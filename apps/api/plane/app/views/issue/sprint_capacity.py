# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Python imports
import datetime as dt
import zoneinfo

# Django imports
from django.utils import timezone

# Third Party imports
from rest_framework import status
from rest_framework.response import Response

# Module imports
from .. import BaseAPIView
from plane.db.models import Cycle, Issue, ProjectMember, User, WorkspaceMember

# Aight fork: sprints are weekly, Monday 00:00 to Sunday 23:59 Hong Kong time, and each IC plans
# 8 points per sprint across every workspace and project (Plane User Convention).
SPRINT_TZ = zoneinfo.ZoneInfo("Asia/Hong_Kong")
SPRINT_CAPACITY = 8
GUEST = 5


def _points(issue):
    try:
        return float(issue.estimate_point.value) if issue.estimate_point_id else None
    except (TypeError, ValueError):
        return None


def _shared_workspace_ids(viewer, target):
    viewer_ws = WorkspaceMember.objects.filter(member=viewer, is_active=True).values_list("workspace_id", flat=True)
    return set(
        WorkspaceMember.objects.filter(member=target, is_active=True, workspace_id__in=viewer_ws).values_list(
            "workspace_id", flat=True
        )
    )


def _viewer_access(viewer):
    """project_id -> (role, guest_view_all_features) for the viewer's active project memberships."""
    return {
        m.project_id: (m.role, m.project.guest_view_all_features)
        for m in ProjectMember.objects.filter(member=viewer, is_active=True).select_related("project")
    }


def _can_view(issue, viewer, access):
    if issue.project_id not in access:
        return False
    role, guest_view_all = access[issue.project_id]
    return role > GUEST or guest_view_all or issue.created_by_id == viewer.id


class SprintCapacityEndpoint(BaseAPIView):
    """A user's stories in this week's and next week's sprints, across all workspaces.

    Defaults to the requesting user. With ?user_id=, shows a teammate who shares at least one workspace
    with the viewer; stories in projects the viewer cannot see are counted but not described.
    """

    def get(self, request):
        viewer = request.user
        target = viewer
        user_id = request.query_params.get("user_id")
        if user_id and str(user_id) != str(viewer.id):
            target = User.objects.filter(pk=user_id, is_active=True, is_bot=False).first()
            if target is None or not _shared_workspace_ids(viewer, target):
                return Response({"error": "User not found"}, status=status.HTTP_404_NOT_FOUND)
        access = _viewer_access(viewer)

        today = timezone.now().astimezone(SPRINT_TZ).date()
        this_monday = today - dt.timedelta(days=today.weekday())
        project_ids = ProjectMember.objects.filter(
            member=target, is_active=True, project__archived_at__isnull=True
        ).values_list("project_id", flat=True)

        sprints = []
        for offset in (0, 1):
            monday = this_monday + dt.timedelta(weeks=offset)
            week_start = dt.datetime.combine(monday, dt.time.min, tzinfo=SPRINT_TZ)
            week_end = week_start + dt.timedelta(days=7)
            cycles = Cycle.objects.filter(project_id__in=project_ids, start_date__lt=week_end, end_date__gt=week_start)
            issues = (
                Issue.issue_objects.filter(
                    issue_cycle__cycle__in=cycles,
                    issue_cycle__deleted_at__isnull=True,
                    issue_assignee__assignee=target,
                    issue_assignee__deleted_at__isnull=True,
                )
                .exclude(type__is_epic=True)
                .select_related("project", "workspace", "state", "estimate_point")
                .distinct()
                .order_by("workspace__slug", "project__identifier", "sequence_id")
            )
            items, planned, done, unestimated = [], 0.0, 0.0, 0
            hidden = {"count": 0, "points": 0.0}
            for issue in issues:
                points = _points(issue)
                is_done = issue.state.group in ("completed", "cancelled") if issue.state_id else False
                if points is None:
                    unestimated += 1
                else:
                    planned += points
                    if is_done:
                        done += points
                if not _can_view(issue, viewer, access):
                    hidden["count"] += 1
                    hidden["points"] += points or 0.0
                    continue
                items.append(
                    {
                        "id": str(issue.id),
                        "name": issue.name,
                        "workspace_slug": issue.workspace.slug,
                        "workspace_name": issue.workspace.name,
                        "project_id": str(issue.project_id),
                        "project_identifier": issue.project.identifier,
                        "project_name": issue.project.name,
                        "sequence_id": issue.sequence_id,
                        "state_name": issue.state.name if issue.state_id else None,
                        "state_group": issue.state.group if issue.state_id else None,
                        "points": points,
                    }
                )
            year, week, _ = monday.isocalendar()
            sprints.append(
                {
                    "label": f"Sprint {year}-W{week:02d}",
                    "start_date": str(monday),
                    "end_date": str(monday + dt.timedelta(days=6)),
                    "is_current": offset == 0,
                    "planned_points": planned,
                    "done_points": done,
                    "unestimated": unestimated,
                    "hidden": hidden,
                    "items": items,
                }
            )
        return Response(
            {
                "capacity": SPRINT_CAPACITY,
                "user": {"id": str(target.id), "display_name": target.display_name, "is_me": target.id == viewer.id},
                "sprints": sprints,
            },
            status=status.HTTP_200_OK,
        )


class SprintCapacityPeopleEndpoint(BaseAPIView):
    """People whose My sprint the requesting user may open: everyone sharing a workspace with them."""

    def get(self, request):
        viewer_ws = WorkspaceMember.objects.filter(member=request.user, is_active=True).values_list(
            "workspace_id", flat=True
        )
        people = (
            User.objects.filter(
                member_workspace__workspace_id__in=viewer_ws,
                member_workspace__is_active=True,
                is_active=True,
                is_bot=False,
            )
            .distinct()
            .order_by("display_name")
        )
        return Response(
            [
                {"id": str(u.id), "display_name": u.display_name, "first_name": u.first_name, "last_name": u.last_name,
                 "avatar_url": u.avatar_url, "is_me": u.id == request.user.id}
                for u in people
            ],
            status=status.HTTP_200_OK,
        )
