# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Aight fork: create the copies of recurring stories that are due. Runs every 15 minutes from beat."""

# Python imports
import datetime as dt
import json
import logging

# Django imports
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.utils.html import escape

# Third party imports
from celery import shared_task

# Module imports
from plane.bgtasks.issue_activities_task import issue_activity
from plane.db.models import (
    Issue,
    IssueAssignee,
    IssueComment,
    IssueLabel,
    IssueRecurrence,
    IssueRecurrenceRun,
    ModuleIssue,
    ProjectMember,
    State,
)
from plane.utils.recurrence import next_occurrence, summary

logger = logging.getLogger("plane.worker")


def copy_state(project):
    state = State.objects.filter(project=project, group="unstarted").order_by("sequence").first()
    return state or State.objects.filter(project=project, default=True).first()


def copy_creator(rule, template):
    if rule.actor_id and ProjectMember.objects.filter(
        project_id=rule.project_id, member_id=rule.actor_id, is_active=True, role__gte=15
    ).exists():
        return rule.actor_id
    # last resort so the copy and its activity always have an author
    return template.created_by_id or template.project.workspace.owner_id


def create_copy(rule, occurrence_date):
    template = rule.issue
    project = template.project
    creator_id = copy_creator(rule, template)
    common = {"project_id": project.id, "workspace_id": project.workspace_id, "created_by_id": creator_id}

    # BaseModel.save() overwrites created_by with the request user, and a beat task has none:
    # build the rows ourselves and save with disable_auto_set_user so created_by sticks.
    copy = Issue(
        name=template.name,
        description_html=template.description_html,
        description_json=template.description_json,
        description_binary=template.description_binary,
        priority=template.priority,
        estimate_point_id=template.estimate_point_id,
        parent_id=template.parent_id,
        type_id=template.type_id,
        state=copy_state(project),
        target_date=occurrence_date,
        project=project,
        workspace_id=project.workspace_id,
        created_by_id=creator_id,
    )
    copy.save(disable_auto_set_user=True)

    assignee_id = IssueAssignee.objects.filter(issue=template).values_list("assignee_id", flat=True).first()
    if assignee_id:
        IssueAssignee(issue=copy, assignee_id=assignee_id, **common).save(disable_auto_set_user=True)
    IssueLabel.objects.bulk_create(
        [
            IssueLabel(issue=copy, label_id=label_id, **common)
            for label_id in IssueLabel.objects.filter(issue=template).values_list("label_id", flat=True)
        ]
    )
    ModuleIssue.objects.bulk_create(
        [
            ModuleIssue(issue=copy, module_id=module_id, **common)
            for module_id in ModuleIssue.objects.filter(issue=template).values_list("module_id", flat=True)
        ]
    )

    ident = f"{project.identifier}-{template.sequence_id}"
    url = f"{(settings.WEB_URL or '').rstrip('/')}/{project.workspace.slug}/browse/{ident}/"
    IssueComment(
        issue=copy,
        actor_id=creator_id,
        comment_html=f'<p>Created from <a href="{escape(url)}">{escape(ident)}</a> (repeats {escape(summary(rule))})</p>',
        **common,
    ).save(disable_auto_set_user=True)

    # queue only after commit: the worker must be able to see the copy, and a rollback must not leave a task behind
    transaction.on_commit(
        lambda: issue_activity.delay(
            type="issue.activity.created",
            requested_data=json.dumps({"name": copy.name, "assignee_ids": [str(assignee_id)] if assignee_id else []}),
            actor_id=str(creator_id),
            issue_id=str(copy.id),
            project_id=str(project.id),
            current_instance=None,
            epoch=int(timezone.now().timestamp()),
            notification=True,
            origin=settings.WEB_URL,
        )
    )
    return copy


def is_live(template):
    return template.deleted_at is None and template.archived_at is None and template.project.archived_at is None


def run_rule(rule_id, now):
    """Create the due copy for one rule. Returns 1 if a copy was created, else 0."""
    with transaction.atomic():
        rule = (
            # of=("self",): lock only the rule row, not the joined project row a user may be editing
            IssueRecurrence.objects.select_for_update(skip_locked=True, of=("self",))
            .select_related("project")
            .filter(pk=rule_id, is_active=True, next_run_at__lte=now)
            .first()
        )
        if rule is None:
            return 0
        template = Issue.all_objects.select_related("project", "project__workspace").get(pk=rule.issue_id)
        if not is_live(template):
            rule.is_active = False
            rule.save(update_fields=["is_active", "updated_at"], disable_auto_set_user=True)
            return 0

        tz = rule.tz
        # collapse missed runs: only the latest occurrence <= now gets a copy
        occurrence = rule.next_run_at
        while (following := next_occurrence(rule, occurrence, tz)) <= now:
            occurrence = following

        run, created = IssueRecurrenceRun.objects.get_or_create(
            recurrence=rule,
            occurrence_date=occurrence.astimezone(tz).date(),
            defaults={"project_id": rule.project_id, "workspace_id": rule.workspace_id},
        )
        made = 0
        if created:
            rule.issue = template
            run.issue = create_copy(rule, run.occurrence_date)
            run.save(update_fields=["issue", "updated_at"], disable_auto_set_user=True)
            made = 1

        rule.last_run_at = occurrence
        rule.next_run_at = following
        rule.save(update_fields=["last_run_at", "next_run_at", "updated_at"], disable_auto_set_user=True)
        return made


@shared_task
def create_due_recurring_issues(now_iso=None):
    now = dt.datetime.fromisoformat(now_iso) if now_iso else timezone.now()
    due = IssueRecurrence.objects.filter(is_active=True, next_run_at__lte=now).values_list("id", flat=True)
    created = 0
    for rule_id in list(due):
        try:
            created += run_rule(rule_id, now)
        except Exception:
            logger.exception("recurring story %s failed", rule_id)
    return created
