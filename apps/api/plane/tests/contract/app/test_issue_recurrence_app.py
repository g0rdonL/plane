# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Aight fork: recurring stories — model, generator and API."""

import datetime as dt

import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework import status

from plane.db.models import (
    Issue,
    IssueAssignee,
    IssueComment,
    IssueLabel,
    IssueRecurrence,
    IssueRecurrenceRun,
    Label,
    Module,
    ModuleIssue,
    Project,
    ProjectMember,
    State,
    User,
    WorkspaceMember,
)

UTC = dt.timezone.utc


@pytest.fixture
def project(db, workspace, create_user):
    project = Project.objects.create(
        name="Ops", identifier="OPS", workspace=workspace, created_by=create_user, timezone="Asia/Bangkok"
    )
    ProjectMember.objects.create(project=project, member=create_user, role=20, is_active=True)
    return project


@pytest.fixture
def states(project, workspace):
    def make(name, group, sequence, default=False):
        return State.objects.create(
            name=name, group=group, sequence=sequence, default=default, project=project, workspace=workspace
        )

    return {
        "backlog": make("Backlog", "backlog", 1000, default=True),
        "todo": make("Todo", "unstarted", 2000),
        "done": make("Done", "completed", 3000),
    }


@pytest.fixture
def teammate(db, workspace, project):
    user = User.objects.create(email="mate@plane.so", username="mate", first_name="Team", last_name="Mate")
    WorkspaceMember.objects.create(workspace=workspace, member=user, role=15)
    ProjectMember.objects.create(project=project, member=user, role=15, is_active=True)
    return user


@pytest.fixture
def template(project, workspace, states, create_user):
    # disable_auto_set_user: BaseModel.save() would otherwise reset created_by to the (absent) request user
    issue = Issue(
        name="Payroll checklist",
        description_html="<p>Run payroll</p>",
        priority="high",
        project=project,
        workspace=workspace,
        state=states["done"],
        created_by=create_user,
    )
    issue.save(disable_auto_set_user=True)
    return issue


def make_rule(template, actor, next_run_at, frequency="daily", weekdays=None, day_of_month=None):
    return IssueRecurrence.objects.create(
        issue=template,
        project=template.project,
        frequency=frequency,
        weekdays=weekdays or [],
        day_of_month=day_of_month,
        next_run_at=next_run_at,
        actor=actor,
    )


@pytest.mark.contract
class TestRecurrenceModels:
    @pytest.mark.django_db
    def test_one_active_rule_per_story(self, template, create_user):
        make_rule(template, create_user, timezone.now())
        with pytest.raises(IntegrityError), transaction.atomic():
            make_rule(template, create_user, timezone.now())

    @pytest.mark.django_db
    def test_soft_deleted_rule_does_not_block_new_one(self, template, create_user):
        make_rule(template, create_user, timezone.now()).delete()
        assert make_rule(template, create_user, timezone.now()).pk

    @pytest.mark.django_db
    def test_one_run_per_occurrence_date(self, template, create_user):
        rule = make_rule(template, create_user, timezone.now())
        IssueRecurrenceRun.objects.create(recurrence=rule, project=rule.project, occurrence_date=dt.date(2026, 10, 13))
        with pytest.raises(IntegrityError), transaction.atomic():
            IssueRecurrenceRun.objects.create(
                recurrence=rule, project=rule.project, occurrence_date=dt.date(2026, 10, 13)
            )

    @pytest.mark.django_db
    def test_tz_comes_from_project(self, template, create_user):
        assert str(make_rule(template, create_user, timezone.now()).tz) == "Asia/Bangkok"


from plane.bgtasks.recurrence_task import create_due_recurring_issues  # noqa: E402

# Mon 13 Oct 2026 08:00 Bangkok
FIRST = dt.datetime(2026, 10, 13, 1, 0, tzinfo=UTC)


def run(now):
    return create_due_recurring_issues(now_iso=now.isoformat())


def copies(rule):
    return Issue.objects.filter(recurrence_runs__recurrence=rule).order_by("created_at")


@pytest.mark.contract
class TestRecurrenceGenerator:
    @pytest.mark.django_db
    def test_not_due_creates_nothing(self, template, create_user):
        rule = make_rule(template, create_user, FIRST)
        assert run(FIRST - dt.timedelta(minutes=1)) == 0
        assert not copies(rule).exists()

    @pytest.mark.django_db
    def test_due_creates_copy_with_template_fields(self, template, states, create_user, teammate, project, workspace):
        label = Label.objects.create(name="hr", project=project, workspace=workspace)
        IssueLabel.objects.create(issue=template, label=label, project=project, workspace=workspace)
        IssueAssignee.objects.create(issue=template, assignee=teammate, project=project, workspace=workspace)
        module = Module.objects.create(name="Ops", project=project, workspace=workspace)
        ModuleIssue.objects.create(issue=template, module=module, project=project, workspace=workspace)
        rule = make_rule(template, create_user, FIRST)

        assert run(FIRST + dt.timedelta(minutes=5)) == 1

        copy = copies(rule).get()
        assert copy.id != template.id
        assert copy.name == "Payroll checklist"
        assert copy.description_html == "<p>Run payroll</p>"
        assert copy.priority == "high"
        assert copy.state_id == states["todo"].id
        assert copy.target_date == dt.date(2026, 10, 13)
        assert copy.start_date is None
        assert copy.created_by_id == create_user.id
        assert list(IssueAssignee.objects.filter(issue=copy).values_list("assignee_id", flat=True)) == [teammate.id]
        assert list(IssueLabel.objects.filter(issue=copy).values_list("label_id", flat=True)) == [label.id]
        assert list(ModuleIssue.objects.filter(issue=copy).values_list("module_id", flat=True)) == [module.id]
        assert not copy.issue_cycle.exists()
        comment = IssueComment.objects.get(issue=copy)
        assert f"OPS-{template.sequence_id}" in comment.comment_html
        assert "repeats daily" in comment.comment_html

    @pytest.mark.django_db
    def test_advances_next_run(self, template, create_user):
        rule = make_rule(template, create_user, FIRST)
        run(FIRST)
        rule.refresh_from_db()
        assert rule.last_run_at == FIRST
        assert rule.next_run_at == FIRST + dt.timedelta(days=1)

    @pytest.mark.django_db
    def test_running_twice_creates_one_copy(self, template, create_user):
        rule = make_rule(template, create_user, FIRST)
        run(FIRST)
        run(FIRST + dt.timedelta(minutes=15))
        assert copies(rule).count() == 1

    @pytest.mark.django_db
    def test_existing_run_row_is_not_recreated(self, template, create_user):
        # crash after the run row was written but before next_run_at advanced
        rule = make_rule(template, create_user, FIRST)
        IssueRecurrenceRun.objects.create(recurrence=rule, project=rule.project, occurrence_date=dt.date(2026, 10, 13))
        assert run(FIRST) == 0
        rule.refresh_from_db()
        assert rule.next_run_at == FIRST + dt.timedelta(days=1)

    @pytest.mark.django_db
    def test_missed_runs_collapse_to_latest(self, template, create_user):
        rule = make_rule(template, create_user, FIRST)
        # worker down for 3 days → one copy, dated the latest missed day (Thu 16 Oct)
        assert run(FIRST + dt.timedelta(days=3, hours=1)) == 1
        assert copies(rule).get().target_date == dt.date(2026, 10, 16)
        rule.refresh_from_db()
        assert rule.next_run_at == FIRST + dt.timedelta(days=4)

    @pytest.mark.django_db
    def test_archived_template_deactivates(self, template, create_user):
        rule = make_rule(template, create_user, FIRST)
        Issue.objects.filter(pk=template.pk).update(archived_at=dt.date(2026, 10, 12))
        assert run(FIRST) == 0
        rule.refresh_from_db()
        assert rule.is_active is False

    @pytest.mark.django_db
    def test_deleted_template_deactivates(self, template, create_user):
        rule = make_rule(template, create_user, FIRST)
        Issue.all_objects.filter(pk=template.pk).update(deleted_at=timezone.now())
        assert run(FIRST) == 0
        assert IssueRecurrence.all_objects.get(pk=rule.pk).is_active is False

    @pytest.mark.django_db
    def test_actor_left_falls_back_to_template_creator(self, template, create_user, teammate, project):
        rule = make_rule(template, teammate, FIRST)
        ProjectMember.objects.filter(project=project, member=teammate).update(is_active=False)
        run(FIRST)
        assert copies(rule).get().created_by_id == create_user.id

    @pytest.mark.django_db
    def test_falls_back_to_default_state_without_unstarted(self, template, states, create_user):
        State.objects.filter(pk=states["todo"].pk).delete()
        rule = make_rule(template, create_user, FIRST)
        run(FIRST)
        assert copies(rule).get().state_id == states["backlog"].id

    @pytest.mark.django_db
    def test_one_broken_rule_does_not_stop_others(self, template, create_user, project, workspace, states):
        other = Issue.objects.create(name="Other", project=project, workspace=workspace, created_by=create_user)
        broken = make_rule(other, create_user, FIRST, frequency="weekly", weekdays=[])  # never matches → ValueError
        good = make_rule(template, create_user, FIRST)
        assert run(FIRST) == 1
        assert copies(good).count() == 1
        assert not copies(broken).exists()


@pytest.mark.contract
class TestRecurrenceApi:
    def url(self, workspace, project, issue):
        return f"/api/workspaces/{workspace.slug}/projects/{project.id}/issues/{issue.id}/recurrence/"

    @pytest.mark.django_db
    def test_get_without_rule_is_404(self, session_client, workspace, project, template):
        assert session_client.get(self.url(workspace, project, template)).status_code == status.HTTP_404_NOT_FOUND

    @pytest.mark.django_db
    def test_put_weekly_then_get(self, session_client, workspace, project, template, create_user):
        response = session_client.put(
            self.url(workspace, project, template), {"frequency": "weekly", "weekdays": [4, 0]}, format="json"
        )
        assert response.status_code == status.HTTP_200_OK, response.data
        assert response.data["frequency"] == "weekly"
        assert response.data["weekdays"] == [0, 4]
        assert response.data["day_of_month"] is None
        assert response.data["is_active"] is True
        rule = IssueRecurrence.objects.get(issue=template)
        assert rule.actor_id == create_user.id
        assert rule.next_run_at > timezone.now()
        assert session_client.get(self.url(workspace, project, template)).data["frequency"] == "weekly"

    @pytest.mark.django_db
    def test_put_replaces_existing_rule(self, session_client, workspace, project, template):
        url = self.url(workspace, project, template)
        session_client.put(url, {"frequency": "daily"}, format="json")
        response = session_client.put(url, {"frequency": "monthly", "day_of_month": 31}, format="json")
        assert response.status_code == status.HTTP_200_OK, response.data
        assert IssueRecurrence.objects.filter(issue=template).count() == 1
        assert IssueRecurrence.objects.get(issue=template).day_of_month == 31

    @pytest.mark.django_db
    def test_delete_then_set_again(self, session_client, workspace, project, template):
        url = self.url(workspace, project, template)
        session_client.put(url, {"frequency": "daily"}, format="json")
        assert session_client.delete(url).status_code == status.HTTP_204_NO_CONTENT
        assert session_client.get(url).status_code == status.HTTP_404_NOT_FOUND
        assert session_client.put(url, {"frequency": "weekdays"}, format="json").status_code == status.HTTP_200_OK

    @pytest.mark.django_db
    @pytest.mark.parametrize(
        "body",
        [
            {"frequency": "hourly"},
            {"frequency": "weekly"},
            {"frequency": "weekly", "weekdays": []},
            {"frequency": "weekly", "weekdays": [7]},
            {"frequency": "monthly"},
            {"frequency": "monthly", "day_of_month": 0},
            {"frequency": "monthly", "day_of_month": 32},
            {"frequency": "daily", "weekdays": [1]},
            {"frequency": "weekdays", "day_of_month": 3},
        ],
    )
    def test_invalid_bodies_are_400(self, session_client, workspace, project, template, body):
        response = session_client.put(self.url(workspace, project, template), body, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert not IssueRecurrence.objects.filter(issue=template).exists()

    @pytest.mark.django_db
    def test_guest_cannot_set(self, api_client, workspace, project, template):
        guest = User.objects.create(email="guest@plane.so", username="guest")
        WorkspaceMember.objects.create(workspace=workspace, member=guest, role=5)
        ProjectMember.objects.create(project=project, member=guest, role=5, is_active=True)
        api_client.force_authenticate(user=guest)
        response = api_client.put(self.url(workspace, project, template), {"frequency": "daily"}, format="json")
        assert response.status_code == status.HTTP_403_FORBIDDEN

    @pytest.mark.django_db
    def test_issue_detail_includes_recurrence(self, session_client, workspace, project, template):
        detail = f"/api/workspaces/{workspace.slug}/projects/{project.id}/issues/{template.id}/"
        assert session_client.get(detail).data["recurrence"] is None
        session_client.put(self.url(workspace, project, template), {"frequency": "daily"}, format="json")
        assert session_client.get(detail).data["recurrence"]["frequency"] == "daily"
