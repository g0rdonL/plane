# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Python imports
import json

# Django imports
from django.db.models import Case, Count, F, FloatField, Q, Sum, Value, When
from django.db.models.functions import Cast, Coalesce
from django.utils import timezone

# Third Party imports
from rest_framework import status
from rest_framework.response import Response

# Module imports
from .. import BaseAPIView
from plane.app.permissions import allow_permission, ROLE
from plane.bgtasks.issue_activities_task import issue_activity
from plane.db.models import Issue
from plane.utils.epic import get_epic_type
from plane.utils.host import base_host

STATE_GROUPS = ["backlog", "unstarted", "started", "completed", "cancelled"]


class EpicAnalyticsEndpoint(BaseAPIView):
    """Progress of an epic: work item counts per state group plus estimate point rollups."""

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER, ROLE.GUEST])
    def get(self, request, slug, project_id, epic_id):
        epic = Issue.objects.filter(
            workspace__slug=slug, project_id=project_id, pk=epic_id, type__is_epic=True
        ).first()
        if epic is None:
            return Response({"error": "Epic not found"}, status=status.HTTP_404_NOT_FOUND)

        work_items = Issue.issue_objects.filter(workspace__slug=slug, parent_id=epic_id)
        today = timezone.now().date()

        counts = work_items.aggregate(
            total_issues=Count("id"),
            overdue_issues=Count(
                "id",
                filter=Q(target_date__lt=today) & ~Q(state__group__in=["completed", "cancelled"]),
            ),
            **{f"{group}_issues": Count("id", filter=Q(state__group=group)) for group in STATE_GROUPS},
        )

        points = (
            work_items.filter(estimate_point__estimate__type="points")
            .annotate(value_as_float=Cast("estimate_point__value", FloatField()))
            .aggregate(
                total_estimate_points=Coalesce(Sum("value_as_float"), Value(0.0), output_field=FloatField()),
                **{
                    f"{group}_estimate_points": Coalesce(
                        Sum(
                            Case(
                                When(state__group=group, then=F("value_as_float")),
                                default=Value(0.0),
                                output_field=FloatField(),
                            )
                        ),
                        Value(0.0),
                        output_field=FloatField(),
                    )
                    for group in STATE_GROUPS
                },
            )
        )

        return Response({**counts, **points}, status=status.HTTP_200_OK)


class WorkItemConvertEndpoint(BaseAPIView):
    """Convert a work item into an epic, or an epic back into a work item."""

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER])
    def post(self, request, slug, project_id, issue_id):
        to_epic = bool(request.data.get("is_epic", True))
        issue = Issue.objects.get(workspace__slug=slug, project_id=project_id, pk=issue_id)
        was_epic = bool(issue.type_id and issue.type.is_epic)
        if was_epic == to_epic:
            return Response({"id": str(issue.id), "is_epic": was_epic}, status=status.HTTP_200_OK)

        if to_epic:
            if issue.parent_id and issue.parent.type_id and issue.parent.type.is_epic:
                # Epics sit at the top of the hierarchy
                issue.parent = None
            issue.type = get_epic_type(project_id)
        else:
            if Issue.issue_objects.filter(parent_id=issue.id).exists() and issue.parent_id:
                issue.parent = None
            issue.type = None
        issue.save(update_fields=["type", "parent", "updated_at"])

        issue_activity.delay(
            type="issue.activity.updated",
            requested_data=json.dumps({"is_epic": to_epic}),
            actor_id=str(request.user.id),
            issue_id=str(issue.id),
            project_id=str(project_id),
            current_instance=json.dumps({"is_epic": was_epic}),
            epoch=int(timezone.now().timestamp()),
            notification=False,
            origin=base_host(request=request, is_app=True),
        )
        return Response({"id": str(issue.id), "is_epic": to_epic}, status=status.HTTP_200_OK)
