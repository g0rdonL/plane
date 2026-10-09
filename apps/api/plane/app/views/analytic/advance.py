# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import datetime as dt
import statistics
from rest_framework.response import Response
from rest_framework import status
from typing import Dict, List, Any, Optional, Tuple
from django.db.models import QuerySet, Q, Count, Min, OuterRef, Subquery
from django.http import HttpRequest
from django.db.models.functions import TruncMonth
from django.utils import timezone
from plane.app.views.base import BaseAPIView
from plane.app.permissions import ROLE, allow_permission
from plane.db.models import (
    WorkspaceMember,
    Project,
    Issue,
    Cycle,
    CycleIssue,
    IssueActivity,
    State,
    Module,
    IssueView,
    ProjectPage,
    Workspace,
    ProjectMember,
)
from plane.utils.build_chart import build_analytics_chart
from plane.utils.date_utils import (
    get_analytics_filters,
)
from plane.utils.sprint import SPRINT_TZ

# Aight fork: momentum reporting is read-only over weekly (Bangkok) sprints. A story is a
# non-epic issue_objects row; epics are never counted.
NON_EPIC_Q = Q(type__is_epic=False) | Q(type__isnull=True)
CUMULATIVE_FLOW_GROUPS = ("backlog", "unstarted", "started", "completed")
CYCLE_TIME_BUCKETS = (
    ("le_1d", "≤1d", lambda days: days <= 1),
    ("d2_3", "2–3d", lambda days: 1 < days <= 3),
    ("d4_7", "4–7d", lambda days: 3 < days <= 7),
    ("d8_14", "8–14d", lambda days: 7 < days <= 14),
    ("gt_14", ">14d", lambda days: 14 < days),
)
MONTH_ABBREVIATIONS = (
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
)


def _to_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _week_windows(weeks: int) -> List[Tuple[dt.datetime, dt.datetime]]:
    """The last `weeks` Monday-Sunday sprint weeks in Bangkok, oldest first (current week last)."""
    today = timezone.now().astimezone(SPRINT_TZ).date()
    current_monday = today - dt.timedelta(days=today.weekday())
    windows = []
    for offset in range(weeks - 1, -1, -1):
        start = dt.datetime.combine(current_monday - dt.timedelta(weeks=offset), dt.time.min, tzinfo=SPRINT_TZ)
        windows.append((start, start + dt.timedelta(days=7)))
    return windows


def _week_meta(start: dt.datetime) -> Tuple[str, str]:
    iso = start.date().isocalendar()
    return f"{iso.year}-W{iso.week:02d}", f"W{iso.week:02d}"


def _week_index(value: dt.datetime, windows: List[Tuple[dt.datetime, dt.datetime]]) -> Optional[int]:
    for index, (start, end) in enumerate(windows):
        if start <= value < end:
            return index
    return None


def _parse_range(raw: Optional[str], default: int, maximum: int) -> Optional[int]:
    if raw in (None, ""):
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    if value < 1 or value > maximum:
        return None
    return value


def _percentile_85(values: List[float]) -> Optional[float]:
    if not values:
        return None
    if len(values) == 1:
        return values[0]
    return statistics.quantiles(values, n=20)[16]


class AdvanceAnalyticsBaseView(BaseAPIView):
    def initialize_workspace(self, slug: str, type: str) -> None:
        self._workspace_slug = slug
        self.filters = get_analytics_filters(
            slug=slug,
            type=type,
            user=self.request.user,
            date_filter=self.request.GET.get("date_filter", None),
            project_ids=self.request.GET.get("project_ids", None),
        )

    def _velocity_series(self, weeks: int) -> Tuple[List[Any], List[float], List[float], List[int]]:
        """Committed/completed points and completed story counts per sprint week (oldest first)."""
        windows = _week_windows(weeks)
        window_start, window_end = windows[0][0], windows[-1][1]
        base = Issue.issue_objects.filter(**self.filters["base_filters"]).filter(NON_EPIC_Q)

        committed_points = [0.0] * weeks
        seen_committed = [set() for _ in range(weeks)]
        committed_rows = (
            CycleIssue.objects.filter(
                deleted_at__isnull=True,
                cycle__deleted_at__isnull=True,
                cycle__end_date__gte=window_start,
                cycle__end_date__lt=window_end,
                issue__deleted_at__isnull=True,
                issue__archived_at__isnull=True,
                issue__is_draft=False,
            )
            .filter(Q(issue__type__is_epic=False) | Q(issue__type__isnull=True))
            .exclude(issue__state__group="cancelled")
            .exclude(issue__state__group="triage")
        )
        for key, value in self.filters["base_filters"].items():
            committed_rows = committed_rows.filter(**{f"issue__{key}": value})
        for issue_id, end_date, value in committed_rows.values_list(
            "issue_id", "cycle__end_date", "issue__estimate_point__value"
        ):
            index = _week_index(end_date, windows)
            if index is None or issue_id in seen_committed[index]:
                continue
            seen_committed[index].add(issue_id)
            committed_points[index] += _to_float(value)

        completed_points = [0.0] * weeks
        completed_counts = [0] * weeks
        completed_rows = base.filter(
            state__group="completed",
            completed_at__gte=window_start,
            completed_at__lt=window_end,
        ).values_list("completed_at", "estimate_point__value")
        for completed_at, value in completed_rows:
            index = _week_index(completed_at, windows)
            if index is None:
                continue
            completed_points[index] += _to_float(value)
            completed_counts[index] += 1

        return windows, committed_points, completed_points, completed_counts

    def _completed_cycle_lead_times(
        self, window_start: dt.datetime, window_end: dt.datetime
    ) -> Tuple[List[float], List[float]]:
        """Cycle and lead times (in days) for stories completed inside the window."""
        base = Issue.issue_objects.filter(**self.filters["base_filters"]).filter(NON_EPIC_Q)
        completed = list(
            base.filter(
                state__group="completed",
                completed_at__gte=window_start,
                completed_at__lt=window_end,
            ).values_list("id", "created_at", "completed_at")
        )
        if not completed:
            return [], []

        new_group = State.objects.filter(id=OuterRef("new_identifier")).values("group")[:1]
        started_rows = (
            IssueActivity.objects.filter(field="state", issue_id__in=[row[0] for row in completed])
            .annotate(new_group=Subquery(new_group))
            .filter(new_group="started")
            .values("issue_id")
            .annotate(started_at=Min("created_at"))
        )
        started_map = {row["issue_id"]: row["started_at"] for row in started_rows}

        cycle_times = []
        lead_times = []
        for issue_id, created_at, completed_at in completed:
            started_at = started_map.get(issue_id) or created_at
            cycle_times.append((completed_at - started_at).total_seconds() / 86400)
            lead_times.append((completed_at - created_at).total_seconds() / 86400)
        return cycle_times, lead_times


class AdvanceAnalyticsEndpoint(AdvanceAnalyticsBaseView):
    def get_filtered_counts(self, queryset: QuerySet) -> Dict[str, int]:
        def get_filtered_count() -> int:
            if self.filters["analytics_date_range"]:
                return queryset.filter(
                    created_at__gte=self.filters["analytics_date_range"]["current"]["gte"],
                    created_at__lte=self.filters["analytics_date_range"]["current"]["lte"],
                ).count()
            return queryset.count()

        def get_previous_count() -> int:
            if self.filters["analytics_date_range"] and self.filters["analytics_date_range"].get("previous"):
                return queryset.filter(
                    created_at__gte=self.filters["analytics_date_range"]["previous"]["gte"],
                    created_at__lte=self.filters["analytics_date_range"]["previous"]["lte"],
                ).count()
            return 0

        return {
            "count": get_filtered_count(),
            # "filter_count": get_previous_count(),
        }

    def get_overview_data(self) -> Dict[str, Dict[str, int]]:
        members_query = WorkspaceMember.objects.filter(
            workspace__slug=self._workspace_slug, is_active=True, member__is_bot=False
        )

        if self.request.GET.get("project_ids", None):
            project_ids = self.request.GET.get("project_ids", None)
            project_ids = [str(project_id) for project_id in project_ids.split(",")]
            members_query = ProjectMember.objects.filter(
                project_id__in=project_ids, is_active=True, member__is_bot=False
            )

        return {
            "total_users": self.get_filtered_counts(members_query),
            "total_admins": self.get_filtered_counts(members_query.filter(role=ROLE.ADMIN.value)),
            "total_members": self.get_filtered_counts(members_query.filter(role=ROLE.MEMBER.value)),
            "total_guests": self.get_filtered_counts(members_query.filter(role=ROLE.GUEST.value)),
            "total_projects": self.get_filtered_counts(Project.objects.filter(**self.filters["project_filters"])),
            "total_work_items": self.get_filtered_counts(Issue.issue_objects.filter(**self.filters["base_filters"])),
            "total_cycles": self.get_filtered_counts(Cycle.objects.filter(**self.filters["base_filters"])),
            "total_intake": self.get_filtered_counts(
                Issue.objects.filter(**self.filters["base_filters"]).filter(
                    issue_intake__status__in=["-2", "-1", "0", "1", "2"]  # TODO: Add description for reference.
                )
            ),
        }

    def get_work_items_stats(self) -> Dict[str, Dict[str, int]]:
        base_queryset = Issue.issue_objects.filter(**self.filters["base_filters"])

        return {
            "total_work_items": self.get_filtered_counts(base_queryset),
            "started_work_items": self.get_filtered_counts(base_queryset.filter(state__group="started")),
            "backlog_work_items": self.get_filtered_counts(base_queryset.filter(state__group="backlog")),
            "un_started_work_items": self.get_filtered_counts(base_queryset.filter(state__group="unstarted")),
            "completed_work_items": self.get_filtered_counts(base_queryset.filter(state__group="completed")),
        }

    def get_momentum_data(self, weeks: int) -> Dict[str, Dict[str, Any]]:
        windows, committed_points, completed_points, completed_counts = self._velocity_series(weeks)
        elapsed_index = weeks - 2 if weeks >= 2 else weeks - 1
        last_three_points = completed_points[-3:]
        last_three_counts = completed_counts[-3:]

        cycle_times, lead_times = self._completed_cycle_lead_times(windows[0][0], windows[-1][1])
        committed_last = committed_points[elapsed_index]

        def tile(value: Optional[float]) -> Dict[str, Any]:
            return {"count": None if value is None else round(value, 1)}

        return {
            "avg_velocity": tile(sum(last_three_points) / len(last_three_points)),
            "last_sprint_velocity": tile(completed_points[elapsed_index]),
            "commitment_reliability": {
                "count": round(completed_points[elapsed_index] / committed_last * 100) if committed_last > 0 else None
            },
            "avg_throughput": tile(sum(last_three_counts) / len(last_three_counts)),
            "median_cycle_time": tile(statistics.median(cycle_times) if cycle_times else None),
            "p85_cycle_time": tile(_percentile_85(cycle_times)),
            "median_lead_time": tile(statistics.median(lead_times) if lead_times else None),
            "p85_lead_time": tile(_percentile_85(lead_times)),
        }

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER], level="WORKSPACE")
    def get(self, request: HttpRequest, slug: str) -> Response:
        self.initialize_workspace(slug, type="analytics")
        tab = request.GET.get("tab", "overview")

        if tab == "overview":
            return Response(
                self.get_overview_data(),
                status=status.HTTP_200_OK,
            )
        elif tab == "work-items":
            return Response(
                self.get_work_items_stats(),
                status=status.HTTP_200_OK,
            )
        elif tab == "momentum":
            weeks = _parse_range(request.GET.get("weeks"), 8, 26)
            if weeks is None:
                return Response({"message": "Invalid weeks"}, status=status.HTTP_400_BAD_REQUEST)
            return Response(
                self.get_momentum_data(weeks),
                status=status.HTTP_200_OK,
            )
        return Response({"message": "Invalid tab"}, status=status.HTTP_400_BAD_REQUEST)


class AdvanceAnalyticsStatsEndpoint(AdvanceAnalyticsBaseView):
    def get_project_issues_stats(self) -> QuerySet:
        # Get the base queryset with workspace and project filters
        base_queryset = Issue.issue_objects.filter(**self.filters["base_filters"])

        # Apply date range filter if available
        if self.filters["chart_period_range"]:
            start_date, end_date = self.filters["chart_period_range"]
            base_queryset = base_queryset.filter(created_at__date__gte=start_date, created_at__date__lte=end_date)

        return (
            base_queryset.values("project_id", "project__name")
            .annotate(
                cancelled_work_items=Count("id", filter=Q(state__group="cancelled")),
                completed_work_items=Count("id", filter=Q(state__group="completed")),
                backlog_work_items=Count("id", filter=Q(state__group="backlog")),
                un_started_work_items=Count("id", filter=Q(state__group="unstarted")),
                started_work_items=Count("id", filter=Q(state__group="started")),
            )
            .order_by("project_id")
        )

    def get_work_items_stats(self) -> Dict[str, Dict[str, int]]:
        base_queryset = Issue.issue_objects.filter(**self.filters["base_filters"])
        return (
            base_queryset.values("project_id", "project__name")
            .annotate(
                cancelled_work_items=Count("id", filter=Q(state__group="cancelled")),
                completed_work_items=Count("id", filter=Q(state__group="completed")),
                backlog_work_items=Count("id", filter=Q(state__group="backlog")),
                un_started_work_items=Count("id", filter=Q(state__group="unstarted")),
                started_work_items=Count("id", filter=Q(state__group="started")),
            )
            .order_by("project_id")
        )

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER], level="WORKSPACE")
    def get(self, request: HttpRequest, slug: str) -> Response:
        self.initialize_workspace(slug, type="chart")
        type = request.GET.get("type", "work-items")

        if type == "work-items":
            return Response(
                self.get_work_items_stats(),
                status=status.HTTP_200_OK,
            )

        return Response({"message": "Invalid type"}, status=status.HTTP_400_BAD_REQUEST)


class AdvanceAnalyticsChartEndpoint(AdvanceAnalyticsBaseView):
    def project_chart(self) -> List[Dict[str, Any]]:
        # Get the base queryset with workspace and project filters
        base_queryset = Issue.issue_objects.filter(**self.filters["base_filters"])
        date_filter = {}

        # Apply date range filter if available
        if self.filters["chart_period_range"]:
            start_date, end_date = self.filters["chart_period_range"]
            date_filter = {
                "created_at__date__gte": start_date,
                "created_at__date__lte": end_date,
            }

        total_work_items = base_queryset.filter(**date_filter).count()
        total_cycles = Cycle.objects.filter(**self.filters["base_filters"], **date_filter).count()
        total_modules = Module.objects.filter(**self.filters["base_filters"], **date_filter).count()
        total_intake = Issue.objects.filter(
            issue_intake__isnull=False, **self.filters["base_filters"], **date_filter
        ).count()
        total_members = WorkspaceMember.objects.filter(
            workspace__slug=self._workspace_slug, is_active=True, **date_filter
        ).count()
        total_pages = ProjectPage.objects.filter(**self.filters["base_filters"], **date_filter).count()
        total_views = IssueView.objects.filter(**self.filters["base_filters"], **date_filter).count()

        data = {
            "work_items": total_work_items,
            "cycles": total_cycles,
            "modules": total_modules,
            "intake": total_intake,
            "members": total_members,
            "pages": total_pages,
            "views": total_views,
        }

        return [
            {
                "key": key,
                "name": key.replace("_", " ").title(),
                "count": value or 0,
            }
            for key, value in data.items()
        ]

    def work_item_completion_chart(self) -> Dict[str, Any]:
        # Get the base queryset
        queryset = (
            Issue.issue_objects.filter(**self.filters["base_filters"])
            .select_related("workspace", "state", "parent")
            .prefetch_related("assignees", "labels", "issue_module__module", "issue_cycle__cycle")
        )

        workspace = Workspace.objects.get(slug=self._workspace_slug)
        start_date = workspace.created_at.date().replace(day=1)

        # Apply date range filter if available
        if self.filters["chart_period_range"]:
            start_date, end_date = self.filters["chart_period_range"]
            queryset = queryset.filter(created_at__date__gte=start_date, created_at__date__lte=end_date)

        # Annotate by month and count
        monthly_stats = (
            queryset.annotate(month=TruncMonth("created_at"))
            .values("month")
            .annotate(
                created_count=Count("id"),
                completed_count=Count("id", filter=Q(state__group="completed")),
            )
            .order_by("month")
        )

        # Create dictionary of month -> counts
        stats_dict = {
            stat["month"].strftime("%Y-%m-%d"): {
                "created_count": stat["created_count"],
                "completed_count": stat["completed_count"],
            }
            for stat in monthly_stats
        }

        # Generate monthly data (ensure months with 0 count are included)
        data = []
        # include the current date at the end
        end_date = timezone.now().date()
        last_month = end_date.replace(day=1)
        current_month = start_date

        while current_month <= last_month:
            date_str = current_month.strftime("%Y-%m-%d")
            stats = stats_dict.get(date_str, {"created_count": 0, "completed_count": 0})
            data.append(
                {
                    "key": date_str,
                    "name": date_str,
                    "count": stats["created_count"],
                    "completed_issues": stats["completed_count"],
                    "created_issues": stats["created_count"],
                }
            )
            # Move to next month
            if current_month.month == 12:
                current_month = current_month.replace(year=current_month.year + 1, month=1)
            else:
                current_month = current_month.replace(month=current_month.month + 1)

        schema = {
            "completed_issues": "completed_issues",
            "created_issues": "created_issues",
        }

        return {"data": data, "schema": schema}

    def velocity_chart(self, weeks: int) -> Dict[str, Any]:
        windows, committed_points, completed_points, _counts = self._velocity_series(weeks)
        data = []
        for index, (start, _end) in enumerate(windows):
            key, name = _week_meta(start)
            rolling_avg = None if index < 2 else round(sum(completed_points[index - 2 : index + 1]) / 3, 1)
            data.append(
                {
                    "key": key,
                    "name": name,
                    "committed_points": round(committed_points[index], 1),
                    "completed_points": round(completed_points[index], 1),
                    "rolling_avg": rolling_avg,
                }
            )
        schema = {
            "committed_points": "Committed points",
            "completed_points": "Completed points",
            "rolling_avg": "Rolling average",
        }
        return {"data": data, "schema": schema}

    def throughput_chart(self, weeks: int) -> Dict[str, Any]:
        windows, _committed, _points, completed_counts = self._velocity_series(weeks)
        data = []
        for index, (start, _end) in enumerate(windows):
            key, name = _week_meta(start)
            data.append({"key": key, "name": name, "completed_count": completed_counts[index]})
        return {"data": data, "schema": {"completed_count": "Completed stories"}}

    def cycle_time_chart(self, weeks: int) -> Dict[str, Any]:
        windows = _week_windows(weeks)
        cycle_times, _lead_times = self._completed_cycle_lead_times(windows[0][0], windows[-1][1])
        counts = [0] * len(CYCLE_TIME_BUCKETS)
        for days in cycle_times:
            for index, (_key, _name, in_bucket) in enumerate(CYCLE_TIME_BUCKETS):
                if in_bucket(days):
                    counts[index] += 1
                    break
        data = [
            {"key": key, "name": name, "count": counts[index]}
            for index, (key, name, _bucket) in enumerate(CYCLE_TIME_BUCKETS)
        ]
        return {"data": data, "schema": {}}

    def cumulative_flow_chart(self, days: int) -> Dict[str, Any]:
        today = timezone.now().astimezone(SPRINT_TZ).date()
        day_list = [today - dt.timedelta(days=days - 1 - offset) for offset in range(days)]
        window_end = dt.datetime.combine(today, dt.time.max, tzinfo=SPRINT_TZ)

        stories = list(
            Issue.issue_objects.filter(**self.filters["base_filters"])
            .filter(NON_EPIC_Q)
            .filter(created_at__lte=window_end)
            .select_related("state")
            .values_list("id", "created_at", "state__group")
        )
        issue_ids = [story[0] for story in stories]
        activity_map: Dict[Any, List[Any]] = {}
        if issue_ids:
            new_group = State.objects.filter(id=OuterRef("new_identifier")).values("group")[:1]
            old_group = State.objects.filter(id=OuterRef("old_identifier")).values("group")[:1]
            activities = (
                IssueActivity.objects.filter(field="state", issue_id__in=issue_ids)
                .annotate(new_group=Subquery(new_group), old_group=Subquery(old_group))
                .order_by("issue_id", "created_at")
                .values_list("issue_id", "created_at", "new_group", "old_group")
            )
            for issue_id, created_at, new_state_group, old_state_group in activities:
                activity_map.setdefault(issue_id, []).append((created_at, new_state_group, old_state_group))

        buckets = {day: {group: 0 for group in CUMULATIVE_FLOW_GROUPS} for day in day_list}
        for issue_id, created_at, current_group in stories:
            transitions = activity_map.get(issue_id, [])
            if transitions and transitions[0][2] in CUMULATIVE_FLOW_GROUPS:
                group = transitions[0][2]
            else:
                group = current_group
            transition_index = 0
            for day in day_list:
                day_end = dt.datetime.combine(day, dt.time.max, tzinfo=SPRINT_TZ)
                if created_at > day_end:
                    continue
                while transition_index < len(transitions) and transitions[transition_index][0] <= day_end:
                    group = transitions[transition_index][1]
                    transition_index += 1
                if group in CUMULATIVE_FLOW_GROUPS:
                    buckets[day][group] += 1
                elif group == "cancelled":
                    break

        data = []
        for day in day_list:
            data.append(
                {
                    "key": day.isoformat(),
                    "name": f"{MONTH_ABBREVIATIONS[day.month - 1]} {day.day:02d}",
                    **buckets[day],
                }
            )
        return {
            "data": data,
            "schema": {"backlog": "Backlog", "unstarted": "Unstarted", "started": "Started", "completed": "Completed"},
        }

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER], level="WORKSPACE")
    def get(self, request: HttpRequest, slug: str) -> Response:
        self.initialize_workspace(slug, type="chart")
        type = request.GET.get("type", "projects")
        group_by = request.GET.get("group_by", None)
        x_axis = request.GET.get("x_axis", "PRIORITY")

        if type == "projects":
            return Response(self.project_chart(), status=status.HTTP_200_OK)

        elif type == "custom-work-items":
            queryset = (
                Issue.issue_objects.filter(**self.filters["base_filters"])
                .select_related("workspace", "state", "parent")
                .prefetch_related("assignees", "labels", "issue_module__module", "issue_cycle__cycle")
            )

            # Apply date range filter if available
            if self.filters["chart_period_range"]:
                start_date, end_date = self.filters["chart_period_range"]
                queryset = queryset.filter(created_at__date__gte=start_date, created_at__date__lte=end_date)

            return Response(
                build_analytics_chart(queryset, x_axis, group_by),
                status=status.HTTP_200_OK,
            )

        elif type == "work-items":
            return Response(
                self.work_item_completion_chart(),
                status=status.HTTP_200_OK,
            )

        elif type == "velocity":
            weeks = _parse_range(request.GET.get("weeks"), 8, 26)
            if weeks is None:
                return Response({"message": "Invalid weeks"}, status=status.HTTP_400_BAD_REQUEST)
            return Response(self.velocity_chart(weeks), status=status.HTTP_200_OK)

        elif type == "throughput":
            weeks = _parse_range(request.GET.get("weeks"), 12, 26)
            if weeks is None:
                return Response({"message": "Invalid weeks"}, status=status.HTTP_400_BAD_REQUEST)
            return Response(self.throughput_chart(weeks), status=status.HTTP_200_OK)

        elif type == "cycle-time":
            weeks = _parse_range(request.GET.get("weeks"), 8, 26)
            if weeks is None:
                return Response({"message": "Invalid weeks"}, status=status.HTTP_400_BAD_REQUEST)
            return Response(self.cycle_time_chart(weeks), status=status.HTTP_200_OK)

        elif type == "cumulative-flow":
            days = _parse_range(request.GET.get("days"), 30, 90)
            if days is None:
                return Response({"message": "Invalid days"}, status=status.HTTP_400_BAD_REQUEST)
            return Response(self.cumulative_flow_chart(days), status=status.HTTP_200_OK)

        return Response({"message": "Invalid type"}, status=status.HTTP_400_BAD_REQUEST)
