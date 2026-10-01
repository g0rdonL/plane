# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Contract tests for the cross-workspace sprint capacity endpoint (Aight fork)."""

import datetime as dt

import pytest
from django.utils import timezone
from rest_framework import status

from plane.app.views.issue.sprint_capacity import SPRINT_TZ
from plane.db.models import (
    Cycle,
    CycleIssue,
    Estimate,
    EstimatePoint,
    Issue,
    IssueAssignee,
    IssueType,
    Project,
    ProjectMember,
    State,
    User,
    Workspace,
    WorkspaceMember,
)

URL = "/api/users/me/sprint-capacity/"


def week_bounds(offset):
    today = timezone.now().astimezone(SPRINT_TZ).date()
    monday = today - dt.timedelta(days=today.weekday()) + dt.timedelta(weeks=offset)
    start = dt.datetime.combine(monday, dt.time.min, tzinfo=SPRINT_TZ)
    return start, start + dt.timedelta(days=7) - dt.timedelta(seconds=1)


def make_project(workspace, user, identifier):
    project = Project.objects.create(name=identifier, identifier=identifier, workspace=workspace, created_by=user)
    ProjectMember.objects.create(project=project, member=user, workspace=workspace, role=20)
    states = {
        "todo": State.objects.create(name="Todo", group="unstarted", project=project, sequence=1),
        "done": State.objects.create(name="Done", group="completed", project=project, sequence=2),
    }
    estimate = Estimate.objects.create(name="Half-days", type="points", project=project)
    points = {v: EstimatePoint.objects.create(estimate=estimate, key=i, value=v, project=project) for i, v in enumerate(["0", "1", "2", "4", "6"])}
    cycles = []
    for offset in (0, 1):
        start, end = week_bounds(offset)
        cycles.append(Cycle.objects.create(name=f"Sprint {offset}", project=project, start_date=start, end_date=end, owned_by=user))
    return project, states, points, cycles


def make_story(project, user, state, cycle, point=None, assignee=None, epic_type=None):
    issue = Issue(name="story", project=project, workspace=project.workspace, state=state, estimate_point=point, type=epic_type)
    issue.save(created_by_id=user.id)
    if assignee:
        IssueAssignee.objects.create(issue=issue, assignee=assignee, project=project, workspace=project.workspace)
    CycleIssue.objects.create(issue=issue, cycle=cycle, project=project, workspace=project.workspace)
    return issue


@pytest.mark.contract
class TestSprintCapacity:
    @pytest.mark.django_db
    def test_totals_across_workspaces(self, session_client, workspace, create_user):
        other_ws = Workspace.objects.create(name="Other", owner=create_user, slug="other-ws")
        WorkspaceMember.objects.create(workspace=other_ws, member=create_user, role=20)
        someone = User.objects.create(email="someone@plane.so", username="someone")

        p1, s1, pts1, c1 = make_project(workspace, create_user, "AAA")
        p2, s2, pts2, c2 = make_project(other_ws, create_user, "BBB")
        epic_type = IssueType.objects.create(workspace=workspace, name="Epic", is_epic=True)

        make_story(p1, create_user, s1["todo"], c1[0], pts1["2"], assignee=create_user)
        make_story(p2, create_user, s2["done"], c2[0], pts2["4"], assignee=create_user)
        make_story(p2, create_user, s2["todo"], c2[0], None, assignee=create_user)  # unestimated
        make_story(p1, create_user, s1["todo"], c1[0], pts1["6"], assignee=someone)  # someone else's
        make_story(p1, create_user, s1["todo"], c1[0], pts1["6"], assignee=create_user, epic_type=epic_type)  # epic
        make_story(p1, create_user, s1["todo"], c1[1], pts1["1"], assignee=create_user)  # next week

        response = session_client.get(URL)
        assert response.status_code == status.HTTP_200_OK, response.data
        assert response.data["capacity"] == 8
        current, upcoming = response.data["sprints"]

        assert current["is_current"] is True
        assert current["planned_points"] == 6
        assert current["done_points"] == 4
        assert current["unestimated"] == 1
        assert {i["project_identifier"] for i in current["items"]} == {"AAA", "BBB"}
        assert {i["workspace_slug"] for i in current["items"]} == {workspace.slug, "other-ws"}
        assert len(current["items"]) == 3

        assert upcoming["is_current"] is False
        assert upcoming["planned_points"] == 1
        assert len(upcoming["items"]) == 1

    @pytest.mark.django_db
    def test_requires_login(self, api_client):
        assert api_client.get(URL).status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)
