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
