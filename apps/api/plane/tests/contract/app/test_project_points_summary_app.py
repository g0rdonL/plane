# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Contract tests for the project work item list story point sums (Aight fork)."""

import pytest
from rest_framework import status
from rest_framework.test import APIClient

from plane.db.models import (
    Estimate,
    EstimatePoint,
    Issue,
    IssueType,
    Project,
    ProjectMember,
    State,
    User,
    WorkspaceMember,
)

URL = "/api/workspaces/{slug}/projects/{project_id}/issues/points-summary/"


def make_project(workspace, user, identifier):
    project = Project.objects.create(name=identifier, identifier=identifier, workspace=workspace, created_by=user)
    ProjectMember.objects.create(project=project, member=user, workspace=workspace, role=20)
    states = {
        group: State.objects.create(name=group, group=group, project=project, sequence=i)
        for i, group in enumerate(["backlog", "unstarted", "started", "completed"])
    }
    estimate = Estimate.objects.create(name="Half-days", type="points", project=project)
    points = {
        v: EstimatePoint.objects.create(estimate=estimate, key=i, value=v, project=project)
        for i, v in enumerate(["1", "2", "4", "0.5"])
    }
    return project, states, points


def make_story(project, user, state, point=None, parent=None, issue_type=None):
    issue = Issue(
        name="story",
        project=project,
        workspace=project.workspace,
        state=state,
        estimate_point=point,
        parent=parent,
        type=issue_type,
    )
    issue.save(created_by_id=user.id)
    return issue


def summary(client, project, **params):
    response = client.get(URL.format(slug=project.workspace.slug, project_id=project.id), params)
    assert response.status_code == status.HTTP_200_OK, response.data
    return (
        response.data["unstarted_estimate_points"],
        response.data["started_estimate_points"],
        response.data["completed_estimate_points"],
    )


@pytest.mark.contract
class TestProjectPointsSummary:
    @pytest.mark.django_db
    def test_sums_by_state_group(self, session_client, workspace, create_user):
        project, states, pts = make_project(workspace, create_user, "AAA")
        other, other_states, other_pts = make_project(workspace, create_user, "BBB")
        epic_type = IssueType.objects.create(workspace=workspace, name="Epic", is_epic=True)

        make_story(project, create_user, states["unstarted"], pts["2"])
        make_story(project, create_user, states["started"], pts["4"])
        make_story(project, create_user, states["started"], pts["0.5"])
        make_story(project, create_user, states["completed"], pts["1"])
        make_story(project, create_user, states["unstarted"])  # unestimated
        make_story(project, create_user, states["unstarted"], pts["4"], issue_type=epic_type)  # epic
        make_story(other, create_user, other_states["unstarted"], other_pts["4"])  # other project

        assert summary(session_client, project, sub_issue="true") == (2, 4.5, 1)

    @pytest.mark.django_db
    def test_follows_list_filters(self, session_client, workspace, create_user):
        project, states, pts = make_project(workspace, create_user, "AAA")
        epic = make_story(project, create_user, states["started"])
        make_story(project, create_user, states["started"], pts["2"], parent=epic)
        make_story(project, create_user, states["unstarted"], pts["1"])

        # the list can hide sub-work items; the web client always asks for them in the sums
        assert summary(session_client, project, sub_issue="false") == (1, 0, 0)
        assert summary(session_client, project, sub_issue="true") == (1, 2, 0)
        assert summary(session_client, project, sub_issue="true", state=str(states["started"].id)) == (0, 2, 0)

    @pytest.mark.django_db
    def test_guests_only_count_their_own_work_items(self, workspace, create_user):
        project, states, pts = make_project(workspace, create_user, "AAA")
        guest = User.objects.create(email="guest-points@plane.so", username="guest_points")
        WorkspaceMember.objects.create(workspace=workspace, member=guest, role=5)
        ProjectMember.objects.create(project=project, member=guest, workspace=workspace, role=5)
        make_story(project, guest, states["unstarted"], pts["1"])
        make_story(project, create_user, states["unstarted"], pts["4"])

        client = APIClient()
        client.force_authenticate(user=guest)
        assert summary(client, project, sub_issue="true") == (1, 0, 0)
