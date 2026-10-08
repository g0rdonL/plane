# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Aight fork: monthly per-person export and the carry-over label command."""

import csv
import datetime as dt
import io

import pytest
from django.core.management import call_command

from plane.db.models import (
    Cycle,
    CycleIssue,
    Issue,
    IssueActivity,
    IssueAssignee,
    IssueLabel,
    IssueType,
    Label,
    Project,
    State,
    User,
)
from plane.utils.monthly_summary import monthly_summary
from plane.utils.sprint import SPRINT_TZ


def bkk(day, hour=12):
    return dt.datetime.combine(day, dt.time(hour), tzinfo=SPRINT_TZ)


@pytest.fixture
def project(db, workspace, create_user):
    return Project.objects.create(name="Monthly", identifier="MON", workspace=workspace, created_by=create_user)


@pytest.fixture
def states(project, workspace):
    def make(name, group):
        return State.objects.create(name=name, group=group, project=project, workspace=workspace)

    return {
        "todo": make("Todo", "unstarted"),
        "done": make("Done", "completed"),
        "cancelled": make("Cancelled", "cancelled"),
    }


@pytest.fixture
def sprint(project, workspace, create_user):
    cache = {}

    def make(monday):
        if monday not in cache:
            start = dt.datetime.combine(monday, dt.time.min, tzinfo=SPRINT_TZ)
            cache[monday] = Cycle.objects.create(
                name=f"Sprint {monday.isoformat()}",
                project=project,
                workspace=workspace,
                owned_by=create_user,
                start_date=start,
                end_date=start + dt.timedelta(days=7, minutes=-1),
            )
        return cache[monday]

    return make


@pytest.fixture
def other_user(db):
    return User.objects.create(email="other@plane.so", username="other", first_name="Other", last_name="Person")


@pytest.fixture
def story(project, workspace, create_user, states):
    def make(name, cycle, state="todo", done_on=None, target=None, assignees=(), epic=False):
        issue = Issue.objects.create(
            name=name, project=project, workspace=workspace, state=states[state], created_by=create_user
        )
        Issue.objects.filter(pk=issue.pk).update(
            completed_at=bkk(done_on) if done_on else None,
            target_date=target,
            type=IssueType.objects.get_or_create(workspace=workspace, name="Epic", is_epic=True)[0] if epic else None,
        )
        CycleIssue.objects.create(issue=issue, cycle=cycle, project=project, workspace=workspace)
        IssueActivity.objects.create(
            issue=issue,
            project=project,
            workspace=workspace,
            field="cycles",
            verb="created",
            new_identifier=cycle.id,
            actor=create_user,
        )
        for user in assignees or (create_user,):
            IssueAssignee.objects.create(issue=issue, assignee=user, project=project, workspace=workspace)
        return issue

    return make


def move(issue, old, new):
    """Move a story to another sprint the way Plane does: rewrite the cycle row and log an activity."""
    CycleIssue.objects.filter(issue=issue).update(cycle=new)
    IssueActivity.objects.create(
        issue=issue,
        project=issue.project,
        workspace=issue.workspace,
        field="cycles",
        verb="updated",
        old_identifier=old.id,
        new_identifier=new.id,
        actor=issue.created_by,
    )


def label(issue, name="carry-over"):
    lab, _ = Label.objects.get_or_create(name=name, project=issue.project, workspace=issue.workspace)
    IssueLabel.objects.create(issue=issue, label=lab, project=issue.project, workspace=issue.workspace)


W39, W40, W41, W45 = dt.date(2026, 9, 21), dt.date(2026, 9, 28), dt.date(2026, 10, 5), dt.date(2026, 11, 2)


@pytest.fixture
def scenario(story, sprint, create_user, other_user):
    story(
        "on time, no due date", sprint(W41), "done", done_on=dt.date(2026, 10, 9), assignees=(create_user, other_user)
    )
    story("late vs due date", sprint(W41), "done", done_on=dt.date(2026, 10, 9), target=dt.date(2026, 10, 7))
    carried = story("carried, labelled", sprint(W41))
    move(carried, sprint(W41), sprint(W45))
    label(carried)
    moved = story("moved, unlabelled", sprint(W41))
    move(moved, sprint(W41), sprint(W45))
    story("cancelled", sprint(W41), "cancelled")
    story("W40 is October, done early", sprint(W40), "done", done_on=dt.date(2026, 9, 30))
    story("September only", sprint(W39))
    story("an epic", sprint(W41), epic=True)
    from_sept = story("carried from September, done", sprint(W39), "done", done_on=dt.date(2026, 10, 8))
    move(from_sept, sprint(W39), sprint(W41))


def by_email(rows):
    return {r["email"]: r for r in rows}


@pytest.mark.contract
@pytest.mark.django_db
class TestMonthlySummary:
    def test_october_numbers_follow_the_policy(self, scenario):
        summary, details = monthly_summary(2026, 10)
        me = by_email(summary)["test@plane.so"]

        assert me["planned"] == 6
        assert me["completed"] == 4
        assert me["completion_rate"] == "67%"
        assert me["deadlines_met"] == 3
        assert me["on_time_rate"] == "75%"
        assert me["carry_overs"] == 1
        assert me["unlabelled_moves"] == 1

        mine = {d["title"]: d for d in details if d["email"] == "test@plane.so"}
        assert "cancelled" not in mine and "an epic" not in mine and "September only" not in mine
        assert mine["late vs due date"]["deadline_source"] == "due date"
        assert mine["W40 is October, done early"]["deadline_source"] == "sprint end"

    def test_every_assignee_gets_the_story(self, scenario):
        other = by_email(monthly_summary(2026, 10)[0])["other@plane.so"]
        assert (other["planned"], other["completed"], other["deadlines_met"]) == (1, 1, 1)
        assert other["name"] == "Other Person"

    def test_carry_over_counts_in_both_months_but_completes_once(self, scenario):
        sept = by_email(monthly_summary(2026, 9)[0])["test@plane.so"]
        assert (sept["planned"], sept["completed"], sept["unlabelled_moves"]) == (2, 0, 1)

        nov = by_email(monthly_summary(2026, 11)[0])["test@plane.so"]
        assert (nov["planned"], nov["completed"], nov["carry_overs"]) == (2, 0, 1)

    def test_command_writes_csv_and_warns_about_missing_label(self, project, scenario):
        Label.objects.filter(project=project, name="carry-over").delete()
        out, err = io.StringIO(), io.StringIO()
        call_command("monthly_summary", "--month", "2026-10", stdout=out, stderr=err)

        rows = list(csv.DictReader(io.StringIO(out.getvalue())))
        assert {r["email"] for r in rows} == {"test@plane.so", "other@plane.so"}
        assert "test-workspace/MON has no carry-over label" in err.getvalue()

    def test_detail_csv_has_one_row_per_person_and_story(self, scenario):
        out = io.StringIO()
        call_command("monthly_summary", "--month", "2026-10", "--detail", stdout=out)
        rows = list(csv.DictReader(io.StringIO(out.getvalue())))
        assert len(rows) == 7


@pytest.mark.contract
@pytest.mark.django_db
class TestEnsureCarryOverLabel:
    def test_creates_missing_labels_once_and_copies_style(self, workspace, create_user, project):
        styled = Project.objects.create(name="Styled", identifier="STY", workspace=workspace, created_by=create_user)
        Label.objects.create(
            name="carry-over", color="#123456", description="moved", project=styled, workspace=workspace
        )

        call_command("ensure_carry_over_label", "--actor", create_user.email, "--dry-run", stdout=io.StringIO())
        assert not Label.objects.filter(project=project, name="carry-over").exists()

        call_command("ensure_carry_over_label", "--actor", create_user.email, stdout=io.StringIO())
        call_command("ensure_carry_over_label", "--actor", create_user.email, stdout=io.StringIO())

        created = Label.objects.get(project=project, name="carry-over")
        assert (created.color, created.description) == ("#123456", "moved")
        assert Label.objects.filter(name="carry-over").count() == 2
