# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Contract tests for the API-key (v1) "My sprint" endpoints (Aight fork)."""

import pytest
from rest_framework import status

from plane.db.models import User, WorkspaceMember
from plane.tests.contract.app.test_sprint_capacity_app import make_project, make_story

URL = "/api/v1/users/me/sprint-capacity/"


@pytest.mark.contract
class TestSprintCapacityApiKey:
    @pytest.mark.django_db
    def test_api_key_sees_own_sprint(self, api_key_client, workspace, create_user):
        project, states, points, cycles = make_project(workspace, create_user, "AAA")
        make_story(project, create_user, states["todo"], cycles[0], points["2"], assignee=create_user)

        response = api_key_client.get(URL)
        assert response.status_code == status.HTTP_200_OK, response.data
        assert response.data["capacity"] == 8
        assert response.data["sprints"][0]["planned_points"] == 2

    @pytest.mark.django_db
    def test_api_key_people_and_stranger(self, api_key_client, workspace, create_user):
        mate = User.objects.create(email="mate@plane.so", username="mate")
        WorkspaceMember.objects.create(workspace=workspace, member=mate, role=15)
        stranger = User.objects.create(email="stranger@plane.so", username="stranger")

        ids = {p["id"] for p in api_key_client.get(URL + "people/").data}
        assert str(mate.id) in ids and str(stranger.id) not in ids
        assert api_key_client.get(URL, {"user_id": str(stranger.id)}).status_code == status.HTTP_404_NOT_FOUND

    @pytest.mark.django_db
    def test_requires_api_key(self, api_client):
        assert api_client.get(URL).status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)
        api_client.credentials(HTTP_X_API_KEY="not-a-real-token")
        assert api_client.get(URL).status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)
