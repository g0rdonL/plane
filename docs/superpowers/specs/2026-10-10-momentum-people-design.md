# Momentum analytics — People section (addendum to 2026-10-09 spec)

Extends `docs/superpowers/specs/2026-10-09-momentum-analytics-design.md`
(merged as g0rdonL/plane PR #14). Everything in that spec still holds:
definitions, `SPRINT_TZ` import, non-epic filter, cancelled exclusion,
`base_filters` project scoping, response envelopes, test style.

## Problem

The Momentum tab shows team-level velocity, throughput, cycle time and flow,
but nothing per person. Gordon asked for per-person metrics on 2026-10-10.
Raw points per head would be misleading: part-timers run 4+1 and 6+1 point
capacities against 8+2 for full-timers, so the headline per-person numbers
must be normalised against each person's own capacity.

## Decisions (Gordon, 2026-10-10, "go")

1. Headline per-person metrics are **capacity utilisation** and **commitment
   reliability**, both percentages. Raw committed/completed points are shown
   but are supporting columns, not the lead.
2. A story with several assignees credits **every assignee in full**. No
   splitting. This matches how My sprint already counts.
3. Unassigned stories are not dropped: they roll into one final
   **Unassigned** row so data holes stay visible.
4. The window is the last `weeks` **fully elapsed** sprint weeks. The current
   (incomplete) week is excluded, otherwise utilisation is deflated mid-week.

## Scope

One new section, **People**, appended after Cumulative flow on the Momentum
tab. A table, no chart. Honours the project selector. Window selector
4 / 8 / 12 / 26 weeks (default 8), same component as the other sections.

Out of scope: per-person charts, drill-down to the person's stories, export,
changing anyone's capacity from this page, lead time per person.

## Definitions

- **People**: active `WorkspaceMember`s of the workspace with
  `role >= ROLE.MEMBER` and `member__is_bot=False`, exactly as
  `SprintCapacityPeopleEndpoint` in
  `apps/api/plane/app/views/issue/sprint_capacity.py` selects them. Guests are
  excluded. Every such person gets a row even when all their numbers are 0.
- **Assigned**: `IssueAssignee` rows with `deleted_at` null. Each assignee is
  credited the story's full points and count.
- **Capacity**: `get_capacity(user)["planned"]` from `sprint_capacity.py`
  (Profile.goals["sprint_capacity"], default 8). Buffer is ignored. Import
  `get_capacity`; do not redefine. If importing it into
  `plane.app.views.analytic.advance` causes a circular import, move the
  function to `plane/utils/sprint.py` and re-export it from
  `sprint_capacity.py` so the existing import sites keep working.
- **Window**: `weeks` elapsed Bangkok Monday–Sunday weeks ending with the
  week before the current one. Reuse `_week_windows(weeks + 1)` and drop the
  last element, or add a parameter; do not duplicate the week arithmetic.
- **Committed points (person)**: over all stories assigned to the person,
  sum of points of stories that are a member of a cycle whose `end_date`
  falls in a window week, deduplicated per (story, week). Same cycle filters
  as `_velocity_series`. Cancelled and triage excluded.
- **Completed points / count (person)**: stories assigned to the person with
  `state__group == "completed"` and `completed_at` inside the window.
- **Reliability**: `completed_points ÷ committed_points` × 100, 0 decimals,
  `null` when committed is 0. Same definition as the team tile, so it can
  exceed 100 when work outside any sprint completes. Say so in the column
  tooltip.
- **Utilisation**: `completed_points ÷ (capacity × weeks)` × 100, 0 decimals,
  `null` when capacity is 0.
- **Median cycle time**: median over the person's completed-in-window stories
  of the cycle time defined in the base spec (first `started` transition →
  `completed_at`, fallback `created_at`). Reuse `_completed_cycle_lead_times`;
  extend it to return issue ids alongside values rather than re-querying.
  1 decimal, `null` when the person completed nothing.
- **Unassigned row**: `key: "unassigned"`, same columns computed over stories
  with no active assignee; `capacity`, `utilisation` are `null`.

## API

### `GET /api/workspaces/<slug>/advance-analytics-charts/?type=people&weeks=8`

Add `people` to the chart types handled in
`apps/api/plane/app/views/analytic/advance.py`. `weeks` default 8, max 26,
invalid → 400 like the other types. Permission unchanged
(`ROLE.ADMIN, ROLE.MEMBER`, workspace level).

```json
{
  "data": [
    {
      "key": "<user uuid>",
      "name": "Linh",
      "avatar_url": "https://…" ,
      "capacity": 6,
      "committed_points": 31,
      "completed_points": 27,
      "completed_count": 9,
      "reliability": 87,
      "utilisation": 56,
      "median_cycle_time": 2.1
    },
    { "key": "unassigned", "name": "Unassigned", "avatar_url": null,
      "capacity": null, "committed_points": 3, "completed_points": 3,
      "completed_count": 1, "reliability": 100, "utilisation": null,
      "median_cycle_time": 0.5 }
  ],
  "schema": { "committed_points": "Committed", "completed_points": "Completed", "...": "..." }
}
```

`name` is `display_name`, falling back to `first_name last_name`, then email
local part, as the sprint people picker does. Sort rows by `completed_points`
descending, then `name`; `unassigned` always last. Omit the `unassigned` row
when all its values are 0.

Query budget: one query for members + capacities, one for committed rows, one
for completed rows, one for the state activities (cycle time), one for
assignees. No per-person queries.

## Frontend

- `packages/types/src/analytics.ts`: add `"people"` to `TAnalyticsGraphsBase`
  and a `TMomentumPersonRow` type for the row shape above.
- `apps/web/core/components/analytics/momentum/people-table.tsx`: `useSWR`
  keyed on workspace + selected projects + weeks, `AnalyticsSectionWrapper`,
  `ChartLoader`, `EmptyStateCompact`, the existing `WindowSelector`. Render
  with the same table styling as `insight-table/root.tsx`; reuse `InsightTable`
  only if its column API fits without widening `AnalyticsTableDataMap` again,
  otherwise write a plain table with the same classes.
- Columns, in order: Person (avatar + name), Capacity/wk, Committed,
  Completed, Stories, Reliability, Utilisation, Median cycle time.
  Percentages render with a `%` suffix and no decimals; `null` renders as
  `—`. Cycle time renders as `2.1d`.
- Utilisation and reliability cells carry a `title` tooltip with the one-line
  definition. No colour coding, no ranking badges, no bars.
- Append `<PeopleTable />` to `momentum/root.tsx` after the cumulative flow
  section.
- i18n under `workspace_analytics` in `en/workspace.json` and the same keys
  with English values in the other 18 locales: `people`, `person`,
  `capacity_per_week`, `completed_stories`, `utilisation`, `unassigned`,
  `reliability_tooltip`, `utilisation_tooltip`, `people_window_note`
  ("Last {count} elapsed sprint weeks; the current week is excluded").
  Reuse existing `committed_points`, `completed_points`,
  `commitment_reliability`, `median_cycle_time`.

## Tests

`apps/api/plane/tests/contract/app/test_momentum_people_app.py`, same fixture
style as `test_momentum_analytics_app.py`. Cover:

1. Two members with capacities 8 and 4 (second set via Profile.goals): same
   completed points give different `utilisation`; `capacity` echoed per row.
2. A story with two assignees credits both in full (points and count).
3. A completed story with no assignee produces the `unassigned` row; the row
   is absent when there is no unassigned work.
4. A workspace Guest with assigned completed work gets no row; a Member with
   no work still gets a zero row.
5. Cancelled story excluded from committed and completed; a story completed
   in the current (incomplete) week is excluded.
6. `project_ids` filter scopes rows; `weeks=99` and `weeks=0` → 400.
7. `reliability` null when committed is 0; `median_cycle_time` matches a
   known set of cycle times.

Run with the repo's `docker-compose-test.yml` (`COMPOSE_PROJECT_NAME=plane-fork`)
as before; type-check with `pnpm turbo run check:types --filter=web`; lint with
`pnpm turbo run check:lint --filter=web`. `pnpm --filter @plane/i18n check:sync`
is red on `aight/epics` already (`sidebar.my_sprint`); it must not get worse.

## Non-goals and risks

- A per-person table can read as a leaderboard. Utilisation against the
  person's own capacity, not raw points, is the lead metric for that reason.
  Keep the visual flat.
- Capacity is read as it is today, not as it was in past weeks. If someone
  changed their capacity mid-window, old weeks are judged against the new
  number. Acceptable for now; note it in the window tooltip.
