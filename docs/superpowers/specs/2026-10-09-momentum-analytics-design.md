# Momentum analytics — design spec (Aight fork)

Date: 2026-10-09. Target branch: `aight/epics`. Author: Gordon Lee (spec drafted with Claude).

## Problem

Plane CE's workspace Analytics page has two tabs (Overview, Work items) and no
sprint-level momentum reporting: no velocity, throughput, cycle/lead time or
cumulative flow. Those are the Jira board reports the team is used to. The data
already exists in the fork (weekly cycles, story points via estimates,
`completed_at`, state history in `IssueActivity`), so this is a read-only
reporting feature with no migrations.

## Scope

Add a third Analytics tab, **Momentum**, at workspace level, honouring the
existing project selector ("All projects" / multi-select). Four sections:

1. **Velocity** — per sprint week: points committed vs points completed, plus a
   3-sprint rolling average line. Tiles: average velocity (last 3 sprints),
   last sprint completed points, commitment reliability (completed ÷ committed).
2. **Throughput** — stories completed per sprint week (count), bar chart.
   Tile: average throughput (last 3 sprints).
3. **Cycle time & lead time** — for stories completed in the window:
   cycle time = first transition into a `started` state → `completed_at`
   (fallback: `created_at` when no started transition exists);
   lead time = `created_at` → `completed_at`.
   Tiles: median and p85 for both, in days (1 decimal).
   Chart: histogram of cycle time in buckets `≤1d, 2–3d, 4–7d, 8–14d, >14d`.
4. **Cumulative flow** — daily stacked area of open story counts by state
   group (`backlog`, `unstarted`, `started`, `completed`) over the window,
   reconstructed from `IssueActivity` rows with `field="state"`.

Out of scope: per-cycle burndown (already exists on the cycle page), per-user
breakdowns, export, module/epic scoping, saving views.

## Definitions (must match `apps/api/plane/app/views/issue/sprint_capacity.py`)

- **Sprint week**: Monday 00:00 → Sunday 23:59:59 in `Asia/Bangkok`
  (`SPRINT_TZ`). Label as ISO week, e.g. `W42`. Import `SPRINT_TZ` rather than
  redefining it.
- **Story**: `Issue.issue_objects` (excludes drafts/archived/deleted) with
  `type__is_epic` false or `type` null. Epics are never counted.
- **Points**: `estimate_point__value` cast to float; missing → 0.
- **Committed in week W**: story is a member of any cycle (`CycleIssue`,
  `deleted_at` null) whose `end_date` falls inside W. Cancelled stories are
  excluded from committed and completed.
- **Completed in week W**: `state__group == "completed"` and `completed_at`
  inside W. Completed stories not in any cycle still count toward throughput
  and completed points (they were done that week), but not toward committed.
- **Rolling average**: mean of the previous 3 sprint weeks including the
  current one; `null` for the first two weeks.
- **Reliability**: `completed ÷ committed` for the last fully elapsed sprint
  week (not the current one), as a percentage, `null` if committed is 0.

## API

Extend the existing advance-analytics endpoints in
`apps/api/plane/app/views/analytic/advance.py`. Reuse
`self.filters["base_filters"]` for workspace/project scoping, so the
`project_ids` query param works unchanged. Add permission via the existing
`@allow_permission([ROLE.ADMIN, ROLE.MEMBER], level="WORKSPACE")`.

### `GET /api/workspaces/<slug>/advance-analytics/?tab=momentum&weeks=8`

Returns tiles:

```json
{
  "avg_velocity": { "count": 11.3 },
  "last_sprint_velocity": { "count": 9 },
  "commitment_reliability": { "count": 82 },
  "avg_throughput": { "count": 7.7 },
  "median_cycle_time": { "count": 2.4 },
  "p85_cycle_time": { "count": 6.1 },
  "median_lead_time": { "count": 5.0 },
  "p85_lead_time": { "count": 14.2 }
}
```

`count` is the value shown; keep the `{count}` envelope because
`TotalInsights` / `InsightCard` already render that shape. Cycle/lead tiles
use the same `weeks` window.

### `GET /api/workspaces/<slug>/advance-analytics-charts/?type=<type>&weeks=8|days=30`

| type              | params                       | `data` row shape                                                                              |
| ----------------- | ---------------------------- | --------------------------------------------------------------------------------------------- |
| `velocity`        | `weeks` (default 8, max 26)  | `{key: "2026-W42", name: "W42", committed_points, completed_points, rolling_avg}`             |
| `throughput`      | `weeks` (default 12, max 26) | `{key, name, completed_count}`                                                                |
| `cycle-time`      | `weeks` (default 8, max 26)  | `{key: "le_1d", name: "≤1d", count}` ×5 buckets, in order                                     |
| `cumulative-flow` | `days` (default 30, max 90)  | `{key: "2026-10-01", name: "Oct 01", backlog, unstarted, started, completed}` one row per day |

Response envelope matches the existing charts: `{"data": [...], "schema": {...}}`
(`schema` maps series key → label). Weeks with no activity are still emitted
with zeros. The current (incomplete) week is included and is the last row.
Invalid `weeks`/`days` → 400 like the existing `Invalid type` branch.

### Cumulative flow algorithm

For each story in scope created on or before the window end:

1. Load its `IssueActivity` rows where `field == "state"`, ordered by
   `created_at`, with `new_identifier` → `State.group` (one query, joined, for
   all issues; do not query per issue).
2. Initial group = the group of the state at creation. Derive it as the
   `old_identifier` group of the first state activity, or the current
   `state.group` when there are no activities.
3. Walk the days of the window; for each day apply all transitions up to
   23:59:59 Bangkok of that day and increment that day's bucket for the
   story's group. Stories with `created_at` after that day are skipped.
   `cancelled` stories are dropped from the day they were cancelled.

Cap the window at 90 days; at ~600 stories this is a few thousand rows and
runs in Python in well under a second. Do not add a snapshot table.

### Cycle time algorithm

One query over `IssueActivity` (`field="state"`) joined to the new state's
group, filtered to the completed-in-window stories, take `MIN(created_at)`
where `new state group == "started"` per issue. Cycle time days =
`(completed_at − started_at).total_seconds() / 86400`, rounded to 1 decimal
for tiles; bucket boundaries apply to the unrounded value. p85 = linear
interpolation (`statistics.quantiles(n=20)[16]` or equivalent), median =
`statistics.median`.

## Frontend

- `packages/types/src/analytics.ts`: add `"momentum"` to `TAnalyticsTabsBase`
  and `"velocity" | "throughput" | "cycle-time" | "cumulative-flow"` to
  `TAnalyticsGraphsBase`.
- `apps/web/core/components/analytics/tabs.tsx`: append
  `{ key: "momentum", label: t("workspace_analytics.momentum"), content: Momentum }`.
- `packages/constants/src/analytics/common.ts`: add a `momentum` entry to
  `ANALYTICS_INSIGHTS_FIELDS` with the eight tile keys above so
  `TotalInsights analyticsType="momentum"` works unchanged.
- New folder `apps/web/core/components/analytics/momentum/` mirroring
  `work-items/`: `root.tsx` (AnalyticsWrapper + TotalInsights + four
  sections), `velocity-chart.tsx` (`@plane/propel/charts/bar-chart` for
  committed/completed, rolling average as a line if the bar chart supports an
  overlay, otherwise a second `line-chart` directly below), `throughput-chart.tsx`
  (bar), `cycle-time-chart.tsx` (bar histogram), `cumulative-flow-chart.tsx`
  (`area-chart`, stacked, one area per state group using the state-group
  colours already used elsewhere in the web app). Each follows the
  `created-vs-resolved.tsx` pattern: `useSWR` keyed on workspace + selected
  projects, `AnalyticsSectionWrapper`, `ChartLoader`, `EmptyStateCompact`.
- Window selector: a small segmented control per section (velocity/throughput:
  4 / 8 / 12 / 26 weeks; cumulative flow: 30 / 60 / 90 days), local component
  state, default as in the API table. Do not wire into the global duration
  dropdown.
- `apps/web/core/services/analytics.service.ts`: widen the generic on
  `processUrl` where needed so the new tab/type keys compile; no new methods.
- i18n: add keys under `workspace_analytics` in
  `packages/i18n/src/locales/en/workspace.json` (and the same keys with English
  values in every other locale file that already has `workspace_analytics`, so
  the i18n lint passes): `momentum`, `velocity`, `throughput`, `cycle_time`,
  `lead_time`, `cumulative_flow`, `committed_points`, `completed_points`,
  `rolling_avg`, `avg_velocity`, `last_sprint_velocity`,
  `commitment_reliability`, `avg_throughput`, `median_cycle_time`,
  `p85_cycle_time`, `median_lead_time`, `p85_lead_time`, `last_n_weeks`,
  `last_n_days`. Use the word "stories", matching the fork's terminology.
- Export (`export.ts`) is untouched; the Export button on the Momentum tab is
  hidden.

## Tests

`apps/api/plane/tests/contract/app/test_momentum_analytics_app.py`, same
fixtures style as `test_sprint_capacity_app.py` (workspace, project, member,
estimate + points, cycles with `end_date` pinned to known Bangkok weeks,
`completed_at` pinned so tests do not depend on the weekday they run). Cover:

1. velocity: committed vs completed for two weeks, cancelled story excluded,
   rolling average null for the first two rows, current week present.
2. throughput: a completed story outside any cycle still counts.
3. tiles: reliability uses the last elapsed week, null when committed is 0;
   p85/median computed from a known set of cycle times; fallback to
   `created_at` when no started transition.
4. cumulative flow: a story that moves backlog → started → completed over
   three days produces the expected daily buckets; cancelled drops out.
5. epics are excluded from every series; `project_ids` filter scopes results.
6. `weeks=99` and `type=bogus` return 400.

Run with the repo's existing API test command (see `apps/api` README / CI
workflow). Web has no unit runner; type-check with `pnpm --filter web typecheck`
(or the equivalent script in `apps/web/package.json`) and lint with the repo's
oxlint script.

## Non-goals and risks

- Weekly-sprint assumption is baked in via `SPRINT_TZ` and Monday weeks; if the
  team moves to two-week sprints this needs a setting, not a rewrite.
- Cumulative flow depends on `IssueActivity` state rows being complete. Bulk
  imports that skipped the activity pipeline will show as their initial group
  until their first UI transition. Acceptable; note it in the section subtitle.
