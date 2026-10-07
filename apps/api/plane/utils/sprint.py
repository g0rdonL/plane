# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Aight fork: sprints are weekly, Monday 00:00 to Sunday 23:59 Bangkok time.
import datetime as dt
import zoneinfo

from django.db.models import Q
from django.utils import timezone

SPRINT_TZ = zoneinfo.ZoneInfo("Asia/Bangkok")
SPRINT_OFFSETS = {"current": 0, "next": 1}


def sprint_week(offset=0):
    """(start, end) datetimes of the Monday-Sunday sprint week, offset weeks from this one."""
    today = timezone.now().astimezone(SPRINT_TZ).date()
    monday = today - dt.timedelta(days=today.weekday()) + dt.timedelta(weeks=offset)
    start = dt.datetime.combine(monday, dt.time.min, tzinfo=SPRINT_TZ)
    return start, start + dt.timedelta(days=7)


def sprint_issue_q(values, prefix=""):
    """Q selecting issues in a cycle that overlaps any of the named sprint weeks ("current", "next")."""
    q = Q()
    for value in values:
        if value not in SPRINT_OFFSETS:
            continue
        start, end = sprint_week(SPRINT_OFFSETS[value])
        q |= Q(
            **{
                f"{prefix}issue_cycle__cycle__start_date__lt": end,
                f"{prefix}issue_cycle__cycle__end_date__gt": start,
                f"{prefix}issue_cycle__deleted_at__isnull": True,
                f"{prefix}issue_cycle__cycle__deleted_at__isnull": True,
            }
        )
    return q if q else Q(pk__in=[])


# Aight fork: a story in a sprint is never Backlog. Adding one promotes it to Todo,
# and moving one back to Backlog is rejected until it leaves the sprint.
SPRINT_BACKLOG_ERROR = "Stories in a sprint can't be in Backlog. Remove it from the sprint first."


def open_sprint_q(prefix=""):
    """Q selecting issues in a cycle that hasn't ended (draft cycles without dates count)."""
    return Q(
        **{
            f"{prefix}issue_cycle__cycle_id__isnull": False,
            f"{prefix}issue_cycle__deleted_at__isnull": True,
            f"{prefix}issue_cycle__cycle__deleted_at__isnull": True,
        }
    ) & (
        Q(**{f"{prefix}issue_cycle__cycle__end_date__isnull": True})
        | Q(**{f"{prefix}issue_cycle__cycle__end_date__gte": timezone.now()})
    )


def is_backlog_in_sprint(issue, state):
    """True if moving an existing issue to `state` would leave a sprint story in Backlog."""
    from plane.db.models import Issue

    if issue is None or issue.pk is None or state is None or state.group != "backlog":
        return False
    return Issue.objects.filter(open_sprint_q(), pk=issue.pk).exists()


def sprint_todo_state(project_id):
    """The project's Todo state: default unstarted state if any, else the first unstarted one."""
    from plane.db.models import State

    return State.objects.filter(project_id=project_id, group="unstarted").order_by("-default", "sequence").first()


def promote_sprint_backlog(issue_ids, project_id, actor_id, origin=None):
    """Move backlog-group issues among issue_ids to Todo. Returns {issue_id: new_state_id}."""
    import json

    from plane.bgtasks.issue_activities_task import issue_activity
    from plane.db.models import Issue

    backlog = list(
        Issue.issue_objects.filter(project_id=project_id, pk__in=issue_ids, state__group="backlog").values_list(
            "id", "state_id"
        )
    )
    todo = sprint_todo_state(project_id) if backlog else None
    if todo is None:
        return {}

    Issue.objects.filter(pk__in=[issue_id for issue_id, _ in backlog]).update(
        state=todo, updated_by_id=actor_id, updated_at=timezone.now()
    )
    epoch = int(timezone.now().timestamp())
    for issue_id, old_state_id in backlog:
        issue_activity.delay(
            type="issue.activity.updated",
            requested_data=json.dumps({"state_id": str(todo.id)}),
            actor_id=str(actor_id),
            issue_id=str(issue_id),
            project_id=str(project_id),
            current_instance=json.dumps({"state_id": str(old_state_id)}),
            epoch=epoch,
            notification=False,
            origin=origin,
        )
    return {str(issue_id): str(todo.id) for issue_id, _ in backlog}
