# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Aight fork: recurring stories. A story with an active IssueRecurrence is a template; the
recurrence beat task creates a copy of it on every due day (see plane.bgtasks.recurrence_task)."""

import zoneinfo

from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.db.models import Q

from plane.utils.recurrence import FREQUENCIES

from .project import ProjectBaseModel


class IssueRecurrence(ProjectBaseModel):
    FREQUENCY_CHOICES = tuple((f, f) for f in FREQUENCIES)

    issue = models.ForeignKey("db.Issue", on_delete=models.CASCADE, related_name="recurrences")
    frequency = models.CharField(max_length=16, choices=FREQUENCY_CHOICES)
    weekdays = ArrayField(models.SmallIntegerField(), default=list, blank=True)
    day_of_month = models.SmallIntegerField(null=True, blank=True)
    next_run_at = models.DateTimeField(db_index=True)
    last_run_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="issue_recurrences"
    )

    class Meta:
        verbose_name = "Issue Recurrence"
        verbose_name_plural = "Issue Recurrences"
        db_table = "issue_recurrences"
        ordering = ("-created_at",)
        constraints = [
            models.UniqueConstraint(
                fields=["issue"],
                condition=Q(deleted_at__isnull=True),
                name="issue_recurrence_unique_issue_when_deleted_at_null",
            )
        ]

    @property
    def tz(self):
        return zoneinfo.ZoneInfo(self.project.timezone or "UTC")


class IssueRecurrenceRun(ProjectBaseModel):
    recurrence = models.ForeignKey(IssueRecurrence, on_delete=models.CASCADE, related_name="runs")
    occurrence_date = models.DateField()
    issue = models.ForeignKey(
        "db.Issue", on_delete=models.SET_NULL, null=True, blank=True, related_name="recurrence_runs"
    )

    class Meta:
        verbose_name = "Issue Recurrence Run"
        verbose_name_plural = "Issue Recurrence Runs"
        db_table = "issue_recurrence_runs"
        ordering = ("-occurrence_date",)
        constraints = [
            models.UniqueConstraint(
                fields=["recurrence", "occurrence_date"],
                condition=Q(deleted_at__isnull=True),
                name="issue_recurrence_run_unique_date_when_deleted_at_null",
            )
        ]
