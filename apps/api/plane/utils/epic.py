# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Django imports
from django.db import IntegrityError
from django.db.models import Q

# Module imports
from plane.db.models import IssueType, Project
from plane.db.models.issue_type import ProjectIssueType

EPIC_TYPE_NAME = "Epic"


def is_epic_request(request):
    """True when the request was routed through one of the `/epics/` aliases."""
    match = getattr(request, "resolver_match", None)
    route = getattr(match, "route", "") or ""
    return "/epics/" in route or "/epics-" in route


def epic_q(is_epic):
    """Filter selecting epics (is_epic=True) or regular work items (is_epic=False)."""
    if is_epic:
        return Q(type__is_epic=True)
    return Q(type__isnull=True) | Q(type__is_epic=False)


def epic_request_q(request):
    return epic_q(is_epic_request(request))


def get_epic_type(project_id):
    """Return the workspace's epic IssueType, creating it and linking it to the project on first use."""
    project = Project.objects.get(pk=project_id)
    epic_type = IssueType.objects.filter(workspace_id=project.workspace_id, is_epic=True).first()
    if epic_type is None:
        epic_type = IssueType.objects.create(
            workspace_id=project.workspace_id,
            name=EPIC_TYPE_NAME,
            description="Epics group related work items",
            is_epic=True,
            level=1,
        )
    if not ProjectIssueType.objects.filter(project_id=project_id, issue_type=epic_type).exists():
        try:
            ProjectIssueType.objects.create(
                project_id=project_id,
                workspace_id=project.workspace_id,
                issue_type=epic_type,
                level=1,
            )
        except IntegrityError:
            pass
    return epic_type
