# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Aight fork: every project needs the carry-over label (Performance Evaluation §2).
# Idempotent; copies colour and description from an existing carry-over label in the workspace.

# Django imports
from django.core.management.base import BaseCommand, CommandError

# Module imports
from plane.db.models import Label, User
from plane.utils.monthly_summary import CARRY_OVER, projects_missing_carry_over

DEFAULT_COLOR = "#F59E0B"


class Command(BaseCommand):
    help = "Create the carry-over label in every project that lacks it"

    def add_arguments(self, parser):
        parser.add_argument("--actor", required=True, help="Email of the user the labels are created by")
        parser.add_argument("--workspace", help="Workspace slug (default: all workspaces)")
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        actor = User.objects.filter(email=options["actor"]).first()
        if actor is None:
            raise CommandError(f"No user with email {options['actor']}")

        created = 0
        for project in projects_missing_carry_over(options["workspace"]):
            self.stdout.write(f"{project.workspace.slug}/{project.identifier}")
            if options["dry_run"]:
                created += 1
                continue
            template = Label.objects.filter(workspace=project.workspace, name__iexact=CARRY_OVER).first()
            Label.objects.create(
                name=CARRY_OVER,
                color=template.color if template else DEFAULT_COLOR,
                description=template.description if template else "",
                project=project,
                workspace=project.workspace,
                created_by=actor,
                updated_by=actor,
            )
            created += 1

        verb = "Would create" if options["dry_run"] else "Created"
        self.stdout.write(self.style.SUCCESS(f"{verb} {created} carry-over labels"))
