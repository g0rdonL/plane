# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Contract tests for epics: work items whose type is the workspace epic type,
served through the `/epics/` aliases of the work item endpoints."""

import pytest
from rest_framework import status

from plane.db.models import Estimate, EstimatePoint, Issue, IssueType, Project, ProjectMember, State

BASE = "/api/workspaces/{slug}/projects/{project_id}"


def collect_ids(payload):
    """Pull every work item id out of a (possibly grouped / paginated) list response."""
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


@pytest.fixture
def project(db, workspace, create_user):
    project = Project.objects.create(name="Epic Project", identifier="EP", workspace=workspace, created_by=create_user)
    ProjectMember.objects.create(project=project, member=create_user, workspace=workspace, role=20)
    return project


@pytest.fixture
def states(project):
    return {
        group: State.objects.create(name=group.title(), group=group, project=project, sequence=i)
        for i, group in enumerate(["backlog", "unstarted", "started", "completed", "cancelled"])
    }


@pytest.fixture
def points(project):
    estimate = Estimate.objects.create(name="Fibonacci", type="points", project=project)
    return {
        value: EstimatePoint.objects.create(estimate=estimate, key=i, value=str(value), project=project)
        for i, value in enumerate([1, 2, 3, 5, 8])
    }


def create(client, workspace, project, kind, data):
    response = client.post(url(workspace, project, f"/{kind}/"), data, format="json")
    assert response.status_code == status.HTTP_201_CREATED, response.data
    return str(response.data["id"])


def url(workspace, project, suffix):
    return BASE.format(slug=workspace.slug, project_id=project.id) + suffix


@pytest.mark.contract
class TestEpics:
    @pytest.mark.django_db
    def test_create_epic_sets_epic_type(self, session_client, workspace, project, states):
        response = session_client.post(url(workspace, project, "/epics/"), {"name": "Checkout revamp"}, format="json")
        assert response.status_code == status.HTTP_201_CREATED, response.data

        epic = Issue.objects.get(pk=response.data["id"])
        assert epic.type is not None and epic.type.is_epic
        assert IssueType.objects.filter(workspace=workspace, is_epic=True).count() == 1

        # A second epic reuses the same type
        session_client.post(url(workspace, project, "/epics/"), {"name": "Onboarding"}, format="json")
        assert IssueType.objects.filter(workspace=workspace, is_epic=True).count() == 1

    @pytest.mark.django_db
    def test_lists_are_scoped(self, session_client, workspace, project, states):
        epic_id = create(session_client, workspace, project, "epics", {"name": "Epic"})
        item_id = create(session_client, workspace, project, "issues", {"name": "Task"})

        for suffix in ["/issues/", "/issues-detail/", "/v2/issues/"]:
            ids = collect_ids(session_client.get(url(workspace, project, suffix)).data)
            assert item_id in ids and epic_id not in ids, (suffix, ids)

        for suffix in ["/epics/", "/epics-detail/", "/v2/epics/"]:
            ids = collect_ids(session_client.get(url(workspace, project, suffix)).data)
            assert epic_id in ids and item_id not in ids, (suffix, ids)

    @pytest.mark.django_db
    def test_detail_reports_is_epic(self, session_client, workspace, project, states):
        epic_id = create(session_client, workspace, project, "epics", {"name": "Epic"})
        item_id = create(session_client, workspace, project, "issues", {"name": "Task"})

        assert session_client.get(url(workspace, project, f"/epics/{epic_id}/")).data["is_epic"] is True
        assert session_client.get(url(workspace, project, f"/issues/{epic_id}/")).data["is_epic"] is True
        assert session_client.get(url(workspace, project, f"/issues/{item_id}/")).data["is_epic"] is False

    @pytest.mark.django_db
    def test_epic_work_items_and_analytics(self, session_client, workspace, project, states, points):
        epic_id = create(session_client, workspace, project, "epics", {"name": "Epic"})

        def make(name, group, point):
            return create(
                session_client,
                workspace,
                project,
                "issues",
                {"name": name, "state_id": str(states[group].id), "estimate_point": str(points[point].id)},
            )

        done = make("Done story", "completed", 5)
        doing = make("Doing story", "started", 3)
        todo = make("Todo story", "unstarted", 8)

        response = session_client.post(
            url(workspace, project, f"/epics/{epic_id}/issues/"), {"sub_issue_ids": [done, doing, todo]}, format="json"
        )
        assert response.status_code in (status.HTTP_200_OK, status.HTTP_201_CREATED), response.data

        children = session_client.get(url(workspace, project, f"/epics/{epic_id}/issues/")).data
        assert {done, doing, todo} <= collect_ids(children)

        analytics = session_client.get(url(workspace, project, f"/epics/{epic_id}/analytics/")).data
        assert analytics["total_issues"] == 3
        assert analytics["completed_issues"] == 1
        assert analytics["started_issues"] == 1
        assert analytics["unstarted_issues"] == 1
        assert analytics["total_estimate_points"] == 16
        assert analytics["completed_estimate_points"] == 5

    @pytest.mark.django_db
    def test_analytics_rejects_non_epic(self, session_client, workspace, project, states):
        item_id = create(session_client, workspace, project, "issues", {"name": "Task"})
        response = session_client.get(url(workspace, project, f"/epics/{item_id}/analytics/"))
        assert response.status_code == status.HTTP_404_NOT_FOUND

    @pytest.mark.django_db
    def test_convert_round_trip(self, session_client, workspace, project, states):
        item_id = create(session_client, workspace, project, "issues", {"name": "Task"})

        response = session_client.post(url(workspace, project, f"/issues/{item_id}/convert/"), {"is_epic": True}, format="json")
        assert response.status_code == status.HTTP_200_OK and response.data["is_epic"] is True
        assert Issue.objects.get(pk=item_id).type.is_epic

        response = session_client.post(
            url(workspace, project, f"/issues/{item_id}/convert/"), {"is_epic": False}, format="json"
        )
        assert response.data["is_epic"] is False
        assert Issue.objects.get(pk=item_id).type is None
