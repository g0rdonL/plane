# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Aight fork: per-person monthly task numbers for the Performance Evaluation policy (§2, §3).
#
# - A story is planned in month M if it was ever in a sprint whose midpoint falls in M
#   (Bangkok time). Weekly Mon-Sun sprints therefore belong to the month of their Thursday.
#   Sprint history comes from cycle activities plus current/removed cycle rows, because
#   moving a story between sprints rewrites its cycle row in place.
# - Cancelled stories count nowhere. Epics and drafts are ignored.
# - A Done story is completed in the first planned month on/after the month it was done,
#   so a story done early (before its sprint's month) still counts for that sprint's month.
# - Deadline = due date if set, else the end of the last sprint the story was in.
# - Carry-overs = planned in M, not completed in M, labelled carry-over. Stories that were
#   moved to a later month's sprint without the label are reported as unlabelled moves.
# - People are the stories' current assignees; bots are skipped.
import datetime as dt
from dataclasses import dataclass, field

from django.db.models import Q

from plane.db.models import Cycle, CycleIssue, Issue, IssueActivity, IssueAssignee, IssueLabel, Project
from plane.utils.sprint import SPRINT_TZ

CARRY_OVER = "carry-over"


def month_bounds(year, month):
    start = dt.datetime(year, month, 1, tzinfo=SPRINT_TZ)
    end = dt.datetime(year + month // 12, month % 12 + 1, 1, tzinfo=SPRINT_TZ)
    return start, end


def month_of(when):
    local = when.astimezone(SPRINT_TZ)
    return (local.year, local.month)


def sprint_month(start_date, end_date):
    return month_of(start_date + (end_date - start_date) / 2)


@dataclass
class Story:
    id: str
    key: str
    name: str
    state: str
    group: str
    completed_at: dt.datetime = None
    target_date: dt.date = None
    carry_over: bool = False
    sprints: list = field(default_factory=list)  # [(month, cycle name, end_date)], sorted by end
    assignees: list = field(default_factory=list)

    @property
    def planned_months(self):
        return sorted({m for m, _, _ in self.sprints})

    @property
    def completed_month(self):
        if self.group != "completed" or self.completed_at is None:
            return None
        done = month_of(self.completed_at)
        return next((m for m in self.planned_months if m >= done), None)

    @property
    def deadline(self):
        if self.target_date:
            return self.target_date, "due date"
        return self.sprints[-1][2].astimezone(SPRINT_TZ).date(), "sprint end"

    @property
    def on_time(self):
        return self.completed_at is not None and self.completed_at.astimezone(SPRINT_TZ).date() <= self.deadline[0]


def load_stories(workspace_slug=None):
    """Sprint stories (not cancelled, not epics) with their sprint history, labels and assignees."""
    issues = Issue.objects.filter(is_draft=False, project__deleted_at__isnull=True).exclude(type__is_epic=True)
    if workspace_slug:
        issues = issues.filter(workspace__slug=workspace_slug)
    rows = issues.exclude(state__group="cancelled").values(
        "id", "name", "sequence_id", "project__identifier", "state__name", "state__group", "completed_at", "target_date"
    )
    stories = {
        r["id"]: Story(
            id=str(r["id"]),
            key=f"{r['project__identifier']}-{r['sequence_id']}",
            name=r["name"],
            state=r["state__name"] or "",
            group=r["state__group"] or "",
            completed_at=r["completed_at"],
            target_date=r["target_date"],
        )
        for r in rows
    }
    ids = list(stories)

    cycle_ids = {}
    for issue_id, cycle_id in CycleIssue.all_objects.filter(issue_id__in=ids).values_list("issue_id", "cycle_id"):
        cycle_ids.setdefault(issue_id, set()).add(cycle_id)
    activities = IssueActivity.objects.filter(issue_id__in=ids, field="cycles").values_list(
        "issue_id", "old_identifier", "new_identifier"
    )
    for issue_id, old, new in activities:
        cycle_ids.setdefault(issue_id, set()).update(c for c in (old, new) if c)

    all_cycle_ids = set().union(*cycle_ids.values()) if cycle_ids else set()
    cycles = {
        c["id"]: c
        for c in Cycle.objects.filter(pk__in=all_cycle_ids, start_date__isnull=False, end_date__isnull=False).values(
            "id", "name", "start_date", "end_date"
        )
    }
    for issue_id, story in stories.items():
        sprints = [cycles[c] for c in cycle_ids.get(issue_id, ()) if c in cycles]
        story.sprints = sorted(
            ((sprint_month(c["start_date"], c["end_date"]), c["name"], c["end_date"]) for c in sprints),
            key=lambda s: s[2],
        )

    carried = IssueLabel.objects.filter(
        issue_id__in=ids, label__name__iexact=CARRY_OVER, label__deleted_at__isnull=True
    )
    for issue_id in carried.values_list("issue_id", flat=True):
        stories[issue_id].carry_over = True

    assignees = IssueAssignee.objects.filter(issue_id__in=ids, assignee__is_bot=False).values_list(
        "issue_id", "assignee__email", "assignee__first_name", "assignee__last_name", "assignee__display_name"
    )
    for issue_id, email, first, last, display in assignees:
        stories[issue_id].assignees.append((email, f"{first or ''} {last or ''}".strip() or display or email))

    return [s for s in stories.values() if s.sprints]


def story_row(story, month):
    completed = story.completed_month == month
    later = any(m > month for m in story.planned_months)
    deadline, source = story.deadline
    return {
        "key": story.key,
        "title": story.name,
        "state": story.state,
        "sprints": " ".join(name for _, name, _ in story.sprints),
        "completed": completed,
        "deadline": deadline.isoformat(),
        "deadline_source": source,
        "deadline_met": completed and story.on_time,
        "carry_over": not completed and story.carry_over,
        "unlabelled_move": not completed and not story.carry_over and later,
    }


def rate(part, whole):
    return f"{part / whole:.0%}" if whole else ""


def monthly_summary(year, month, workspace_slug=None):
    """(people, details): one summary row per person and one detail row per (person, story)."""
    target = (year, month)
    people, details = {}, []
    for story in load_stories(workspace_slug):
        if target not in story.planned_months:
            continue
        row = story_row(story, target)
        for email, name in story.assignees:
            person = people.setdefault(
                email,
                {
                    "email": email,
                    "name": name,
                    "planned": 0,
                    "completed": 0,
                    "deadlines_met": 0,
                    "carry_overs": 0,
                    "unlabelled_moves": 0,
                },
            )
            person["planned"] += 1
            person["completed"] += row["completed"]
            person["deadlines_met"] += row["deadline_met"]
            person["carry_overs"] += row["carry_over"]
            person["unlabelled_moves"] += row["unlabelled_move"]
            details.append({"month": f"{year}-{month:02d}", "email": email, "name": name, **row})

    summary = []
    for person in sorted(people.values(), key=lambda p: p["name"].lower()):
        summary.append(
            {
                "month": f"{year}-{month:02d}",
                "email": person["email"],
                "name": person["name"],
                "planned": person["planned"],
                "completed": person["completed"],
                "completion_rate": rate(person["completed"], person["planned"]),
                "deadlines_met": person["deadlines_met"],
                "on_time_rate": rate(person["deadlines_met"], person["completed"]),
                "carry_overs": person["carry_overs"],
                "unlabelled_moves": person["unlabelled_moves"],
            }
        )
    details.sort(key=lambda d: (d["name"].lower(), d["key"]))
    return summary, details


def projects_missing_carry_over(workspace_slug=None):
    projects = Project.objects.filter(archived_at__isnull=True)
    if workspace_slug:
        projects = projects.filter(workspace__slug=workspace_slug)
    has_label = Q(project_label__name__iexact=CARRY_OVER, project_label__deleted_at__isnull=True)
    with_label = projects.filter(has_label).values_list("id", flat=True)
    return projects.exclude(id__in=with_label).select_related("workspace").order_by("identifier")
