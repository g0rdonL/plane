# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Aight fork: backfill for the sprint defaults (Backlog -> Todo, no priority -> Medium).

# Django imports
from django.core.management.base import BaseCommand, CommandError

# Module imports
from plane.db.models import Issue, User
from plane.utils.sprint import apply_sprint_defaults, open_sprint_q, sprint_defaults_q


class Command(BaseCommand):
    help = "Move Backlog stories in sprints that haven't ended to Todo and set empty priority to Medium"

    def add_arguments(self, parser):
        parser.add_argument("--actor", required=True, help="Email of the user the changes are attributed to")
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        actor = User.objects.filter(email=options["actor"]).first()
        if actor is None:
            raise CommandError(f"No user with email {options['actor']}")

        rows = (
            Issue.issue_objects.filter(open_sprint_q(), sprint_defaults_q())
            .values_list("project_id", "id", "project__identifier", "sequence_id", "state__group", "priority")
            .distinct()
        )
        by_project = {}
        for project_id, issue_id, identifier, sequence_id, group, priority in rows:
            by_project.setdefault(project_id, []).append(issue_id)
            self.stdout.write(f"{identifier}-{sequence_id} state={group} priority={priority}")

        total = 0
        for project_id, issue_ids in by_project.items():
            if options["dry_run"]:
                total += len(issue_ids)
                continue
            changed = apply_sprint_defaults(issue_ids, project_id, actor.id)
            total += len(changed)
            if len(changed) < len(issue_ids):
                self.stderr.write(f"Project {project_id} has no Todo (unstarted) state; Backlog stories skipped")

        verb = "Would update" if options["dry_run"] else "Updated"
        self.stdout.write(self.style.SUCCESS(f"{verb} {total} stories"))
