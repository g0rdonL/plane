# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Aight fork: read-only monthly per-person export for People Ops' Monthly Summaries.
# Definitions live in plane/utils/monthly_summary.py.

# Python imports
import csv
import json
import re

# Django imports
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction

# Module imports
from plane.utils.monthly_summary import monthly_summary, projects_missing_carry_over


class Command(BaseCommand):
    help = "Per-person planned/completed/on-time/carry-over numbers for one month (read-only)"

    def add_arguments(self, parser):
        parser.add_argument("--month", required=True, help="YYYY-MM, in Bangkok time")
        parser.add_argument("--workspace", help="Workspace slug (default: all workspaces)")
        parser.add_argument("--detail", action="store_true", help="One row per person and story instead")
        parser.add_argument("--format", choices=["csv", "json"], default="csv")

    def handle(self, *args, **options):
        match = re.fullmatch(r"(\d{4})-(\d{2})", options["month"])
        if not match or not 1 <= int(match.group(2)) <= 12:
            raise CommandError("--month must be YYYY-MM")
        year, month = int(match.group(1)), int(match.group(2))

        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("SET TRANSACTION READ ONLY")
            summary, details = monthly_summary(year, month, options["workspace"])
            missing = list(projects_missing_carry_over(options["workspace"]))

        for project in missing:
            self.stderr.write(f"Warning: {project.workspace.slug}/{project.identifier} has no carry-over label")

        rows = details if options["detail"] else summary
        if options["format"] == "json":
            self.stdout.write(json.dumps(rows, ensure_ascii=False, indent=2))
            return
        if rows:
            writer = csv.DictWriter(self.stdout, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
