# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Python imports
import datetime as dt
import zoneinfo

# Django imports
from django.db.models import OuterRef, Subquery
from django.db.models.functions import Greatest
from django.utils import timezone

# Third Party imports
from rest_framework import status
from rest_framework.response import Response

# Module imports
from .. import BaseAPIView
from plane.db.models import Cycle, CycleIssue, Issue, IssueActivity, Profile, ProjectMember, User, WorkspaceMember

# Aight fork: sprints are weekly, Monday 00:00 to Sunday 23:59 Bangkok time. By default each IC plans
# 8 points per sprint across every workspace and project, plus a 2-point buffer for unplanned work
# (Plane User Convention). Part-timers set their own numbers, stored in Profile.goals["sprint_capacity"]
# (an unused CE field, so no migration). A story counts against the buffer when it entered the sprint
# on or after Tuesday 00:00 of that sprint week.
SPRINT_TZ = zoneinfo.ZoneInfo("Asia/Bangkok")
SPRINT_CAPACITY = 8
SPRINT_BUFFER = 2
BUFFER_CUTOFF = dt.timedelta(days=1)
MAX_POINTS = 40
GUEST = 5


MIN_OFFSET, MAX_OFFSET = -12, 4
DEFAULT_OFFSETS = (0, 1)


def _parse_offsets(raw):
    """Week offsets from ?offsets=-1,0,1; the default pair when absent, None when malformed."""
    if raw is None or raw == "":
        return DEFAULT_OFFSETS
    try:
        offsets = list(dict.fromkeys(int(part) for part in raw.split(",")))
    except ValueError:
        return None
    if any(not MIN_OFFSET <= offset <= MAX_OFFSET for offset in offsets):
        return None
    return tuple(offsets)


def get_capacity(user):
    goals = Profile.objects.filter(user=user).values_list("goals", flat=True).first() or {}
    saved = goals.get("sprint_capacity") if isinstance(goals, dict) else None
    saved = saved if isinstance(saved, dict) else {}
    return {
        "planned": saved.get("planned", SPRINT_CAPACITY),
        "buffer": saved.get("buffer", SPRINT_BUFFER),
    }


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
    """A user's stories in weekly sprints, across all workspaces: this week's and next week's by default.

    ?offsets=-2,-1,0,1 picks other weeks, as offsets from the current week (past weeks back to
    MIN_OFFSET, future weeks up to MAX_OFFSET), returned in the order requested.

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
        offsets = _parse_offsets(request.query_params.get("offsets"))
        if offsets is None:
            return Response({"error": "Invalid offsets"}, status=status.HTTP_400_BAD_REQUEST)
        access = _viewer_access(viewer)

        today = timezone.now().astimezone(SPRINT_TZ).date()
        this_monday = today - dt.timedelta(days=today.weekday())
        project_ids = ProjectMember.objects.filter(
            member=target, is_active=True, project__archived_at__isnull=True
        ).values_list("project_id", flat=True)

        sprints = []
        for offset in offsets:
            monday = this_monday + dt.timedelta(weeks=offset)
            week_start = dt.datetime.combine(monday, dt.time.min, tzinfo=SPRINT_TZ)
            week_end = week_start + dt.timedelta(days=7)
            cycles = Cycle.objects.filter(project_id__in=project_ids, start_date__lt=week_end, end_date__gt=week_start)
            # Moving a story between sprints rewrites CycleIssue.cycle_id in place, so its created_at is
            # not when it entered this sprint; the latest "cycles" activity is. Greatest() skips NULLs.
            moved_at = (
                IssueActivity.objects.filter(issue_id=OuterRef("pk"), field="cycles", new_identifier__in=cycles.values("id"))
                .order_by("-created_at")
                .values("created_at")[:1]
            )
            linked_at = (
                CycleIssue.objects.filter(issue_id=OuterRef("pk"), cycle__in=cycles)
                .order_by("-created_at")
                .values("created_at")[:1]
            )
            buffer_from = week_start + BUFFER_CUTOFF
            issues = (
                Issue.issue_objects.filter(
                    issue_cycle__cycle__in=cycles,
                    issue_cycle__deleted_at__isnull=True,
                    issue_assignee__assignee=target,
                    issue_assignee__deleted_at__isnull=True,
                )
                .exclude(type__is_epic=True)
                .annotate(added_at=Greatest(Subquery(moved_at), Subquery(linked_at)))
                .select_related("project", "workspace", "state", "estimate_point")
                .distinct()
                .order_by("workspace__slug", "project__identifier", "sequence_id")
            )
            items, planned, buffer, done, unestimated = [], 0.0, 0.0, 0.0, 0
            # Done (and cancelled) stories stay in planned/buffer so past weeks keep their totals. The
            # remaining_* sums, which the capacity badges and warnings compare, leave out stories finished
            # while planning was still open (before buffer_from), since that frees room to plan more.
            # Stories finished once the sprint is under way keep counting: the week was planned around them.
            # Cancelled stories have no timestamp and always leave.
            remaining, remaining_buffer = 0.0, 0.0
            hidden = {"count": 0, "points": 0.0}
            for issue in issues:
                points = _points(issue)
                is_done = issue.state.group in ("completed", "cancelled") if issue.state_id else False
                is_buffer = issue.added_at is not None and issue.added_at >= buffer_from
                finished_mid_sprint = (
                    is_done and issue.state.group == "completed" and (issue.completed_at or week_start) >= buffer_from
                )
                counts = not is_done or finished_mid_sprint
                if points is None:
                    unestimated += 1
                else:
                    if is_buffer:
                        buffer += points
                        remaining_buffer += points if counts else 0.0
                    else:
                        planned += points
                        remaining += points if counts else 0.0
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
                        "is_buffer": is_buffer,
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
                    "buffer_points": buffer,
                    "buffer_from": buffer_from.isoformat(),
                    "done_points": done,
                    "remaining_points": remaining,
                    "remaining_buffer_points": remaining_buffer,
                    "unestimated": unestimated,
                    "hidden": hidden,
                    "items": items,
                }
            )
        capacity = get_capacity(target)
        return Response(
            {
                "capacity": capacity["planned"],
                "buffer_capacity": capacity["buffer"],
                "user": {
                    "id": str(target.id),
                    "display_name": target.display_name,
                    "full_name": f"{target.first_name} {target.last_name}".strip() or target.display_name,
                    "is_me": target.id == viewer.id,
                },
                "sprints": sprints,
            },
            status=status.HTTP_200_OK,
        )


    def patch(self, request):
        """Set the requesting user's own planned and buffer points per sprint."""
        current = get_capacity(request.user)
        values = {}
        for key in ("planned", "buffer"):
            raw = request.data.get(key, current[key])
            if isinstance(raw, bool) or not isinstance(raw, (int, str)) or not str(raw).isdigit():
                return Response({"error": f"{key} must be a whole number"}, status=status.HTTP_400_BAD_REQUEST)
            value = int(raw)
            if value > MAX_POINTS:
                return Response({"error": f"{key} must be at most {MAX_POINTS}"}, status=status.HTTP_400_BAD_REQUEST)
            values[key] = value
        profile, _ = Profile.objects.get_or_create(user=request.user)
        goals = profile.goals if isinstance(profile.goals, dict) else {}
        goals["sprint_capacity"] = values
        profile.goals = goals
        profile.save(update_fields=["goals"])
        return Response({"capacity": values["planned"], "buffer_capacity": values["buffer"]}, status=status.HTTP_200_OK)


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
            .order_by("first_name", "last_name", "display_name")
        )
        return Response(
            [
                {"id": str(u.id), "display_name": u.display_name, "first_name": u.first_name, "last_name": u.last_name,
                 "avatar_url": u.avatar_url, "is_me": u.id == request.user.id}
                for u in people
            ],
            status=status.HTTP_200_OK,
        )
