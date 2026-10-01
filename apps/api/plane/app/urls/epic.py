# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from django.urls import path

from plane.app.views.issue.epic import EpicAnalyticsEndpoint, WorkItemConvertEndpoint
from plane.app.views.issue.sprint_capacity import SprintCapacityEndpoint, SprintCapacityPeopleEndpoint

PROJECT = "projects/<uuid:project_id>/"

# Epics are work items whose type is the workspace epic type. They reuse the work item
# endpoints under `/epics/`; the views check `is_epic_request` to scope list/create calls.
# Order matters: the specific rewrites must run before the generic `issues/` rewrite.
EPIC_ROUTE_REWRITES = [
    (PROJECT + "issues/<uuid:issue_id>/sub-issues/", PROJECT + "epics/<uuid:issue_id>/issues/"),
    (PROJECT + "issues/<uuid:issue_id>/issue-links/", PROJECT + "epics/<uuid:issue_id>/links/"),
    (PROJECT + "issues-detail/", PROJECT + "epics-detail/"),
    (PROJECT + "v2/issues/", PROJECT + "v2/epics/"),
    (PROJECT + "issues/", PROJECT + "epics/"),
]


def build_epic_urlpatterns(patterns):
    epic_patterns = []
    for pattern in patterns:
        route = str(pattern.pattern)
        for source, target in EPIC_ROUTE_REWRITES:
            if source in route:
                epic_patterns.append(
                    path(
                        route.replace(source, target, 1),
                        pattern.callback,
                        name=f"{pattern.name}-epic" if pattern.name else None,
                    )
                )
                break
    return epic_patterns


urlpatterns = [
    path("users/me/sprint-capacity/", SprintCapacityEndpoint.as_view(), name="user-sprint-capacity"),
    path("users/me/sprint-capacity/people/", SprintCapacityPeopleEndpoint.as_view(), name="user-sprint-capacity-people"),
    path(
        "workspaces/<str:slug>/" + PROJECT + "epics/<uuid:epic_id>/analytics/",
        EpicAnalyticsEndpoint.as_view(),
        name="project-epic-analytics",
    ),
    path(
        "workspaces/<str:slug>/" + PROJECT + "issues/<uuid:issue_id>/convert/",
        WorkItemConvertEndpoint.as_view(),
        name="project-work-item-convert",
    ),
]
