# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Aight fork: a story in a sprint is never Backlog."""

from datetime import timedelta

import pytest
from django.core.management import call_command
from django.utils import timezone
from rest_framework import status

from plane.db.models import Cycle, CycleIssue, Issue, Project, ProjectMember, State


@pytest.fixture
def project(db, workspace, create_user):
    project = Project.objects.create(name="Sprint", identifier="SPR", workspace=workspace, created_by=create_user)
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
        "started": make("In Progress", "started", 3000),
    }


@pytest.fixture
def make_issue(project, workspace, create_user):
    def make(state, name="Story"):
        return Issue.objects.create(name=name, project=project, workspace=workspace, state=state, created_by=create_user)

    return make


@pytest.fixture
def make_cycle(project, workspace, create_user):
    def make(end_offset_days=3, name="Sprint"):
        now = timezone.now()
        return Cycle.objects.create(
            name=name,
            project=project,
            workspace=workspace,
            owned_by=create_user,
            start_date=now - timedelta(days=7) + timedelta(days=end_offset_days),
            end_date=now + timedelta(days=end_offset_days),
        )

    return make


def in_cycle(issue, cycle):
    return CycleIssue.objects.create(
        issue=issue, cycle=cycle, project=issue.project, workspace=issue.workspace, created_by=issue.created_by
    )


@pytest.mark.contract
class TestSprintBacklog:
    def cycle_url(self, slug, project_id, cycle_id):
        return f"/api/workspaces/{slug}/projects/{project_id}/cycles/{cycle_id}/cycle-issues/"

    def issue_url(self, slug, project_id, issue_id):
        return f"/api/workspaces/{slug}/projects/{project_id}/issues/{issue_id}/"

    @pytest.mark.django_db
    def test_adding_backlog_story_promotes_to_todo(
        self, session_client, workspace, project, states, make_issue, make_cycle
    ):
        backlog_story = make_issue(states["backlog"])
        started_story = make_issue(states["started"])
        cycle = make_cycle()

        response = session_client.post(
            self.cycle_url(workspace.slug, project.id, cycle.id),
            {"issues": [str(backlog_story.id), str(started_story.id)]},
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED, response.data
        assert response.data["promoted"] == {str(backlog_story.id): str(states["todo"].id)}
        backlog_story.refresh_from_db()
        started_story.refresh_from_db()
        assert backlog_story.state_id == states["todo"].id
        assert started_story.state_id == states["started"].id

    @pytest.mark.django_db
    def test_moving_backlog_story_between_sprints_promotes_it(
        self, session_client, workspace, project, states, make_issue, make_cycle
    ):
        story = make_issue(states["backlog"])
        in_cycle(story, make_cycle(name="This week"))
        next_cycle = make_cycle(end_offset_days=10, name="Next week")

        response = session_client.post(
            self.cycle_url(workspace.slug, project.id, next_cycle.id), {"issues": [str(story.id)]}, format="json"
        )

        assert response.status_code == status.HTTP_201_CREATED, response.data
        story.refresh_from_db()
        assert story.state_id == states["todo"].id

    @pytest.mark.django_db
    def test_setting_backlog_on_sprint_story_is_rejected(
        self, session_client, workspace, project, states, make_issue, make_cycle
    ):
        story = make_issue(states["todo"])
        in_cycle(story, make_cycle())

        response = session_client.patch(
            self.issue_url(workspace.slug, project.id, story.id), {"state_id": str(states["backlog"].id)}, format="json"
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "state" in response.data
        story.refresh_from_db()
        assert story.state_id == states["todo"].id

    @pytest.mark.django_db
    def test_setting_backlog_outside_open_sprint_is_allowed(
        self, session_client, workspace, project, states, make_issue, make_cycle
    ):
        unsprinted = make_issue(states["todo"], name="No sprint")
        finished = make_issue(states["todo"], name="Old sprint")
        in_cycle(finished, make_cycle(end_offset_days=-2))

        for story in (unsprinted, finished):
            response = session_client.patch(
                self.issue_url(workspace.slug, project.id, story.id),
                {"state_id": str(states["backlog"].id)},
                format="json",
            )
            assert response.status_code == status.HTTP_204_NO_CONTENT, response.data
            story.refresh_from_db()
            assert story.state_id == states["backlog"].id

    @pytest.mark.django_db
    def test_backfill_command(self, workspace, project, states, make_issue, make_cycle, create_user):
        open_story = make_issue(states["backlog"], name="Open sprint")
        old_story = make_issue(states["backlog"], name="Old sprint")
        in_cycle(open_story, make_cycle())
        in_cycle(old_story, make_cycle(end_offset_days=-2))

        call_command("promote_sprint_backlog", "--actor", create_user.email, "--dry-run")
        open_story.refresh_from_db()
        assert open_story.state_id == states["backlog"].id

        call_command("promote_sprint_backlog", "--actor", create_user.email)
        open_story.refresh_from_db()
        old_story.refresh_from_db()
        assert open_story.state_id == states["todo"].id
        assert old_story.state_id == states["backlog"].id
