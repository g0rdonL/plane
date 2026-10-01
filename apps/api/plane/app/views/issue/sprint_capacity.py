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
from plane.db.models import Cycle, Issue, ProjectMember

# Aight fork: sprints are weekly, Monday 00:00 to Sunday 23:59 Hong Kong time, and each IC plans
# 8 points per sprint across every workspace and project (Plane User Convention).
SPRINT_TZ = zoneinfo.ZoneInfo("Asia/Hong_Kong")
SPRINT_CAPACITY = 8


def _points(issue):
    try:
        return float(issue.estimate_point.value) if issue.estimate_point_id else None
    except (TypeError, ValueError):
        return None


class SprintCapacityEndpoint(BaseAPIView):
    """The requesting user's stories in this week's and next week's sprints, across all workspaces."""

    def get(self, request):
        today = timezone.now().astimezone(SPRINT_TZ).date()
        this_monday = today - dt.timedelta(days=today.weekday())
        project_ids = ProjectMember.objects.filter(
            member=request.user, is_active=True, project__archived_at__isnull=True
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
                    issue_assignee__assignee=request.user,
                    issue_assignee__deleted_at__isnull=True,
                )
                .exclude(type__is_epic=True)
                .select_related("project", "workspace", "state", "estimate_point")
                .distinct()
                .order_by("workspace__slug", "project__identifier", "sequence_id")
            )
            items, planned, done, unestimated = [], 0.0, 0.0, 0
            for issue in issues:
                points = _points(issue)
                is_done = issue.state.group in ("completed", "cancelled") if issue.state_id else False
                if points is None:
                    unestimated += 1
                else:
                    planned += points
                    if is_done:
                        done += points
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
                    "items": items,
                }
            )
        return Response({"capacity": SPRINT_CAPACITY, "sprints": sprints}, status=status.HTTP_200_OK)
