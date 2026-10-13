# Recurring stories — design

Aight fork, `aight/epics`. Replaces the external `plane-recurring` script (`/opt/skills/plane-recurring`, launchd on
macmini1, config in `recurring.json`) with a native Plane feature.

## Goal

Anyone who can edit a story can make it repeat from the story itself ("Repeats: weekly on Fri"). On each due day
Plane creates a fresh copy of that story. No JSON, no external process.

Success: Minh Chau sets up an HR/Ops routine in HROPS on her own, and the copy appears on the right day with the
right fields; Gordon's two existing AIGHT routines run natively and the script is retired.

## Decisions

| Question                        | Decision                                                                                                |
| ------------------------------- | ------------------------------------------------------------------------------------------------------- |
| Where is repetition configured? | On the story itself (sidebar "Repeats" property). That story is the **template**.                       |
| What triggers a copy?           | A fixed schedule — not completion of the previous copy.                                                 |
| Schedule kinds                  | Daily · Weekdays (Mon–Fri) · Weekly on chosen weekdays · Monthly on day N (1–31, clamped to month end). |
| Time of day                     | 08:00 in the project's timezone (all prod projects are `Asia/Bangkok`). Not user-configurable.          |
| Copy state                      | The project's first `unstarted`-group state (Todo); falls back to the project default state.            |
| Copy due date                   | `target_date` = the occurrence date. `start_date` left empty.                                           |
| Copy sprint                     | Not added to any cycle.                                                                                 |
| Missed runs                     | One copy for the most recent missed occurrence only; no backlog of copies.                              |
| Who can set it                  | Project admins and members (role ≥ 15). Guests cannot.                                                  |

## Data model

New file `apps/api/plane/db/models/recurrence.py`, both models `ProjectBaseModel` (workspace, project, audit fields,
soft delete).

**`IssueRecurrence`** — the rule, one per template story.

| Field          | Type                                                                 | Notes                                                    |
| -------------- | -------------------------------------------------------------------- | -------------------------------------------------------- |
| `issue`        | `OneToOneField(Issue, related_name="recurrence", on_delete=CASCADE)` | the template                                             |
| `frequency`    | `CharField` choices `daily`, `weekdays`, `weekly`, `monthly`         |                                                          |
| `weekdays`     | `ArrayField(SmallIntegerField)`, default `[]`                        | `weekly` only; 0 = Mon … 6 = Sun, ≥ 1 entry              |
| `day_of_month` | `SmallIntegerField(null=True)`                                       | `monthly` only; 1–31                                     |
| `next_run_at`  | `DateTimeField(db_index=True)`                                       | UTC instant of the next occurrence (08:00 project-local) |
| `last_run_at`  | `DateTimeField(null=True)`                                           |                                                          |
| `is_active`    | `BooleanField(default=True)`                                         |                                                          |
| `actor`        | `ForeignKey(User, on_delete=SET_NULL, null=True)`                    | who set it; copies are created as this user              |

**`IssueRecurrenceRun`** — one row per occurrence; idempotency and the copy ↔ template link.

| Field             | Type                                                                               | Notes              |
| ----------------- | ---------------------------------------------------------------------------------- | ------------------ |
| `recurrence`      | `ForeignKey(IssueRecurrence, related_name="runs", on_delete=CASCADE)`              |                    |
| `occurrence_date` | `DateField`                                                                        | project-local date |
| `issue`           | `ForeignKey(Issue, related_name="recurrence_runs", on_delete=SET_NULL, null=True)` | the copy           |

Unique constraint `(recurrence, occurrence_date)` where `deleted_at IS NULL`.

One migration, `0123_issuerecurrence_issuerecurrencerun`. No change to the `issues` table.

## Schedule computation

Pure function in `apps/api/plane/utils/recurrence.py`:

```python
def next_occurrence(rule, after: datetime, tz: ZoneInfo) -> datetime  # UTC
```

Returns the first 08:00 project-local instant strictly after `after` that matches the rule. Monthly day 31 in a
30-day month (or 29–31 in February) fires on the last day of that month. Unit-tested without the database.

`next_run_at` is computed on create/update of the rule (from "now") and after each run (from the occurrence that
just ran).

## Generator

Celery task `plane.bgtasks.recurrence_task.create_due_recurring_issues`, added to `beat_schedule` in
`plane/celery.py` at `crontab(minute="*/15")`. Runs in the existing `beat-worker` container.

For each active rule with `next_run_at <= now`, inside `transaction.atomic()` with `select_for_update(skip_locked=True)`:

1. If the template is archived, deleted, or its project is archived → set `is_active=False`, stop.
2. Collapse missed runs: the occurrence to create is the **latest** occurrence `<= now`.
3. `get_or_create` the `IssueRecurrenceRun` for that `occurrence_date`. If it already existed, skip creation
   (retry safety).
4. Create the copy (below), link it on the run row.
5. `last_run_at = occurrence`, `next_run_at = next_occurrence(rule, occurrence, tz)`.

One failing rule is logged and skipped; it does not stop the others.

### The copy

Copied from the template: `name`, `description_html` (+ `description_json`/`description_binary`/`description_stripped`),
`priority`, `estimate_point`, `parent`, `type` (if set), labels, the assignee (single — see #16), modules.

Not copied: state (→ Todo, see Decisions), `start_date`, `target_date` (→ occurrence date), cycle, sub-issues,
attachments, links, comments, reactions, subscribers beyond the defaults, `sort_order` (new default).

`created_by` = rule `actor` (falls back to the template's `created_by` if the actor left the project). The copy goes
through the same post-create path as a normal API create: `issue_activity.delay(type="issue.activity.created", …,
notification=True, origin="recurrence")` so the assignee is notified, and an activity comment "Created from
`<IDENT-N>` (repeats <rule summary>)".

The copy itself does not repeat.

## API

App API (session auth, same permission as editing the issue — `ROLE.ADMIN, ROLE.MEMBER`):

```
GET    /api/workspaces/<slug>/projects/<project_id>/issues/<issue_id>/recurrence/
PUT    /api/workspaces/<slug>/projects/<project_id>/issues/<issue_id>/recurrence/
DELETE /api/workspaces/<slug>/projects/<project_id>/issues/<issue_id>/recurrence/
```

- `GET` → `{frequency, weekdays, day_of_month, next_run_at, is_active}` or `404` when not repeating.
- `PUT` body `{frequency, weekdays?, day_of_month?}` → create or replace; recomputes `next_run_at`; returns the rule.
  Validation: `weekly` needs ≥ 1 weekday in 0–6; `monthly` needs `day_of_month` 1–31; other fields must be absent/empty
  for the frequency. Epics and copies-of-copies are allowed (any story can be a template).
- `DELETE` → `204`; soft-deletes the rule (past run rows and copies untouched).

The issue detail payload gains a read-only `recurrence` summary (`null` or the GET shape) so the sidebar renders
without a second request. Public v1 API: out of scope for now.

## Web UI

- **`RecurrenceDropdown`** (`apps/web/core/components/dropdowns/recurrence/`) — button shows "Doesn't repeat" or a
  summary ("Weekly on Fri", "Monthly on the 1st", "Weekdays"); popover with the frequency list, weekday toggles for
  weekly, a 1–31 picker for monthly, and "Next: Fri 17 Oct" under the selection.
- Added as a "Repeats" `SidebarPropertyListItem` in `issues/issue-detail/sidebar.tsx` and
  `issues/peek-overview/properties.tsx`, after Due date. Disabled for guests and archived stories.
- Service `services/issue/issue_recurrence.service.ts`; state lives on the issue store's `recurrence` field, updated
  optimistically on PUT/DELETE.
- Copies: no new UI; the "Created from …" activity entry is the link back.
- i18n keys added in `en` and filled in all locales (English fallback text, as with Momentum).

## Cutover

After deploy to lh-plane:

1. Recreate the two `recurring.json` tasks as repeating template stories in AIGHT (weekly Fri, monthly 1st).
2. Unload `com.gordon.plane-recurring` on macmini1 and move `/opt/skills/plane-recurring` to an archived note in its
   README (script kept in git history).
3. Rewrite HROPS-119 so Minh Chau sets up a repeat herself and checks the first copy.

## Testing

- **Unit** (`tests/unit/utils/test_recurrence.py`): `next_occurrence` for each frequency, week wrap, month-end clamp,
  February, DST-free Bangkok and a DST zone (Europe/London) for correctness.
- **Contract** (`tests/contract/app/test_issue_recurrence_app.py`): PUT/GET/DELETE + validation errors + guest 403;
  generator creates exactly one copy per occurrence (run twice → still one); missed runs collapse to one; archived
  template deactivates; copy fields (Todo state, due date = occurrence, single assignee, labels, no cycle).
- **Web**: `check:types`, and a browser click-through of the Repeats property on the sidebar and peek view before
  hand-off.

## Out of scope

Custom time of day, every-N-weeks intervals, end dates / occurrence counts, completion-triggered repeats, auto-adding
copies to the active sprint, public v1 API endpoints, a project-level list of all repeating stories.
