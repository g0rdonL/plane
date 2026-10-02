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
    IssueActivity,
    IssueAssignee,
    IssueType,
    Profile,
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


def make_story(project, user, state, cycle, point=None, assignee=None, epic_type=None, added_at=None):
    issue = Issue(name="story", project=project, workspace=project.workspace, state=state, estimate_point=point, type=epic_type)
    issue.save(created_by_id=user.id)
    if assignee:
        IssueAssignee.objects.create(issue=issue, assignee=assignee, project=project, workspace=project.workspace)
    link = CycleIssue.objects.create(issue=issue, cycle=cycle, project=project, workspace=project.workspace)
    # planned on Monday unless told otherwise, so results don't depend on the weekday the tests run
    CycleIssue.objects.filter(pk=link.pk).update(created_at=added_at or cycle.start_date)
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
        assert response.data["buffer_capacity"] == 2
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
    def test_stories_added_from_tuesday_count_as_buffer(self, session_client, workspace, create_user):
        p1, s1, pts1, c1 = make_project(workspace, create_user, "AAA")
        tuesday = c1[0].start_date + dt.timedelta(days=1)
        make_story(p1, create_user, s1["todo"], c1[0], pts1["4"], assignee=create_user)  # planned Monday
        make_story(p1, create_user, s1["todo"], c1[0], pts1["1"], assignee=create_user, added_at=tuesday)
        # linked last week, moved into this sprint on Wednesday: the activity log decides
        moved = make_story(p1, create_user, s1["todo"], c1[0], pts1["2"], assignee=create_user,
                           added_at=c1[0].start_date - dt.timedelta(days=3))
        activity = IssueActivity.objects.create(issue=moved, project=p1, workspace=workspace, verb="updated",
                                                field="cycles", new_identifier=c1[0].id, actor=create_user)
        IssueActivity.objects.filter(pk=activity.pk).update(created_at=tuesday + dt.timedelta(days=1))

        current = session_client.get(URL).data["sprints"][0]
        assert current["planned_points"] == 4
        assert current["buffer_points"] == 3
        assert sorted(i["points"] for i in current["items"] if i["is_buffer"]) == [1, 2]

    @pytest.mark.django_db
    def test_people_set_their_own_capacity(self, session_client, workspace, create_user):
        response = session_client.patch(URL, {"planned": 4, "buffer": 1}, format="json")
        assert response.status_code == status.HTTP_200_OK, response.data
        assert Profile.objects.get(user=create_user).goals["sprint_capacity"] == {"planned": 4, "buffer": 1}
        data = session_client.get(URL).data
        assert (data["capacity"], data["buffer_capacity"]) == (4, 1)
        assert session_client.patch(URL, {"buffer": 3}, format="json").data == {"capacity": 4, "buffer_capacity": 3}
        for bad in ({"planned": -1}, {"planned": "x"}, {"buffer": 41}, {"planned": 2.5}, {"planned": True}):
            assert session_client.patch(URL, bad, format="json").status_code == status.HTTP_400_BAD_REQUEST

        teammate = make_user("teammate3@plane.so", workspace)
        assert session_client.get(URL, {"user_id": str(teammate.id)}).data["capacity"] == 8  # default

    @pytest.mark.django_db
    def test_requires_login(self, api_client):
        assert api_client.get(URL).status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)


def make_user(email, workspace=None, role=15):
    user = User.objects.create(email=email, username=email.split("@")[0], display_name=email.split("@")[0])
    if workspace:
        WorkspaceMember.objects.create(workspace=workspace, member=user, role=role)
    return user


@pytest.mark.contract
class TestTeammateSprint:
    @pytest.mark.django_db
    def test_viewer_sees_only_projects_they_belong_to(self, session_client, workspace, create_user):
        # target works in a shared project (AAA) and a private one in another workspace (BBB)
        target = make_user("target@plane.so", workspace)
        other_ws = Workspace.objects.create(name="Private", owner=target, slug="private-ws")
        WorkspaceMember.objects.create(workspace=other_ws, member=target, role=20)
        p1, s1, pts1, c1 = make_project(workspace, create_user, "AAA")
        ProjectMember.objects.create(project=p1, member=target, workspace=workspace, role=15)
        p2, s2, pts2, c2 = make_project(other_ws, target, "BBB")
        make_story(p1, create_user, s1["todo"], c1[0], pts1["2"], assignee=target)
        make_story(p2, target, s2["todo"], c2[0], pts2["4"], assignee=target)

        response = session_client.get(URL, {"user_id": str(target.id)})
        assert response.status_code == status.HTTP_200_OK, response.data
        assert response.data["user"]["is_me"] is False
        current = response.data["sprints"][0]
        assert current["planned_points"] == 6  # totals include hidden work
        assert [i["project_identifier"] for i in current["items"]] == ["AAA"]
        assert current["hidden"] == {"count": 1, "points": 4.0}
        assert "BBB" not in str(response.data) and "private-ws" not in str(response.data)

    @pytest.mark.django_db
    def test_guest_only_sees_own_stories_unless_allowed(self, api_client, workspace, create_user):
        guest = make_user("guest@plane.so", workspace, role=5)
        p1, s1, pts1, c1 = make_project(workspace, create_user, "AAA")
        ProjectMember.objects.create(project=p1, member=guest, workspace=workspace, role=5)
        make_story(p1, create_user, s1["todo"], c1[0], pts1["2"], assignee=create_user)
        api_client.force_authenticate(user=guest)

        current = api_client.get(URL, {"user_id": str(create_user.id)}).data["sprints"][0]
        assert current["items"] == [] and current["hidden"]["count"] == 1
        p1.guest_view_all_features = True
        p1.save(update_fields=["guest_view_all_features"])
        current = api_client.get(URL, {"user_id": str(create_user.id)}).data["sprints"][0]
        assert len(current["items"]) == 1 and current["hidden"]["count"] == 0

    @pytest.mark.django_db
    def test_stranger_is_not_found(self, session_client, workspace):
        stranger = make_user("stranger@plane.so")
        lonely = Workspace.objects.create(name="Lonely", owner=stranger, slug="lonely-ws")
        WorkspaceMember.objects.create(workspace=lonely, member=stranger, role=20)
        assert session_client.get(URL, {"user_id": str(stranger.id)}).status_code == status.HTTP_404_NOT_FOUND

    @pytest.mark.django_db
    def test_people_lists_shared_workspace_members_only(self, session_client, workspace, create_user):
        teammate = make_user("teammate@plane.so", workspace)
        stranger = make_user("stranger2@plane.so")
        bot = make_user("bot@plane.so", workspace)
        bot.is_bot = True
        bot.save(update_fields=["is_bot"])
        ids = {p["id"] for p in session_client.get(URL + "people/").data}
        assert str(teammate.id) in ids and str(create_user.id) in ids
        assert str(stranger.id) not in ids and str(bot.id) not in ids


def collect_ids(payload):
    ids = set()
    if isinstance(payload, dict):
        if "id" in payload and "name" in payload:
            ids.add(str(payload["id"]))
        for value in payload.values():
            ids |= collect_ids(value)
    elif isinstance(payload, list):
        for value in payload:
            ids |= collect_ids(value)
    return ids


@pytest.mark.contract
class TestSprintRichFilter:
    @pytest.mark.django_db
    def test_workspace_view_filters_by_relative_sprint(self, session_client, workspace, create_user):
        import json

        p1, s1, pts1, c1 = make_project(workspace, create_user, "AAA")
        now_story = make_story(p1, create_user, s1["todo"], c1[0], pts1["2"], assignee=create_user)
        next_story = make_story(p1, create_user, s1["todo"], c1[1], pts1["1"], assignee=create_user)
        url = f"/api/workspaces/{workspace.slug}/issues/"

        def ids(expr):
            r = session_client.get(url, {"filters": json.dumps(expr)})
            assert r.status_code == status.HTTP_200_OK, r.data
            return collect_ids(r.data)

        assert ids({"sprint__in": "current"}) >= {str(now_story.id)}
        assert str(next_story.id) not in ids({"sprint__in": "current"})
        assert str(next_story.id) in ids({"sprint__in": "next"})
        both = ids({"and": [{"sprint__in": "current,next"}, {"assignee_id__in": str(create_user.id)}]})
        assert {str(now_story.id), str(next_story.id)} <= both
