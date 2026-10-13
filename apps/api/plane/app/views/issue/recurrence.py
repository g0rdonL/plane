# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Aight fork: set, read and clear a story's repeat rule."""

# Django imports
from django.shortcuts import get_object_or_404
from django.utils import timezone

# Third Party imports
from rest_framework import status
from rest_framework.response import Response

# Module imports
from .. import BaseAPIView
from plane.app.permissions import ROLE, allow_permission
from plane.app.serializers import IssueRecurrenceSerializer
from plane.db.models import Issue, IssueRecurrence
from plane.utils.recurrence import next_occurrence


class IssueRecurrenceEndpoint(BaseAPIView):
    def get_issue(self, slug, project_id, issue_id):
        return get_object_or_404(
            Issue.objects.select_related("project"), pk=issue_id, project_id=project_id, workspace__slug=slug
        )

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER, ROLE.GUEST])
    def get(self, request, slug, project_id, issue_id):
        rule = IssueRecurrence.objects.filter(
            issue_id=issue_id, project_id=project_id, workspace__slug=slug, is_active=True
        ).first()
        if rule is None:
            return Response({"error": "This story does not repeat."}, status=status.HTTP_404_NOT_FOUND)
        return Response(IssueRecurrenceSerializer(rule).data, status=status.HTTP_200_OK)

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER])
    def put(self, request, slug, project_id, issue_id):
        issue = self.get_issue(slug, project_id, issue_id)
        serializer = IssueRecurrenceSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        rule = IssueRecurrence.objects.filter(issue=issue).first() or IssueRecurrence(
            issue=issue, project_id=project_id
        )
        for field, value in serializer.validated_data.items():
            setattr(rule, field, value)
        rule.is_active = True
        rule.actor = request.user
        rule.project = issue.project
        rule.next_run_at = next_occurrence(rule, timezone.now(), rule.tz)
        rule.save()
        return Response(IssueRecurrenceSerializer(rule).data, status=status.HTTP_200_OK)

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER])
    def delete(self, request, slug, project_id, issue_id):
        issue = self.get_issue(slug, project_id, issue_id)
        for rule in IssueRecurrence.objects.filter(issue=issue):
            rule.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
