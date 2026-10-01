# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""API-key (v1) access to the Aight fork's "My sprint" endpoints, for agents such as Jarvis.

Same views and visibility rules as /api/users/me/sprint-capacity/; only authentication and
throttling follow the public API.
"""

from plane.api.middleware.api_authentication import APIKeyAuthentication
from plane.api.rate_limit import ApiKeyRateThrottle
from plane.app.views.issue.sprint_capacity import SprintCapacityEndpoint, SprintCapacityPeopleEndpoint


class ApiKeySprintCapacityEndpoint(SprintCapacityEndpoint):
    authentication_classes = [APIKeyAuthentication]

    def get_throttles(self):
        return [ApiKeyRateThrottle()]


class ApiKeySprintCapacityPeopleEndpoint(SprintCapacityPeopleEndpoint):
    authentication_classes = [APIKeyAuthentication]

    def get_throttles(self):
        return [ApiKeyRateThrottle()]
