# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Aight fork: a story has at most one assignee, on both the web app API and the public v1 API."""

import pytest
from rest_framework import status

from plane.db.models import Issue, IssueAssignee, Project, ProjectMember, State, User, WorkspaceMember


@pytest.fixture
def project(db, workspace, create_user):
    project = Project.objects.create(name="Solo", identifier="SOLO", workspace=workspace, created_by=create_user)
    ProjectMember.objects.create(project=project, member=create_user, role=20, is_active=True)
    return project


@pytest.fixture
def teammate(db, workspace, project):
    user = User.objects.create(email="teammate@plane.so", username="teammate", first_name="Team", last_name="Mate")
    WorkspaceMember.objects.create(workspace=workspace, member=user, role=15)
    ProjectMember.objects.create(project=project, member=user, role=15, is_active=True)
    return user


@pytest.fixture
def story(db, workspace, project, create_user):
    state = State.objects.create(
        name="Todo", group="unstarted", sequence=1000, default=True, project=project, workspace=workspace
    )
    return Issue.objects.create(name="Story", project=project, workspace=workspace, state=state, created_by=create_user)


def assignee_ids(issue):
    return set(IssueAssignee.objects.filter(issue=issue).values_list("assignee_id", flat=True))


@pytest.mark.contract
class TestSingleAssigneeApp:
    def issue_url(self, slug, project_id, issue_id=None):
        base = f"/api/workspaces/{slug}/projects/{project_id}/issues/"
        return f"{base}{issue_id}/" if issue_id else base

    @pytest.mark.django_db
    def test_update_with_two_assignees_is_rejected(
        self, session_client, workspace, project, story, create_user, teammate
    ):
        response = session_client.patch(
            self.issue_url(workspace.slug, project.id, story.id),
            {"assignee_ids": [str(create_user.id), str(teammate.id)]},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "assignee_ids" in response.data
        assert assignee_ids(story) == set()

    @pytest.mark.django_db
    def test_update_with_one_assignee_replaces(self, session_client, workspace, project, story, create_user, teammate):
        url = self.issue_url(workspace.slug, project.id, story.id)

        for user in (create_user, teammate):
            response = session_client.patch(url, {"assignee_ids": [str(user.id)]}, format="json")
            assert response.status_code == status.HTTP_204_NO_CONTENT, response.data

        assert assignee_ids(story) == {teammate.id}

    @pytest.mark.django_db
    def test_create_with_two_assignees_is_rejected(self, session_client, workspace, project, create_user, teammate):
        response = session_client.post(
            self.issue_url(workspace.slug, project.id),
            {"name": "Pair", "assignee_ids": [str(create_user.id), str(teammate.id)]},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert not Issue.objects.filter(project=project, name="Pair").exists()


@pytest.mark.contract
class TestSingleAssigneePublicApi:
    def issue_url(self, slug, project_id, issue_id):
        return f"/api/v1/workspaces/{slug}/projects/{project_id}/issues/{issue_id}/"

    @pytest.mark.django_db
    def test_update_with_two_assignees_is_rejected(
        self, api_key_client, workspace, project, story, create_user, teammate
    ):
        response = api_key_client.patch(
            self.issue_url(workspace.slug, project.id, story.id),
            {"assignees": [str(create_user.id), str(teammate.id)]},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert assignee_ids(story) == set()

    @pytest.mark.django_db
    def test_update_with_one_assignee_succeeds(self, api_key_client, workspace, project, story, teammate):
        response = api_key_client.patch(
            self.issue_url(workspace.slug, project.id, story.id),
            {"assignees": [str(teammate.id)]},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK, response.data
        assert assignee_ids(story) == {teammate.id}
