# Recurring Stories Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Any story in the Aight Plane fork can be set to repeat (daily / weekdays / weekly on days / monthly on a date); Plane creates a fresh copy on each due day at 08:00 project time.

**Architecture:** Two new models (`IssueRecurrence` rule, `IssueRecurrenceRun` per-occurrence row) hang off the template story. A pure `next_occurrence()` function computes schedule instants. A celery-beat task every 15 min creates due copies idempotently. A small app-API endpoint (GET/PUT/DELETE) plus a `recurrence` field on the issue detail payload feed a "Repeats" property in the web sidebar and peek view.

**Tech Stack:** Django 5.2 + DRF + Celery beat (`DatabaseScheduler`), Postgres (`ArrayField`), React + MobX + headlessui, `@plane/i18n`.

**Spec:** `docs/superpowers/specs/2026-10-13-recurring-stories-design.md`

## Global Constraints

- Branch `feat/recurring-stories` off `aight/epics`; PR base is **`aight/epics`** (the fork has no `main`).
- Fire time: **08:00 in `Project.timezone`** (all prod projects are `Asia/Bangkok`). Not configurable.
- Frequencies: exactly `daily`, `weekdays`, `weekly`, `monthly`. Weekdays use **0 = Mon … 6 = Sun**. `day_of_month` 1–31, clamped to month end.
- Copy: state = first `unstarted`-group state (fallback project default); `target_date` = occurrence date; no cycle; at most **one** assignee (fork rule from #16).
- Permission: project **ADMIN and MEMBER** only (`ROLE.ADMIN`, `ROLE.MEMBER`); guests get 403.
- Every new source file starts with the fork's 3-line AGPL header (`# Copyright (c) 2023-present Plane Software, Inc. and contributors` / `# SPDX-License-Identifier: AGPL-3.0-only` / `# See the LICENSE file for details.`; `/** … */` block form for TS).
- Pre-commit runs `oxfmt` and `oxlint --deny-warnings` on staged TS files — new TS must be warning-free; don't `--no-verify`.
- Backend tests run in Docker: `docker compose -f docker-compose-test.yml -f /tmp/plane-test-override/override.yml run --rm --build api-tests pytest <path> -q` where the override file contains `services:\n  test-minio:\n    image: pgsty/minio:latest\n` (Docker Hub dropped `minio/minio`). Create it once: `mkdir -p /tmp/plane-test-override && printf 'services:\n  test-minio:\n    image: pgsty/minio:latest\n' > /tmp/plane-test-override/override.yml`. Second `User` in a test needs a unique `username`.
- Commits end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. **Duplicate copies** — beat retries, two workers, or a crash between "create copy" and "advance next_run_at" must never yield two copies for one occurrence → `IssueRecurrenceRun` unique `(recurrence, occurrence_date)` + `get_or_create` inside the lock. Test: Task 3 `test_running_twice_creates_one_copy` and `test_existing_run_row_is_not_recreated`.
2. **Stopping and restarting a repeat** — DELETE then PUT again on the same story must work (soft-deleted rows must not block a new rule) → partial unique constraint on `issue` where `deleted_at IS NULL`. Test: Task 4 `test_delete_then_set_again`.
3. **Month-end and leap-year dates** — "monthly on 31" in Feb / Apr; "monthly on 29" in a non-leap February → last day of month. Test: Task 1 `test_monthly_31_clamps_*`, `test_monthly_29_non_leap_feb`.
4. **Template goes away** — archived/deleted template or archived project must stop the rule rather than error every 15 min. Test: Task 3 `test_archived_template_deactivates`, `test_deleted_template_deactivates`.
5. **Rule actor left the project** — copies must still be created (fallback to template creator) so a departure doesn't silently stop HR routines. Test: Task 3 `test_actor_left_falls_back_to_template_creator`.

---

## File Structure

| File                                                                                           | Responsibility                                                       |
| ---------------------------------------------------------------------------------------------- | -------------------------------------------------------------------- |
| `apps/api/plane/utils/recurrence.py` (new)                                                     | Pure schedule maths: `matches()`, `next_occurrence()`, `summary()`   |
| `apps/api/plane/db/models/recurrence.py` (new)                                                 | `IssueRecurrence`, `IssueRecurrenceRun`                              |
| `apps/api/plane/db/models/__init__.py`                                                         | export the two models                                                |
| `apps/api/plane/db/migrations/0123_issuerecurrence_issuerecurrencerun.py` (new, generated)     | schema                                                               |
| `apps/api/plane/bgtasks/recurrence_task.py` (new)                                              | beat task + `create_copy()`                                          |
| `apps/api/plane/celery.py`                                                                     | beat entry every 15 min                                              |
| `apps/api/plane/app/serializers/recurrence.py` (new)                                           | `IssueRecurrenceSerializer` (validate + representation)              |
| `apps/api/plane/app/serializers/__init__.py`                                                   | export it                                                            |
| `apps/api/plane/app/serializers/issue.py`                                                      | `IssueDetailSerializer.recurrence` read field                        |
| `apps/api/plane/app/views/issue/recurrence.py` (new)                                           | `IssueRecurrenceEndpoint` GET/PUT/DELETE                             |
| `apps/api/plane/app/urls/issue.py`                                                             | route                                                                |
| `apps/api/plane/tests/unit/utils/test_recurrence.py` (new)                                     | schedule unit tests                                                  |
| `apps/api/plane/tests/contract/app/test_issue_recurrence_app.py` (new)                         | API + generator contract tests                                       |
| `packages/types/src/issues/issue.ts`                                                           | `TIssueRecurrence`, `TIssueRecurrenceFrequency`, `TIssue.recurrence` |
| `apps/web/core/services/issue/issue_recurrence.service.ts` (new)                               | HTTP client                                                          |
| `apps/web/core/components/issues/recurrence/summary.ts` (new)                                  | i18n summary string                                                  |
| `apps/web/core/components/issues/recurrence/property.tsx` (new)                                | `IssueRecurrenceProperty` popover                                    |
| `apps/web/core/components/issues/issue-detail/sidebar.tsx`, `.../peek-overview/properties.tsx` | mount "Repeats"                                                      |
| `packages/i18n/src/locales/*/work-item.json` (19 locales)                                      | `recurrence.*` keys                                                  |

---

### Task 1: Schedule maths

**Files:**

- Create: `apps/api/plane/utils/recurrence.py`
- Test: `apps/api/plane/tests/unit/utils/test_recurrence.py` (create `tests/unit/utils/__init__.py` if the directory lacks one — check `ls apps/api/plane/tests/unit/utils/`)

**Interfaces:**

- Produces:
  - `FREQUENCIES = ("daily", "weekdays", "weekly", "monthly")`
  - `FIRE_TIME: datetime.time` = 08:00
  - `matches(rule, day: datetime.date) -> bool`
  - `next_occurrence(rule, after: datetime.datetime, tz: zoneinfo.ZoneInfo) -> datetime.datetime` — tz-aware **UTC**, strictly `> after`
  - `summary(rule) -> str` — e.g. `"daily"`, `"weekdays"`, `"weekly on Mon, Fri"`, `"monthly on day 1"`
  - `rule` is duck-typed: any object with `.frequency: str`, `.weekdays: list[int]`, `.day_of_month: int | None`.

- [ ] **Step 1: Write the failing tests**

```python
# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Aight fork: schedule maths for recurring stories."""

import datetime as dt
import zoneinfo
from types import SimpleNamespace

import pytest

from plane.utils.recurrence import next_occurrence, summary

BKK = zoneinfo.ZoneInfo("Asia/Bangkok")
LON = zoneinfo.ZoneInfo("Europe/London")
UTC = dt.timezone.utc


def rule(frequency, weekdays=None, day_of_month=None):
    return SimpleNamespace(frequency=frequency, weekdays=weekdays or [], day_of_month=day_of_month)


def bkk(y, m, d, h=0, mi=0):
    return dt.datetime(y, m, d, h, mi, tzinfo=BKK)


@pytest.mark.unit
class TestNextOccurrence:
    def test_daily_before_eight_fires_today(self):
        # Mon 13 Oct 2026 07:59 BKK → same day 08:00 BKK = 01:00 UTC
        assert next_occurrence(rule("daily"), bkk(2026, 10, 13, 7, 59), BKK) == dt.datetime(2026, 10, 13, 1, 0, tzinfo=UTC)

    def test_daily_at_eight_exactly_moves_to_tomorrow(self):
        assert next_occurrence(rule("daily"), bkk(2026, 10, 13, 8, 0), BKK) == dt.datetime(2026, 10, 14, 1, 0, tzinfo=UTC)

    def test_result_is_utc(self):
        assert next_occurrence(rule("daily"), bkk(2026, 10, 13), BKK).tzinfo == UTC

    def test_weekdays_skips_weekend(self):
        # Fri 16 Oct 2026 09:00 → Mon 19 Oct 08:00
        assert next_occurrence(rule("weekdays"), bkk(2026, 10, 16, 9), BKK) == bkk(2026, 10, 19, 8).astimezone(UTC)

    def test_weekly_on_friday(self):
        # Tue 13 Oct → Fri 16 Oct (weekday 4)
        assert next_occurrence(rule("weekly", [4]), bkk(2026, 10, 13, 12), BKK) == bkk(2026, 10, 16, 8).astimezone(UTC)

    def test_weekly_multiple_days_picks_nearest(self):
        # Tue 13 Oct 12:00, days Mon+Wed → Wed 14 Oct
        assert next_occurrence(rule("weekly", [0, 2]), bkk(2026, 10, 13, 12), BKK) == bkk(2026, 10, 14, 8).astimezone(UTC)

    def test_weekly_wraps_to_next_week(self):
        # Sat 17 Oct, Mon only → Mon 19 Oct
        assert next_occurrence(rule("weekly", [0]), bkk(2026, 10, 17, 12), BKK) == bkk(2026, 10, 19, 8).astimezone(UTC)

    def test_monthly_first(self):
        assert next_occurrence(rule("monthly", day_of_month=1), bkk(2026, 10, 13), BKK) == bkk(2026, 11, 1, 8).astimezone(UTC)

    def test_monthly_31_clamps_in_30_day_month(self):
        # November has 30 days → 30 Nov
        assert next_occurrence(rule("monthly", day_of_month=31), bkk(2026, 11, 1), BKK) == bkk(2026, 11, 30, 8).astimezone(UTC)

    def test_monthly_31_clamps_february(self):
        assert next_occurrence(rule("monthly", day_of_month=31), bkk(2027, 2, 1), BKK) == bkk(2027, 2, 28, 8).astimezone(UTC)

    def test_monthly_29_non_leap_feb(self):
        assert next_occurrence(rule("monthly", day_of_month=29), bkk(2027, 2, 1), BKK) == bkk(2027, 2, 28, 8).astimezone(UTC)

    def test_monthly_29_leap_feb(self):
        assert next_occurrence(rule("monthly", day_of_month=29), bkk(2028, 2, 1), BKK) == bkk(2028, 2, 29, 8).astimezone(UTC)

    def test_monthly_after_clamped_day_goes_to_next_month(self):
        # Fired 30 Nov (clamped 31) → next is 31 Dec
        after = bkk(2026, 11, 30, 8)
        assert next_occurrence(rule("monthly", day_of_month=31), after, BKK) == bkk(2026, 12, 31, 8).astimezone(UTC)

    def test_dst_zone_keeps_local_eight(self):
        # London switches to GMT on 25 Oct 2026: 08:00 local is 07:00 UTC before, 08:00 UTC after
        before = next_occurrence(rule("daily"), dt.datetime(2026, 10, 23, 9, tzinfo=LON), LON)
        after = next_occurrence(rule("daily"), dt.datetime(2026, 10, 25, 9, tzinfo=LON), LON)
        assert before == dt.datetime(2026, 10, 24, 7, 0, tzinfo=UTC)
        assert after == dt.datetime(2026, 10, 26, 8, 0, tzinfo=UTC)


@pytest.mark.unit
class TestSummary:
    def test_summaries(self):
        assert summary(rule("daily")) == "daily"
        assert summary(rule("weekdays")) == "weekdays"
        assert summary(rule("weekly", [4, 0])) == "weekly on Mon, Fri"
        assert summary(rule("monthly", day_of_month=1)) == "monthly on day 1"
```

- [ ] **Step 2: Run to verify failure**

Run: `cd ~/dev/plane && docker compose -f docker-compose-test.yml -f /tmp/plane-test-override/override.yml run --rm --build api-tests pytest plane/tests/unit/utils/test_recurrence.py -q`
Expected: collection error `ModuleNotFoundError: No module named 'plane.utils.recurrence'`.

- [ ] **Step 3: Implement**

```python
# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Aight fork: schedule maths for recurring stories.

A rule fires at 08:00 project-local time on every matching day. Weekdays are 0 = Mon … 6 = Sun.
Monthly rules on a day the month lacks (29–31) fire on the month's last day.
"""

import calendar
import datetime as dt

FREQUENCIES = ("daily", "weekdays", "weekly", "monthly")
FIRE_TIME = dt.time(8, 0)
DAY_NAMES = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
# 400 days covers every frequency (worst case: monthly, ~31 days)
SEARCH_DAYS = 400


def matches(rule, day):
    if rule.frequency == "daily":
        return True
    if rule.frequency == "weekdays":
        return day.weekday() < 5
    if rule.frequency == "weekly":
        return day.weekday() in rule.weekdays
    if rule.frequency == "monthly":
        last_day = calendar.monthrange(day.year, day.month)[1]
        return day.day == min(rule.day_of_month, last_day)
    raise ValueError(f"unknown frequency {rule.frequency!r}")


def next_occurrence(rule, after, tz):
    """First 08:00 project-local instant strictly after `after` that matches the rule, in UTC."""
    day = after.astimezone(tz).date()
    for _ in range(SEARCH_DAYS):
        candidate = dt.datetime.combine(day, FIRE_TIME, tzinfo=tz)
        if candidate > after and matches(rule, day):
            return candidate.astimezone(dt.timezone.utc)
        day += dt.timedelta(days=1)
    raise ValueError("rule never fires")


def summary(rule):
    if rule.frequency == "weekly":
        return "weekly on " + ", ".join(DAY_NAMES[d] for d in sorted(rule.weekdays))
    if rule.frequency == "monthly":
        return f"monthly on day {rule.day_of_month}"
    return rule.frequency
```

- [ ] **Step 4: Run to verify pass**

Run: same command as Step 2. Expected: `15 passed`.

- [ ] **Step 5: Commit**

```bash
git add apps/api/plane/utils/recurrence.py apps/api/plane/tests/unit/utils/
git commit -m "feat(api): schedule maths for recurring stories

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Models and migration

**Files:**

- Create: `apps/api/plane/db/models/recurrence.py`
- Modify: `apps/api/plane/db/models/__init__.py` (append import)
- Create (generated): `apps/api/plane/db/migrations/0123_issuerecurrence_issuerecurrencerun.py`
- Test: `apps/api/plane/tests/contract/app/test_issue_recurrence_app.py` (model section; later tasks append)

**Interfaces:**

- Consumes: `plane.utils.recurrence.FREQUENCIES`
- Produces:
  - `IssueRecurrence(ProjectBaseModel)`: `issue` FK → Issue (`related_name="recurrences"`), `frequency`, `weekdays: list[int]`, `day_of_month: int|None`, `next_run_at`, `last_run_at`, `is_active`, `actor` FK → User (`related_name="issue_recurrences"`, SET_NULL). Partial unique on `issue` where `deleted_at IS NULL`. Property `tz -> ZoneInfo` from `self.project.timezone`.
  - `IssueRecurrenceRun(ProjectBaseModel)`: `recurrence` FK (`related_name="runs"`), `occurrence_date: date`, `issue` FK → Issue (`related_name="recurrence_runs"`, SET_NULL, null). Partial unique `(recurrence, occurrence_date)` where `deleted_at IS NULL`.

Note: `issue` is a ForeignKey with a partial unique constraint, not a OneToOneField, so a soft-deleted rule doesn't block setting a new one on the same story.

- [ ] **Step 1: Write the failing test** (new file; fixtures reused by Tasks 3–4)

```python
# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Aight fork: recurring stories — model, generator and API."""

import datetime as dt

import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework import status

from plane.db.models import (
    Issue,
    IssueAssignee,
    IssueComment,
    IssueLabel,
    IssueRecurrence,
    IssueRecurrenceRun,
    Label,
    Module,
    ModuleIssue,
    Project,
    ProjectMember,
    State,
    User,
    WorkspaceMember,
)

UTC = dt.timezone.utc


@pytest.fixture
def project(db, workspace, create_user):
    project = Project.objects.create(
        name="Ops", identifier="OPS", workspace=workspace, created_by=create_user, timezone="Asia/Bangkok"
    )
    ProjectMember.objects.create(project=project, member=create_user, role=20, is_active=True)
    return project


@pytest.fixture
def states(project, workspace):
    def make(name, group, sequence, default=False):
        return State.objects.create(
            name=name, group=group, sequence=sequence, default=default, project=project, workspace=workspace
        )

    return {
        "backlog": make("Backlog", "backlog", 1000, default=True),
        "todo": make("Todo", "unstarted", 2000),
        "done": make("Done", "completed", 3000),
    }


@pytest.fixture
def teammate(db, workspace, project):
    user = User.objects.create(email="mate@plane.so", username="mate", first_name="Team", last_name="Mate")
    WorkspaceMember.objects.create(workspace=workspace, member=user, role=15)
    ProjectMember.objects.create(project=project, member=user, role=15, is_active=True)
    return user


@pytest.fixture
def template(project, workspace, states, create_user):
    # disable_auto_set_user: BaseModel.save() would otherwise reset created_by to the (absent) request user
    issue = Issue(
        name="Payroll checklist",
        description_html="<p>Run payroll</p>",
        priority="high",
        project=project,
        workspace=workspace,
        state=states["done"],
        created_by=create_user,
    )
    issue.save(disable_auto_set_user=True)
    return issue


def make_rule(template, actor, next_run_at, frequency="daily", weekdays=None, day_of_month=None):
    return IssueRecurrence.objects.create(
        issue=template,
        project=template.project,
        frequency=frequency,
        weekdays=weekdays or [],
        day_of_month=day_of_month,
        next_run_at=next_run_at,
        actor=actor,
    )


@pytest.mark.contract
class TestRecurrenceModels:
    @pytest.mark.django_db
    def test_one_active_rule_per_story(self, template, create_user):
        make_rule(template, create_user, timezone.now())
        with pytest.raises(IntegrityError), transaction.atomic():
            make_rule(template, create_user, timezone.now())

    @pytest.mark.django_db
    def test_soft_deleted_rule_does_not_block_new_one(self, template, create_user):
        make_rule(template, create_user, timezone.now()).delete()
        assert make_rule(template, create_user, timezone.now()).pk

    @pytest.mark.django_db
    def test_one_run_per_occurrence_date(self, template, create_user):
        rule = make_rule(template, create_user, timezone.now())
        IssueRecurrenceRun.objects.create(recurrence=rule, project=rule.project, occurrence_date=dt.date(2026, 10, 13))
        with pytest.raises(IntegrityError), transaction.atomic():
            IssueRecurrenceRun.objects.create(
                recurrence=rule, project=rule.project, occurrence_date=dt.date(2026, 10, 13)
            )

    @pytest.mark.django_db
    def test_tz_comes_from_project(self, template, create_user):
        assert str(make_rule(template, create_user, timezone.now()).tz) == "Asia/Bangkok"
```

- [ ] **Step 2: Run to verify failure**

Run: `… pytest plane/tests/contract/app/test_issue_recurrence_app.py -q`
Expected: `ImportError: cannot import name 'IssueRecurrence'`.

- [ ] **Step 3: Implement the models**

`apps/api/plane/db/models/recurrence.py`:

```python
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
```

Append to `apps/api/plane/db/models/__init__.py`:

```python

from .recurrence import IssueRecurrence, IssueRecurrenceRun
```

- [ ] **Step 4: Generate the migration**

Run: `cd ~/dev/plane && docker compose -f docker-compose-test.yml -f /tmp/plane-test-override/override.yml run --rm --build api-tests python manage.py makemigrations db -n issuerecurrence_issuerecurrencerun`
The container's `/code` is a build copy, so copy the generated file out: re-run with a bind mount instead —
`docker compose -f docker-compose-test.yml -f /tmp/plane-test-override/override.yml run --rm --build -v "$PWD/apps/api/plane/db/migrations:/code/plane/db/migrations" api-tests python manage.py makemigrations db -n issuerecurrence_issuerecurrencerun`
(check the service's workdir with `grep -n working_dir -A0 docker-compose-test.yml apps/api/Dockerfile*` first and adjust `/code` if different).
Expected: `apps/api/plane/db/migrations/0123_issuerecurrence_issuerecurrencerun.py` created, depending on `0122_…`, containing exactly two `CreateModel` ops plus two `AddConstraint` ops — nothing touching other models. If it contains unrelated `AlterField`s, delete those ops.

- [ ] **Step 5: Run to verify pass**

Run: `… pytest plane/tests/contract/app/test_issue_recurrence_app.py -q`
Expected: `4 passed`.

- [ ] **Step 6: Commit**

```bash
git add apps/api/plane/db/models/recurrence.py apps/api/plane/db/models/__init__.py apps/api/plane/db/migrations/0123_issuerecurrence_issuerecurrencerun.py apps/api/plane/tests/contract/app/test_issue_recurrence_app.py
git commit -m "feat(api): recurrence rule and run models

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Generator task

**Files:**

- Create: `apps/api/plane/bgtasks/recurrence_task.py`
- Modify: `apps/api/plane/celery.py` (add beat entry inside `app.conf.beat_schedule`)
- Test: append to `apps/api/plane/tests/contract/app/test_issue_recurrence_app.py`

**Interfaces:**

- Consumes: `next_occurrence`, `summary` (Task 1); `IssueRecurrence`, `IssueRecurrenceRun`, `rule.tz` (Task 2)
- Produces:
  - celery task `plane.bgtasks.recurrence_task.create_due_recurring_issues(now_iso: str | None = None) -> int` (number of copies created; `now_iso` only for tests)
  - `create_copy(rule, occurrence_date: date) -> Issue`
  - `copy_state(project) -> State`

`BaseModel.save()` resets `created_by` to the current request user (None in a beat task) unless called with `disable_auto_set_user=True`; every row the task writes uses that flag. Check that `Issue.save` and `IssueComment.save` forward `**kwargs` to `BaseModel.save` (`grep -n "super().*save" apps/api/plane/db/models/issue.py`); if one doesn't, set `created_by_id` via `Model.objects.filter(pk=…).update(created_by_id=…)` right after saving.

Copy rules (spec): name, description_html/json/binary, priority, estimate_point, parent, type, labels, first assignee, modules. State = first `unstarted` state by `sequence`, else project default. `target_date` = occurrence date. `created_by` = actor if still an active project member with role ≥ 15, else template `created_by`. A comment from that user: `Created from <a href="…">OPS-12</a> (repeats weekly on Fri)` — a comment rather than an activity row, because the web activity renderer drops unknown fields.

- [ ] **Step 1: Write the failing tests** (append to the test file)

```python
from plane.bgtasks.recurrence_task import create_due_recurring_issues  # noqa: E402

# Mon 13 Oct 2026 08:00 Bangkok
FIRST = dt.datetime(2026, 10, 13, 1, 0, tzinfo=UTC)


def run(now):
    return create_due_recurring_issues(now_iso=now.isoformat())


def copies(rule):
    return Issue.objects.filter(recurrence_runs__recurrence=rule).order_by("created_at")


@pytest.mark.contract
class TestRecurrenceGenerator:
    @pytest.mark.django_db
    def test_not_due_creates_nothing(self, template, create_user):
        rule = make_rule(template, create_user, FIRST)
        assert run(FIRST - dt.timedelta(minutes=1)) == 0
        assert not copies(rule).exists()

    @pytest.mark.django_db
    def test_due_creates_copy_with_template_fields(self, template, states, create_user, teammate, project, workspace):
        label = Label.objects.create(name="hr", project=project, workspace=workspace)
        IssueLabel.objects.create(issue=template, label=label, project=project, workspace=workspace)
        IssueAssignee.objects.create(issue=template, assignee=teammate, project=project, workspace=workspace)
        module = Module.objects.create(name="Ops", project=project, workspace=workspace)
        ModuleIssue.objects.create(issue=template, module=module, project=project, workspace=workspace)
        rule = make_rule(template, create_user, FIRST)

        assert run(FIRST + dt.timedelta(minutes=5)) == 1

        copy = copies(rule).get()
        assert copy.id != template.id
        assert copy.name == "Payroll checklist"
        assert copy.description_html == "<p>Run payroll</p>"
        assert copy.priority == "high"
        assert copy.state_id == states["todo"].id
        assert copy.target_date == dt.date(2026, 10, 13)
        assert copy.start_date is None
        assert copy.created_by_id == create_user.id
        assert list(IssueAssignee.objects.filter(issue=copy).values_list("assignee_id", flat=True)) == [teammate.id]
        assert list(IssueLabel.objects.filter(issue=copy).values_list("label_id", flat=True)) == [label.id]
        assert list(ModuleIssue.objects.filter(issue=copy).values_list("module_id", flat=True)) == [module.id]
        assert not copy.issue_cycle.exists()
        comment = IssueComment.objects.get(issue=copy)
        assert f"OPS-{template.sequence_id}" in comment.comment_html
        assert "repeats daily" in comment.comment_html

    @pytest.mark.django_db
    def test_advances_next_run(self, template, create_user):
        rule = make_rule(template, create_user, FIRST)
        run(FIRST)
        rule.refresh_from_db()
        assert rule.last_run_at == FIRST
        assert rule.next_run_at == FIRST + dt.timedelta(days=1)

    @pytest.mark.django_db
    def test_running_twice_creates_one_copy(self, template, create_user):
        rule = make_rule(template, create_user, FIRST)
        run(FIRST)
        run(FIRST + dt.timedelta(minutes=15))
        assert copies(rule).count() == 1

    @pytest.mark.django_db
    def test_existing_run_row_is_not_recreated(self, template, create_user):
        # crash after the run row was written but before next_run_at advanced
        rule = make_rule(template, create_user, FIRST)
        IssueRecurrenceRun.objects.create(recurrence=rule, project=rule.project, occurrence_date=dt.date(2026, 10, 13))
        assert run(FIRST) == 0
        rule.refresh_from_db()
        assert rule.next_run_at == FIRST + dt.timedelta(days=1)

    @pytest.mark.django_db
    def test_missed_runs_collapse_to_latest(self, template, create_user):
        rule = make_rule(template, create_user, FIRST)
        # worker down for 3 days → one copy, dated the latest missed day (Thu 16 Oct)
        assert run(FIRST + dt.timedelta(days=3, hours=1)) == 1
        assert copies(rule).get().target_date == dt.date(2026, 10, 16)
        rule.refresh_from_db()
        assert rule.next_run_at == FIRST + dt.timedelta(days=4)

    @pytest.mark.django_db
    def test_archived_template_deactivates(self, template, create_user):
        rule = make_rule(template, create_user, FIRST)
        Issue.objects.filter(pk=template.pk).update(archived_at=dt.date(2026, 10, 12))
        assert run(FIRST) == 0
        rule.refresh_from_db()
        assert rule.is_active is False

    @pytest.mark.django_db
    def test_deleted_template_deactivates(self, template, create_user):
        rule = make_rule(template, create_user, FIRST)
        Issue.all_objects.filter(pk=template.pk).update(deleted_at=timezone.now())
        assert run(FIRST) == 0
        assert IssueRecurrence.all_objects.get(pk=rule.pk).is_active is False

    @pytest.mark.django_db
    def test_actor_left_falls_back_to_template_creator(self, template, create_user, teammate, project):
        rule = make_rule(template, teammate, FIRST)
        ProjectMember.objects.filter(project=project, member=teammate).update(is_active=False)
        run(FIRST)
        assert copies(rule).get().created_by_id == create_user.id

    @pytest.mark.django_db
    def test_falls_back_to_default_state_without_unstarted(self, template, states, create_user):
        State.objects.filter(pk=states["todo"].pk).delete()
        rule = make_rule(template, create_user, FIRST)
        run(FIRST)
        assert copies(rule).get().state_id == states["backlog"].id

    @pytest.mark.django_db
    def test_one_broken_rule_does_not_stop_others(self, template, create_user, project, workspace, states):
        other = Issue.objects.create(name="Other", project=project, workspace=workspace, created_by=create_user)
        broken = make_rule(other, create_user, FIRST, frequency="weekly", weekdays=[])  # never matches → ValueError
        good = make_rule(template, create_user, FIRST)
        assert run(FIRST) == 1
        assert copies(good).count() == 1
        assert not copies(broken).exists()
```

- [ ] **Step 2: Run to verify failure**

Run: `… pytest plane/tests/contract/app/test_issue_recurrence_app.py -q`
Expected: `ModuleNotFoundError: No module named 'plane.bgtasks.recurrence_task'`.

- [ ] **Step 3: Implement**

`apps/api/plane/bgtasks/recurrence_task.py`:

```python
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
    return template.created_by_id


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

    issue_activity.delay(
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
    return copy


def is_live(template):
    return template.deleted_at is None and template.archived_at is None and template.project.archived_at is None


def run_rule(rule_id, now):
    """Create the due copy for one rule. Returns 1 if a copy was created, else 0."""
    with transaction.atomic():
        rule = (
            IssueRecurrence.objects.select_for_update(skip_locked=True)
            .select_related("issue", "project")
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
```

Add to `app.conf.beat_schedule` in `apps/api/plane/celery.py`, right after the `stack_email_notification` entry:

```python
    "create-due-recurring-issues": {
        "task": "plane.bgtasks.recurrence_task.create_due_recurring_issues",
        "schedule": crontab(minute="*/15"),  # Aight fork: recurring stories
    },
```

Check that `plane/celery.py`'s `app.autodiscover_tasks()` (or the `imports` list) picks up `plane.bgtasks.recurrence_task`; if tasks are listed explicitly in `CELERY_IMPORTS` in `plane/settings/common.py`, add `"plane.bgtasks.recurrence_task"` there.

- [ ] **Step 4: Run to verify pass**

Run: `… pytest plane/tests/contract/app/test_issue_recurrence_app.py -q`
Expected: `15 passed`. If `test_deleted_template_deactivates` fails because `rule.issue` resolves through the soft-delete manager, keep the `Issue.all_objects.get(...)` lookup (already used above) and make sure nothing else dereferences `rule.issue` before `is_live()`.

- [ ] **Step 5: Commit**

```bash
git add apps/api/plane/bgtasks/recurrence_task.py apps/api/plane/celery.py apps/api/plane/settings/common.py apps/api/plane/tests/contract/app/test_issue_recurrence_app.py
git commit -m "feat(api): beat task creates due recurring story copies

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Recurrence API and detail payload

**Files:**

- Create: `apps/api/plane/app/serializers/recurrence.py`
- Modify: `apps/api/plane/app/serializers/__init__.py` (export), `apps/api/plane/app/serializers/issue.py` (`IssueDetailSerializer`)
- Create: `apps/api/plane/app/views/issue/recurrence.py`
- Modify: `apps/api/plane/app/urls/issue.py` (route)
- Test: append to `apps/api/plane/tests/contract/app/test_issue_recurrence_app.py`

**Interfaces:**

- Consumes: `next_occurrence` (Task 1); models (Task 2)
- Produces (HTTP, used by Task 5):
  - `GET    /api/workspaces/<slug>/projects/<project_id>/issues/<issue_id>/recurrence/` → 200 `TIssueRecurrence` | 404
  - `PUT    …/recurrence/` body `{frequency, weekdays?, day_of_month?}` → 200 `TIssueRecurrence`
  - `DELETE …/recurrence/` → 204
  - `TIssueRecurrence` JSON = `{"frequency": str, "weekdays": int[], "day_of_month": int|null, "next_run_at": iso str, "is_active": bool}`
  - Issue detail (`GET …/issues/<id>/`) gains `"recurrence": TIssueRecurrence | null`.

- [ ] **Step 1: Write the failing tests** (append)

```python
@pytest.mark.contract
class TestRecurrenceApi:
    def url(self, workspace, project, issue):
        return f"/api/workspaces/{workspace.slug}/projects/{project.id}/issues/{issue.id}/recurrence/"

    @pytest.mark.django_db
    def test_get_without_rule_is_404(self, session_client, workspace, project, template):
        assert session_client.get(self.url(workspace, project, template)).status_code == status.HTTP_404_NOT_FOUND

    @pytest.mark.django_db
    def test_put_weekly_then_get(self, session_client, workspace, project, template, create_user):
        response = session_client.put(
            self.url(workspace, project, template), {"frequency": "weekly", "weekdays": [4, 0]}, format="json"
        )
        assert response.status_code == status.HTTP_200_OK, response.data
        assert response.data["frequency"] == "weekly"
        assert response.data["weekdays"] == [0, 4]
        assert response.data["day_of_month"] is None
        assert response.data["is_active"] is True
        rule = IssueRecurrence.objects.get(issue=template)
        assert rule.actor_id == create_user.id
        assert rule.next_run_at > timezone.now()
        assert session_client.get(self.url(workspace, project, template)).data["frequency"] == "weekly"

    @pytest.mark.django_db
    def test_put_replaces_existing_rule(self, session_client, workspace, project, template):
        url = self.url(workspace, project, template)
        session_client.put(url, {"frequency": "daily"}, format="json")
        response = session_client.put(url, {"frequency": "monthly", "day_of_month": 31}, format="json")
        assert response.status_code == status.HTTP_200_OK, response.data
        assert IssueRecurrence.objects.filter(issue=template).count() == 1
        assert IssueRecurrence.objects.get(issue=template).day_of_month == 31

    @pytest.mark.django_db
    def test_delete_then_set_again(self, session_client, workspace, project, template):
        url = self.url(workspace, project, template)
        session_client.put(url, {"frequency": "daily"}, format="json")
        assert session_client.delete(url).status_code == status.HTTP_204_NO_CONTENT
        assert session_client.get(url).status_code == status.HTTP_404_NOT_FOUND
        assert session_client.put(url, {"frequency": "weekdays"}, format="json").status_code == status.HTTP_200_OK

    @pytest.mark.django_db
    @pytest.mark.parametrize(
        "body",
        [
            {"frequency": "hourly"},
            {"frequency": "weekly"},
            {"frequency": "weekly", "weekdays": []},
            {"frequency": "weekly", "weekdays": [7]},
            {"frequency": "monthly"},
            {"frequency": "monthly", "day_of_month": 0},
            {"frequency": "monthly", "day_of_month": 32},
            {"frequency": "daily", "weekdays": [1]},
            {"frequency": "weekdays", "day_of_month": 3},
        ],
    )
    def test_invalid_bodies_are_400(self, session_client, workspace, project, template, body):
        response = session_client.put(self.url(workspace, project, template), body, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert not IssueRecurrence.objects.filter(issue=template).exists()

    @pytest.mark.django_db
    def test_guest_cannot_set(self, api_client, workspace, project, template):
        guest = User.objects.create(email="guest@plane.so", username="guest")
        WorkspaceMember.objects.create(workspace=workspace, member=guest, role=5)
        ProjectMember.objects.create(project=project, member=guest, role=5, is_active=True)
        api_client.force_authenticate(user=guest)
        response = api_client.put(self.url(workspace, project, template), {"frequency": "daily"}, format="json")
        assert response.status_code == status.HTTP_403_FORBIDDEN

    @pytest.mark.django_db
    def test_issue_detail_includes_recurrence(self, session_client, workspace, project, template):
        detail = f"/api/workspaces/{workspace.slug}/projects/{project.id}/issues/{template.id}/"
        assert session_client.get(detail).data["recurrence"] is None
        session_client.put(self.url(workspace, project, template), {"frequency": "daily"}, format="json")
        assert session_client.get(detail).data["recurrence"]["frequency"] == "daily"
```

(Check `api_client`/`force_authenticate` matches how `session_client` is built in `plane/tests/conftest.py`; if `session_client` uses `force_authenticate`, the guest test above is correct as written.)

- [ ] **Step 2: Run to verify failure**

Run: `… pytest plane/tests/contract/app/test_issue_recurrence_app.py -q -k Api`
Expected: 404s on PUT (route missing) → assertion failures.

- [ ] **Step 3: Implement the serializer**

`apps/api/plane/app/serializers/recurrence.py`:

```python
# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from rest_framework import serializers

from plane.db.models import IssueRecurrence
from plane.utils.recurrence import FREQUENCIES


class IssueRecurrenceSerializer(serializers.ModelSerializer):
    frequency = serializers.ChoiceField(choices=FREQUENCIES)
    weekdays = serializers.ListField(
        child=serializers.IntegerField(min_value=0, max_value=6), required=False, default=list
    )
    day_of_month = serializers.IntegerField(min_value=1, max_value=31, required=False, allow_null=True, default=None)

    class Meta:
        model = IssueRecurrence
        fields = ["frequency", "weekdays", "day_of_month", "next_run_at", "is_active"]
        read_only_fields = ["next_run_at", "is_active"]

    def validate(self, attrs):
        frequency = attrs["frequency"]
        weekdays = sorted(set(attrs.get("weekdays") or []))
        day_of_month = attrs.get("day_of_month")
        if frequency == "weekly" and not weekdays:
            raise serializers.ValidationError({"weekdays": "Pick at least one day."})
        if frequency != "weekly" and weekdays:
            raise serializers.ValidationError({"weekdays": "Only weekly repeats take days."})
        if frequency == "monthly" and day_of_month is None:
            raise serializers.ValidationError({"day_of_month": "Pick a day of the month."})
        if frequency != "monthly" and day_of_month is not None:
            raise serializers.ValidationError({"day_of_month": "Only monthly repeats take a day of the month."})
        attrs["weekdays"] = weekdays
        return attrs
```

Export in `apps/api/plane/app/serializers/__init__.py` (append):

```python
from .recurrence import IssueRecurrenceSerializer
```

In `apps/api/plane/app/serializers/issue.py`, `IssueDetailSerializer`: add the field, the method, and `"recurrence"` to `Meta.fields`:

```python
    recurrence = serializers.SerializerMethodField()

    def get_recurrence(self, obj):
        # Aight fork: recurring stories
        from .recurrence import IssueRecurrenceSerializer

        rule = obj.recurrences.filter(is_active=True).first()
        return IssueRecurrenceSerializer(rule).data if rule else None
```

```python
        fields = IssueSerializer.Meta.fields + [
            "description_html",
            "is_subscribed",
            "is_intake",
            "type_id",
            "is_epic",
            "recurrence",
        ]
```

(The local import avoids a circular import between `issue.py` and `recurrence.py`; if `__init__` ordering makes a top-level import safe, prefer that.)

- [ ] **Step 4: Implement the view and route**

`apps/api/plane/app/views/issue/recurrence.py`:

```python
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
```

In `apps/api/plane/app/urls/issue.py`: import `from plane.app.views.issue.recurrence import IssueRecurrenceEndpoint` (match how the file imports other views — if it imports from `plane.app.views`, export the class from `plane/app/views/__init__.py` too) and add to `urlpatterns` next to the `issue-subscribers` routes:

```python
    path(
        "workspaces/<str:slug>/projects/<uuid:project_id>/issues/<uuid:issue_id>/recurrence/",
        IssueRecurrenceEndpoint.as_view(),
        name="project-issue-recurrence",
    ),
```

The epic route rewriter (`app/urls/epic.py`, generic `issues/` → `epics/`) mirrors this under `/epics/` automatically.

- [ ] **Step 5: Run to verify pass**

Run: `… pytest plane/tests/contract/app/test_issue_recurrence_app.py -q`
Expected: all pass (4 model + 11 generator + 15 API incl. 9 parametrised = 30).

- [ ] **Step 6: Run the full contract + unit suites for regressions**

Run: `… pytest plane/tests/contract plane/tests/unit -q`
Expected: everything passes except the known flaky `test_sprint_capacity_api.py` 429s (rate limit shared across the run; pass in isolation — confirm with `… pytest plane/tests/contract/api/test_sprint_capacity_api.py -q`).

- [ ] **Step 7: Commit**

```bash
git add apps/api/plane/app/serializers/recurrence.py apps/api/plane/app/serializers/__init__.py apps/api/plane/app/serializers/issue.py apps/api/plane/app/views/issue/recurrence.py apps/api/plane/app/views/__init__.py apps/api/plane/app/urls/issue.py apps/api/plane/tests/contract/app/test_issue_recurrence_app.py
git commit -m "feat(api): recurrence endpoint and issue detail field

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Web "Repeats" property

**Files:**

- Modify: `packages/types/src/issues/issue.ts`
- Create: `apps/web/core/services/issue/issue_recurrence.service.ts`
- Create: `apps/web/core/components/issues/recurrence/summary.ts`
- Create: `apps/web/core/components/issues/recurrence/property.tsx`
- Create: `apps/web/core/components/issues/recurrence/index.ts`
- Modify: `apps/web/core/components/issues/issue-detail/sidebar.tsx` (after the Due date item, ~line 182)
- Modify: `apps/web/core/components/issues/peek-overview/properties.tsx` (after the Due date item, ~line 184)
- Modify: `packages/i18n/src/locales/*/work-item.json` (19 files)

**Interfaces:**

- Consumes: HTTP API from Task 4.
- Produces:
  - types `TIssueRecurrenceFrequency = "daily" | "weekdays" | "weekly" | "monthly"`, `TIssueRecurrencePayload = { frequency; weekdays?: number[]; day_of_month?: number | null }`, `TIssueRecurrence = TIssueRecurrencePayload & { weekdays: number[]; day_of_month: number | null; next_run_at: string; is_active: boolean }`, and `TIssue.recurrence?: TIssueRecurrence | null`
  - `IssueRecurrenceService.set(ws, projectId, issueId, payload) / .remove(ws, projectId, issueId)`
  - `<IssueRecurrenceProperty workspaceSlug projectId issueId disabled />`

- [ ] **Step 1: Types** — in `packages/types/src/issues/issue.ts`, above the `TIssue` type add:

```ts
// Aight fork: recurring stories
export type TIssueRecurrenceFrequency = "daily" | "weekdays" | "weekly" | "monthly";

export type TIssueRecurrencePayload = {
  frequency: TIssueRecurrenceFrequency;
  weekdays?: number[];
  day_of_month?: number | null;
};

export type TIssueRecurrence = TIssueRecurrencePayload & {
  weekdays: number[];
  day_of_month: number | null;
  next_run_at: string;
  is_active: boolean;
};
```

and inside `TIssue`, next to `is_subscribed?: boolean;`:

```ts
  recurrence?: TIssueRecurrence | null;
```

- [ ] **Step 2: Service** — `apps/web/core/services/issue/issue_recurrence.service.ts`:

```ts
/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { API_BASE_URL } from "@plane/constants";
import type { TIssueRecurrence, TIssueRecurrencePayload } from "@plane/types";
// services
import { APIService } from "@/services/api.service";

export class IssueRecurrenceService extends APIService {
  constructor() {
    super(API_BASE_URL);
  }

  private url(workspaceSlug: string, projectId: string, issueId: string) {
    return `/api/workspaces/${workspaceSlug}/projects/${projectId}/issues/${issueId}/recurrence/`;
  }

  async set(
    workspaceSlug: string,
    projectId: string,
    issueId: string,
    data: TIssueRecurrencePayload
  ): Promise<TIssueRecurrence> {
    return this.put(this.url(workspaceSlug, projectId, issueId), data)
      .then((response) => response?.data)
      .catch((error) => {
        throw error?.response?.data;
      });
  }

  async remove(workspaceSlug: string, projectId: string, issueId: string): Promise<void> {
    return this.delete(this.url(workspaceSlug, projectId, issueId))
      .then(() => undefined)
      .catch((error) => {
        throw error?.response?.data;
      });
  }
}
```

(Confirm `APIService` exposes `put` and `delete` — `grep -n "put(\|delete(" apps/web/core/services/api.service.ts`.)

- [ ] **Step 3: i18n keys** — add a top-level `"recurrence"` object to every `packages/i18n/src/locales/<locale>/work-item.json` (English text in all locales, as the Momentum PR did). Run from repo root:

```bash
python3 - <<'EOF'
import json, pathlib
keys = {
    "label": "Repeats",
    "none": "Doesn't repeat",
    "daily": "Daily",
    "weekdays": "Weekdays",
    "weekly": "Weekly",
    "monthly": "Monthly",
    "weekly_on": "Weekly on {days}",
    "monthly_on": "Monthly on day {day}",
    "day_of_month": "Day of month",
    "next": "Next: {date}",
    "days": {"0": "Mon", "1": "Tue", "2": "Wed", "3": "Thu", "4": "Fri", "5": "Sat", "6": "Sun"},
    "update_error": "Couldn't update the repeat. Try again.",
}
for path in sorted(pathlib.Path("packages/i18n/src/locales").glob("*/work-item.json")):
    data = json.loads(path.read_text())
    data["recurrence"] = keys
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    print("updated", path)
EOF
pnpm exec oxfmt packages/i18n/src/locales/*/work-item.json
```

Expected: 19 files updated. `git diff --stat packages/i18n` shows only additions.

- [ ] **Step 4: Summary helper** — `apps/web/core/components/issues/recurrence/summary.ts`:

```ts
/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import type { TIssueRecurrence } from "@plane/types";

type TTranslate = (key: string, params?: Record<string, string | number>) => string;

export const WEEKDAYS = [0, 1, 2, 3, 4, 5, 6];

export const getRecurrenceSummary = (t: TTranslate, recurrence: TIssueRecurrence | null | undefined): string => {
  if (!recurrence) return t("recurrence.none");
  if (recurrence.frequency === "weekly") {
    const days = [...recurrence.weekdays]
      .sort((a, b) => a - b)
      .map((day) => t(`recurrence.days.${day}`))
      .join(", ");
    return t("recurrence.weekly_on", { days });
  }
  if (recurrence.frequency === "monthly") return t("recurrence.monthly_on", { day: recurrence.day_of_month ?? 1 });
  return t(`recurrence.${recurrence.frequency}`);
};

export const getNextRunLabel = (t: TTranslate, recurrence: TIssueRecurrence): string => {
  const date = new Date(recurrence.next_run_at).toLocaleDateString(undefined, {
    weekday: "short",
    day: "numeric",
    month: "short",
  });
  return t("recurrence.next", { date });
};
```

(Check the `t` signature from `useTranslation()` in `packages/i18n` and adjust `TTranslate` if it differs.)

- [ ] **Step 5: Property component** — `apps/web/core/components/issues/recurrence/property.tsx`:

```tsx
/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useContext, useState } from "react";
import { observer } from "mobx-react";
import { Popover } from "@headlessui/react";
import { EUserPermissionsLevel } from "@plane/constants";
import { useTranslation } from "@plane/i18n";
import { setToast, TOAST_TYPE } from "@plane/propel/toast";
import type { TIssueRecurrenceFrequency, TIssueRecurrencePayload } from "@plane/types";
import { EUserPermissions } from "@plane/types";
import { cn } from "@plane/utils";
// hooks
import { useUser } from "@/hooks/store/user";
import { StoreContext } from "@/lib/store-context";
// services
import { IssueRecurrenceService } from "@/services/issue/issue_recurrence.service";
// local imports
import { getNextRunLabel, getRecurrenceSummary, WEEKDAYS } from "./summary";

const recurrenceService = new IssueRecurrenceService();
const FREQUENCIES: (TIssueRecurrenceFrequency | null)[] = [null, "daily", "weekdays", "weekly", "monthly"];
const DAYS_OF_MONTH = Array.from({ length: 31 }, (_, i) => i + 1);

type Props = {
  workspaceSlug: string;
  projectId: string;
  issueId: string;
  disabled?: boolean;
};

export const IssueRecurrenceProperty = observer(function IssueRecurrenceProperty(props: Props) {
  const { workspaceSlug, projectId, issueId, disabled = false } = props;
  const { t } = useTranslation();
  const store = useContext(StoreContext);
  const {
    permission: { allowPermissions },
  } = useUser();
  const [isSaving, setIsSaving] = useState(false);

  const issue = store.issue.issues.getIssueById(issueId);
  const recurrence = issue?.recurrence ?? null;
  const canEdit =
    !disabled &&
    allowPermissions(
      [EUserPermissions.ADMIN, EUserPermissions.MEMBER],
      EUserPermissionsLevel.PROJECT,
      workspaceSlug,
      projectId
    );

  const save = async (payload: TIssueRecurrencePayload | null) => {
    setIsSaving(true);
    try {
      if (payload) {
        const next = await recurrenceService.set(workspaceSlug, projectId, issueId, payload);
        store.issue.issues.updateIssue(issueId, { recurrence: next });
      } else {
        await recurrenceService.remove(workspaceSlug, projectId, issueId);
        store.issue.issues.updateIssue(issueId, { recurrence: null });
      }
    } catch {
      setToast({ type: TOAST_TYPE.ERROR, title: t("toast.error"), message: t("recurrence.update_error") });
    } finally {
      setIsSaving(false);
    }
  };

  const selectFrequency = (frequency: TIssueRecurrenceFrequency | null) => {
    if (frequency === null) return void save(null);
    if (frequency === "weekly") {
      // default to today's weekday (Mon = 0)
      const today = (new Date().getDay() + 6) % 7;
      return void save({ frequency, weekdays: recurrence?.weekdays?.length ? recurrence.weekdays : [today] });
    }
    if (frequency === "monthly")
      return void save({ frequency, day_of_month: recurrence?.day_of_month ?? new Date().getDate() });
    return void save({ frequency });
  };

  const toggleWeekday = (day: number) => {
    if (!recurrence) return;
    const weekdays = recurrence.weekdays.includes(day)
      ? recurrence.weekdays.filter((d) => d !== day)
      : [...recurrence.weekdays, day];
    if (weekdays.length === 0) return; // weekly needs at least one day
    void save({ frequency: "weekly", weekdays });
  };

  const summaryLabel = getRecurrenceSummary(t, recurrence);

  if (!canEdit)
    return <span className={cn("px-2 text-body-xs-regular", { "text-placeholder": !recurrence })}>{summaryLabel}</span>;

  return (
    <Popover className="relative w-full">
      <Popover.Button
        type="button"
        disabled={isSaving}
        className={cn("h-7.5 w-full rounded-sm px-2 text-left text-body-xs-regular hover:bg-layer-1", {
          "text-placeholder": !recurrence,
        })}
      >
        {summaryLabel}
      </Popover.Button>
      <Popover.Panel className="absolute left-0 z-20 mt-1 w-56 rounded-md border border-subtle bg-surface-1 p-2 shadow-raised-200">
        <div className="flex flex-col gap-0.5">
          {FREQUENCIES.map((frequency) => {
            const isActive = (recurrence?.frequency ?? null) === frequency;
            return (
              <button
                key={frequency ?? "none"}
                type="button"
                disabled={isSaving}
                onClick={() => selectFrequency(frequency)}
                className={cn("rounded-sm px-2 py-1 text-left text-body-xs-regular hover:bg-layer-1", {
                  "bg-layer-2 text-primary": isActive,
                })}
              >
                {t(frequency ? `recurrence.${frequency}` : "recurrence.none")}
              </button>
            );
          })}
        </div>
        {recurrence?.frequency === "weekly" && (
          <div className="mt-2 flex gap-0.5 border-t border-subtle pt-2">
            {WEEKDAYS.map((day) => (
              <button
                key={day}
                type="button"
                disabled={isSaving}
                onClick={() => toggleWeekday(day)}
                className={cn("flex-1 rounded-sm py-1 text-11 font-medium", {
                  "bg-layer-2 text-primary": recurrence.weekdays.includes(day),
                  "text-tertiary hover:text-primary": !recurrence.weekdays.includes(day),
                })}
              >
                {t(`recurrence.days.${day}`)}
              </button>
            ))}
          </div>
        )}
        {recurrence?.frequency === "monthly" && (
          <label className="mt-2 flex items-center justify-between gap-2 border-t border-subtle pt-2 text-body-xs-regular">
            {t("recurrence.day_of_month")}
            <select
              value={recurrence.day_of_month ?? 1}
              disabled={isSaving}
              onChange={(e) => void save({ frequency: "monthly", day_of_month: Number(e.target.value) })}
              className="rounded-sm border border-subtle bg-surface-1 px-1 py-0.5"
            >
              {DAYS_OF_MONTH.map((day) => (
                <option key={day} value={day}>
                  {day}
                </option>
              ))}
            </select>
          </label>
        )}
        {recurrence && <p className="mt-2 px-2 text-11 text-tertiary">{getNextRunLabel(t, recurrence)}</p>}
      </Popover.Panel>
    </Popover>
  );
});
```

`apps/web/core/components/issues/recurrence/index.ts`:

```ts
/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

export * from "./property";
```

(Class names: copy the token names actually used in `components/dropdowns/` panels — e.g. grep `shadow-raised` and `bg-surface-1` there — and swap any that don't exist in this Tailwind config.)

- [ ] **Step 6: Mount it** — in both `issue-detail/sidebar.tsx` (after the Due date `</SidebarPropertyListItem>` at ~line 182) and `peek-overview/properties.tsx` (~line 184), insert:

```tsx
<SidebarPropertyListItem icon={Repeat} label={t("recurrence.label")}>
  <IssueRecurrenceProperty
    workspaceSlug={workspaceSlug}
    projectId={projectId}
    issueId={issueId}
    disabled={!isEditable || !!issue.archived_at}
  />
</SidebarPropertyListItem>
```

In `peek-overview/properties.tsx` use that file's own edit flag (`disabled={disabled || !!issue.archived_at}`) and its own `workspaceSlug`/`projectId`/`issueId` variables. Add imports in both files:

```tsx
import { Repeat } from "lucide-react";
import { IssueRecurrenceProperty } from "@/components/issues/recurrence";
```

(`SidebarPropertyListItem.icon` is `React.FC<{ className?: string }>`; lucide icons satisfy it.)

- [ ] **Step 7: Make sure the detail fetch keeps `recurrence` in the store** — open `apps/web/core/store/issue/issue.store.ts` `addIssue`/`updateIssue` and the detail fetch in `store/issue/issue-details/issue.store.ts`. If incoming issue objects are picked/whitelisted by key, add `"recurrence"` to that list. If they are stored whole, no change.

- [ ] **Step 8: Typecheck and lint**

Run: `cd ~/dev/plane && pnpm turbo run check:types --filter=web && pnpm exec oxlint --deny-warnings apps/web/core/components/issues/recurrence apps/web/core/services/issue/issue_recurrence.service.ts`
Expected: `Tasks: N successful`, `Found 0 warnings and 0 errors`.

- [ ] **Step 9: Commit**

```bash
git add packages/types/src/issues/issue.ts apps/web/core/services/issue/issue_recurrence.service.ts apps/web/core/components/issues/recurrence apps/web/core/components/issues/issue-detail/sidebar.tsx apps/web/core/components/issues/peek-overview/properties.tsx packages/i18n/src/locales
git commit -m "feat(web): Repeats property on stories

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

If the hook rejects pre-existing warnings in `sidebar.tsx`/`properties.tsx`, add file-level `// oxlint-disable <rule>` lines above the license header for exactly the reported rules (fork convention), re-stage, and commit again.

---

### Task 6: Browser check, PR

**Files:** none new.

- [ ] **Step 1: Run the app locally** — `cd ~/dev/plane && ./setup.sh` (if env files are missing) then `docker compose -f docker-compose-local.yml up -d` and `pnpm dev`. Sign up / log in at `http://localhost:3000`, create a workspace + project.
      If the local stack can't run on macmini1 (RAM/time), stop here and do this step on prod right after Task 7's deploy instead, with a throwaway story that is deleted afterwards — say so in the hand-off.

- [ ] **Step 2: Click through** (Playwright MCP or Chrome): open a story → sidebar shows "Repeats: Doesn't repeat" → pick Weekly → Mon–Sun toggles appear with today selected and "Next: …" → toggle Fri on and today off → summary reads "Weekly on Fri" → switch to Monthly, pick 31 → "Monthly on day 31" → "Doesn't repeat" clears it → reload: state persists. Repeat in the peek view. Take a screenshot of the open popover and view it.

- [ ] **Step 3: Generator smoke** — set a story to Daily, then in the API container: `python manage.py shell -c "from plane.db.models import IssueRecurrence as R; from django.utils import timezone as tz; R.objects.update(next_run_at=tz.now()); from plane.bgtasks.recurrence_task import create_due_recurring_issues as f; print(f())"` → prints `1`; the copy appears in the list in Todo with today's due date, the comment links back.

- [ ] **Step 4: Push and open the PR**

```bash
git push -u origin feat/recurring-stories
gh pr create --repo g0rdonL/plane --base aight/epics --head feat/recurring-stories --title "feat: recurring stories" --body "<summary of tasks 1–5, test counts, browser check result>

🤖 Generated with [Claude Code](https://claude.com/claude-code)"
```

---

### Task 7: Deploy and cut over (after Gordon merges)

- [ ] **Step 1: Deploy to lh-plane** (same flow as #16):

```bash
ssh ubuntu@43.160.247.31 'set -e
cd ~/code/plane-fork && git pull -q --ff-only origin aight/epics && git log --oneline -1
docker tag aight/plane-backend:v1.4.2-epics aight/plane-backend:pre-recurring
docker tag aight/plane-frontend:v1.4.2-epics aight/plane-frontend:pre-recurring
docker build -f apps/api/Dockerfile.api -t aight/plane-backend:v1.4.2-epics apps/api > ~/backend-build.log 2>&1
docker build -f apps/web/Dockerfile.web -t aight/plane-frontend:v1.4.2-epics . > ~/build-recurring.log 2>&1
cd ~/plane-selfhost/plane-app && sudo docker compose --env-file plane.env up -d migrator api worker beat-worker web'
```

Then wait for `https://plane.aight.to/api/instances/` → 200, confirm `docker logs plane-app-migrator-1` shows `Applying db.0123_issuerecurrence_issuerecurrencerun... OK`, and `docker logs plane-app-beat-worker-1 | grep create-due-recurring` shows the schedule loaded.

- [ ] **Step 2: Move Gordon's two routines** — create two template stories in AIGHT via the v1 API ("Weekly sprint review", "Monthly infrastructure check", descriptions from `/opt/skills/plane-recurring/recurring.json`), then in the lh-plane API container create their rules (actor = Gordon's user) with `IssueRecurrence.objects.create(issue=…, project=…, frequency="weekly", weekdays=[4], next_run_at=next_occurrence(...), actor=…)` and `frequency="monthly", day_of_month=1`. Confirm both show "Repeats" in the UI.

- [ ] **Step 3: Retire the script** (macmini1):

```bash
launchctl bootout gui/$(id -u)/com.gordon.plane-recurring
```

Prepend to `/opt/skills/plane-recurring/README.md`: `> **Retired 2026-10-xx** — recurring stories are native in the Plane fork (g0rdonL/plane#<PR>). Set "Repeats" on a story. This script and its launchd job are no longer used.` Commit in `/opt/skills` and push.

- [ ] **Step 4: Rewrite HROPS-119** via v1 API `PATCH` `description_html`: open any HROPS story → "Repeats" in the sidebar → pick a schedule; the copy appears at 08:00 Bangkok on the due day in Todo with that day as due date; check fields and leave feedback in a comment. Keep assignee Minh Chau.
