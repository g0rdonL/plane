# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Aight fork: a story moved to Done joins the current sprint."""

import json
from datetime import timedelta

import pytest
from django.utils import timezone

from plane.bgtasks.issue_activities_task import issue_activity
from plane.db.models import Cycle, CycleIssue, Issue, IssueActivity, IssueType, Project, ProjectMember, State


@pytest.fixture
def project(db, workspace, create_user):
    project = Project.objects.create(name="Done", identifier="DON", workspace=workspace, created_by=create_user)
    ProjectMember.objects.create(project=project, member=create_user, role=20, is_active=True)
    return project


@pytest.fixture
def states(project, workspace):
    def make(name, group, sequence):
        return State.objects.create(name=name, group=group, sequence=sequence, project=project, workspace=workspace)

    return {
        "todo": make("Todo", "unstarted", 1000),
        "started": make("In Progress", "started", 2000),
        "done": make("Done", "completed", 3000),
        "closed": make("Closed", "completed", 4000),
    }


@pytest.fixture
def make_cycle(project, workspace, create_user):
    def make(start_days, end_days, name="Sprint"):
        now = timezone.now()
        return Cycle.objects.create(
            name=name,
            project=project,
            workspace=workspace,
            owned_by=create_user,
            start_date=now + timedelta(days=start_days),
            end_date=now + timedelta(days=end_days),
        )

    return make


@pytest.fixture
def make_issue(project, workspace, create_user):
    def make(state, **kwargs):
        return Issue.objects.create(
            name="Story", project=project, workspace=workspace, state=state, created_by=create_user, **kwargs
        )

    return make


def in_cycle(issue, cycle):
    return CycleIssue.objects.create(
        issue=issue, cycle=cycle, project=issue.project, workspace=issue.workspace, created_by=issue.created_by
    )


def change_state(issue, old_state, new_state, actor):
    """Move the issue and run the activity task the way the issue PATCH endpoints queue it."""
    Issue.objects.filter(pk=issue.pk).update(state=new_state)
    issue_activity(
        type="issue.activity.updated",
        requested_data=json.dumps({"state_id": str(new_state.id)}),
        current_instance=json.dumps({"state_id": str(old_state.id)}),
        issue_id=str(issue.id),
        actor_id=str(actor.id),
        project_id=str(issue.project_id),
        epoch=int(timezone.now().timestamp()),
    )


def cycles_of(issue):
    return list(CycleIssue.objects.filter(issue=issue).values_list("cycle_id", flat=True))


@pytest.mark.contract
class TestDoneJoinsCurrentSprint:
    @pytest.mark.django_db
    def test_story_without_sprint_joins_current(self, create_user, states, make_cycle, make_issue):
        current = make_cycle(-2, 4)
        story = make_issue(states["started"])

        change_state(story, states["started"], states["done"], create_user)

        assert cycles_of(story) == [current.id]
        activity = IssueActivity.objects.get(issue=story, field="cycles")
        assert activity.verb == "created" and activity.new_identifier == current.id

    @pytest.mark.django_db
    @pytest.mark.parametrize("window", [(-21, -14), (14, 21)], ids=["past", "future"])
    def test_story_in_other_sprint_moves_to_current(self, create_user, states, make_cycle, make_issue, window):
        other = make_cycle(*window, name="Other")
        current = make_cycle(-2, 4)
        story = make_issue(states["started"])
        in_cycle(story, other)

        change_state(story, states["started"], states["done"], create_user)

        assert cycles_of(story) == [current.id]
        activity = IssueActivity.objects.get(issue=story, field="cycles")
        assert activity.verb == "updated"
        assert (activity.old_identifier, activity.new_identifier) == (other.id, current.id)

    @pytest.mark.django_db
    def test_story_already_in_current_sprint_stays(self, create_user, states, make_cycle, make_issue):
        current = make_cycle(-2, 4)
        story = make_issue(states["started"])
        in_cycle(story, current)

        change_state(story, states["started"], states["done"], create_user)

        assert cycles_of(story) == [current.id]
        assert not IssueActivity.objects.filter(issue=story, field="cycles").exists()

    @pytest.mark.django_db
    def test_no_current_sprint_leaves_story_alone(self, create_user, states, make_cycle, make_issue):
        make_cycle(-21, -14)
        story = make_issue(states["started"])

        change_state(story, states["started"], states["done"], create_user)

        assert cycles_of(story) == []

    @pytest.mark.django_db
    def test_only_a_move_into_done_triggers(self, create_user, states, make_cycle, make_issue):
        make_cycle(-2, 4)
        started = make_issue(states["todo"])
        already_done = make_issue(states["done"])

        change_state(started, states["todo"], states["started"], create_user)
        change_state(already_done, states["done"], states["closed"], create_user)

        assert cycles_of(started) == []
        assert cycles_of(already_done) == []
        # the state change itself is still recorded
        assert IssueActivity.objects.filter(issue=started, field="state").exists()

    @pytest.mark.django_db
    def test_epics_are_left_out(self, create_user, workspace, states, make_cycle, make_issue):
        make_cycle(-2, 4)
        epic_type = IssueType.objects.create(workspace=workspace, name="Epic", is_epic=True)
        epic = make_issue(states["started"], type=epic_type)

        change_state(epic, states["started"], states["done"], create_user)

        assert cycles_of(epic) == []
