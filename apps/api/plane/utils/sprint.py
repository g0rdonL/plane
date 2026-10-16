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
# and moving one back to Backlog is rejected until it leaves the sprint. Adding a story
# with no priority also defaults it to Medium (a default only: clearing it later is allowed).
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


SPRINT_DEFAULT_PRIORITY = "medium"


def sprint_defaults_q():
    """Q selecting issues that adding to a sprint would change (Backlog state or no priority)."""
    return Q(state__group="backlog") | Q(priority="none")


def apply_sprint_defaults(issue_ids, project_id, actor_id, origin=None):
    """Move Backlog issues among issue_ids to Todo and set empty priority to Medium.

    Returns {issue_id: {field: new_value}} for the issues that changed.
    """
    import json

    from plane.bgtasks.issue_activities_task import issue_activity
    from plane.db.models import Issue

    rows = list(
        Issue.issue_objects.filter(sprint_defaults_q(), project_id=project_id, pk__in=issue_ids).values_list(
            "id", "state_id", "state__group", "priority"
        )
    )
    todo = sprint_todo_state(project_id) if any(group == "backlog" for _, _, group, _ in rows) else None

    changes = {}
    for issue_id, state_id, group, priority in rows:
        requested, current = {}, {}
        if group == "backlog" and todo is not None:
            requested["state_id"], current["state_id"] = str(todo.id), str(state_id)
        if priority == "none":
            requested["priority"], current["priority"] = SPRINT_DEFAULT_PRIORITY, priority
        if requested:
            changes[issue_id] = (requested, current)
    if not changes:
        return {}

    now = timezone.now()
    promote_ids = [issue_id for issue_id, (requested, _) in changes.items() if "state_id" in requested]
    priority_ids = [issue_id for issue_id, (requested, _) in changes.items() if "priority" in requested]
    if promote_ids:
        Issue.objects.filter(pk__in=promote_ids).update(state=todo, updated_by_id=actor_id, updated_at=now)
    if priority_ids:
        Issue.objects.filter(pk__in=priority_ids).update(
            priority=SPRINT_DEFAULT_PRIORITY, updated_by_id=actor_id, updated_at=now
        )

    epoch = int(now.timestamp())
    for issue_id, (requested, current) in changes.items():
        issue_activity.delay(
            type="issue.activity.updated",
            requested_data=json.dumps(requested),
            actor_id=str(actor_id),
            issue_id=str(issue_id),
            project_id=str(project_id),
            current_instance=json.dumps(current),
            epoch=epoch,
            notification=False,
            origin=origin,
        )
    return {str(issue_id): requested for issue_id, (requested, _) in changes.items()}


# Aight fork: a story moved to Done joins the current sprint. Work picked up outside a sprint
# (Paseo workspaces) or from an older or later sprint then counts in the week it was finished.
def current_sprint_cycle(project_id):
    """The project's cycle running right now, latest start first; None if there isn't one."""
    from plane.db.models import Cycle

    now = timezone.now()
    return (
        Cycle.objects.filter(project_id=project_id, start_date__lte=now, end_date__gte=now, archived_at__isnull=True)
        .order_by("-start_date")
        .first()
    )


def completed_state_change(requested_data, current_instance, project_id):
    """True if an issue update moved the issue from a non-completed state into a completed one."""
    import json

    from plane.db.models import State

    requested = json.loads(requested_data) if isinstance(requested_data, str) else requested_data or {}
    current = json.loads(current_instance) if isinstance(current_instance, str) else current_instance or {}
    new_id = requested.get("state_id") or requested.get("state")
    old_id = current.get("state_id") or current.get("state")
    if not new_id or str(new_id) == str(old_id):
        return False
    groups = dict(
        State.objects.filter(project_id=project_id, pk__in=[i for i in (new_id, old_id) if i]).values_list(
            "id", "group"
        )
    )
    groups = {str(k): v for k, v in groups.items()}
    return groups.get(str(new_id)) == "completed" and groups.get(str(old_id)) != "completed"


def join_current_sprint(issue_id, project_id, actor_id):
    """Move a completed story into the project's current sprint unless it's already in this week's.

    Returns the cycle activity payload ({"updated_cycle_issues", "created_cycle_issues"}) or None.
    """
    from django.core import serializers

    from plane.db.models import CycleIssue, Issue

    issue = (
        Issue.issue_objects.filter(pk=issue_id, project_id=project_id, state__group="completed")
        .exclude(type__is_epic=True)
        .first()
    )
    if issue is None or Issue.objects.filter(sprint_issue_q(["current"]), pk=issue_id).exists():
        return None
    cycle = current_sprint_cycle(project_id)
    if cycle is None:
        return None

    cycle_issue = CycleIssue.objects.filter(issue_id=issue_id, project_id=project_id).first()
    if cycle_issue is not None:
        old_cycle_id = cycle_issue.cycle_id
        cycle_issue.cycle_id = cycle.id
        cycle_issue.updated_by_id = actor_id
        cycle_issue.save(update_fields=["cycle_id", "updated_by_id", "updated_at"])
        return {
            "updated_cycle_issues": [
                {"old_cycle_id": str(old_cycle_id), "new_cycle_id": str(cycle.id), "issue_id": str(issue_id)}
            ],
            "created_cycle_issues": "[]",
        }
    cycle_issue = CycleIssue.objects.create(
        cycle=cycle,
        issue_id=issue_id,
        project_id=project_id,
        workspace_id=cycle.workspace_id,
        created_by_id=actor_id,
        updated_by_id=actor_id,
    )
    return {"updated_cycle_issues": [], "created_cycle_issues": serializers.serialize("json", [cycle_issue])}
