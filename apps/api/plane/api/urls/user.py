# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from django.urls import path

from plane.api.views import UserEndpoint
from plane.api.views.sprint_capacity import ApiKeySprintCapacityEndpoint, ApiKeySprintCapacityPeopleEndpoint

urlpatterns = [
    path(
        "users/me/",
        UserEndpoint.as_view(http_method_names=["get"]),
        name="users",
    ),
    # Aight fork: "My sprint" for API-key callers (Jarvis plane-broker)
    path("users/me/sprint-capacity/", ApiKeySprintCapacityEndpoint.as_view(), name="api-user-sprint-capacity"),
    path(
        "users/me/sprint-capacity/people/",
        ApiKeySprintCapacityPeopleEndpoint.as_view(),
        name="api-user-sprint-capacity-people",
    ),
]
