/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import useSWR from "swr";
// plane imports
import type { TSprintCapacitySprint } from "@plane/types";
import { CustomSearchSelect, Loader } from "@plane/ui";
// hooks
import { useAppRouter } from "@/hooks/use-app-router";
// services
import { SprintCapacityService } from "@/services/sprint-capacity.service";

const service = new SprintCapacityService();

const fullName = (person: { first_name: string; last_name: string; display_name: string }) =>
  `${person.first_name} ${person.last_name}`.trim() || person.display_name;

const formatPoints = (value: number) => (Number.isInteger(value) ? `${value}` : value.toFixed(1));
const formatRange = (start: string, end: string) => {
  const opts: Intl.DateTimeFormatOptions = { day: "numeric", month: "short" };
  return `${new Date(`${start}T00:00:00`).toLocaleDateString("en-GB", opts)} – ${new Date(`${end}T00:00:00`).toLocaleDateString("en-GB", opts)}`;
};

function CapacityBadge({ planned, capacity }: { planned: number; capacity: number }) {
  const tone =
    planned > capacity
      ? "bg-danger-subtle text-danger-primary"
      : planned === capacity
        ? "bg-success-subtle text-success-primary"
        : "bg-layer-2 text-secondary";
  return (
    <span className={`rounded-full px-3 py-1 text-13 font-semibold ${tone}`}>
      {formatPoints(planned)} / {capacity} pts
    </span>
  );
}

function SprintSection({ sprint, capacity, isMe }: { sprint: TSprintCapacitySprint; capacity: number; isMe: boolean }) {
  const over = sprint.planned_points > capacity;
  const under = sprint.planned_points < capacity;
  const groups = sprint.items.reduce<Record<string, typeof sprint.items>>((acc, item) => {
    const key = `${item.workspace_name} / ${item.project_name}`;
    (acc[key] ||= []).push(item);
    return acc;
  }, {});

  return (
    <section className="space-y-3 rounded-lg border border-subtle bg-layer-1 p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h2 className="text-16 font-semibold text-primary">
            {sprint.label} {sprint.is_current ? "· this week" : "· next week"}
          </h2>
          <p className="text-12 text-tertiary">
            {formatRange(sprint.start_date, sprint.end_date)} · {formatPoints(sprint.done_points)} pts done
          </p>
        </div>
        <CapacityBadge planned={sprint.planned_points} capacity={capacity} />
      </div>
      {(over || under || sprint.unestimated > 0) && (
        <ul className="space-y-0.5 text-12">
          {over && (
            <li className="text-danger-primary">
              Over capacity by {formatPoints(sprint.planned_points - capacity)} pts: move a story back to the backlog.
            </li>
          )}
          {under && !sprint.is_current && (
            <li className="text-secondary">
              {formatPoints(capacity - sprint.planned_points)} pts left to plan before Friday 17:00.
            </li>
          )}
          {sprint.unestimated > 0 && (
            <li className="text-warning-primary">
              {sprint.unestimated} {sprint.unestimated === 1 ? "story has" : "stories have"} no estimate yet.
            </li>
          )}
        </ul>
      )}
      {sprint.items.length === 0 && sprint.hidden.count === 0 ? (
        <p className="text-13 text-tertiary">Nothing assigned{isMe ? " to you" : ""} in this sprint yet.</p>
      ) : sprint.items.length === 0 ? null : (
        Object.entries(groups).map(([group, items]) => (
          <div key={group} className="space-y-1">
            <p className="text-11 font-medium tracking-wide text-tertiary uppercase">{group}</p>
            {items.map((item) => (
              <Link
                key={item.id}
                href={`/${item.workspace_slug}/browse/${item.project_identifier}-${item.sequence_id}/`}
                className="flex items-center gap-3 rounded-sm px-2 py-1.5 text-13 hover:bg-layer-transparent-hover"
              >
                <span className="w-24 flex-shrink-0 text-tertiary">
                  {item.project_identifier}-{item.sequence_id}
                </span>
                <span
                  className={`flex-grow truncate ${item.state_group === "completed" || item.state_group === "cancelled" ? "text-tertiary line-through" : "text-primary"}`}
                >
                  {item.name}
                </span>
                <span className="w-24 flex-shrink-0 text-right text-12 text-secondary">{item.state_name}</span>
                <span className="w-12 flex-shrink-0 text-right text-12 font-medium text-primary">
                  {item.points === null ? "–" : `${formatPoints(item.points)} pts`}
                </span>
              </Link>
            ))}
          </div>
        ))
      )}
      {sprint.hidden.count > 0 && (
        <p className="rounded-sm bg-layer-2 px-2 py-1.5 text-12 text-secondary">
          {sprint.hidden.count} {sprint.hidden.count === 1 ? "story" : "stories"} in projects you can&apos;t access ·{" "}
          {formatPoints(sprint.hidden.points)} pts
        </p>
      )}
    </section>
  );
}

export function MySprintRoot() {
  const router = useAppRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const userId = searchParams.get("user") ?? undefined;

  const { data: people } = useSWR("MY_SPRINT_PEOPLE", () => service.getPeople(), { revalidateOnFocus: false });
  const { data, error } = useSWR(`MY_SPRINT_CAPACITY_${userId ?? "me"}`, () => service.getSprintCapacity(userId), {
    revalidateOnFocus: true,
  });

  const me = people?.find((person) => person.is_me);
  const options = (people ?? []).map((person) => {
    const name = person.is_me ? `${fullName(person)} (me)` : fullName(person);
    return {
      value: person.id,
      query: `${person.display_name} ${person.first_name} ${person.last_name}`,
      content: <span className="truncate">{name}</span>,
    };
  });
  const handlePersonChange = (id: string) => router.push(id === me?.id ? pathname : `${pathname}?user=${id}`);

  return (
    <div className="h-full w-full overflow-y-auto">
      <div className="mx-auto max-w-4xl space-y-4 p-6">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <p className="max-w-xl text-13 text-secondary">
            {data?.user.is_me === false
              ? `${data.user.full_name}'s stories in this week's and next week's sprints, across all workspaces. Stories in projects you can't access are counted but not shown.`
              : `Everything assigned to you in this week's and next week's sprints, across all workspaces and projects. Plan ${data?.capacity ?? 8} points per sprint in total (Plane User Convention).`}
          </p>
          <CustomSearchSelect
            value={data?.user.id ?? me?.id}
            onChange={handlePersonChange}
            options={options}
            label={
              <span className="text-13">{data ? (data.user.is_me ? "My sprint" : data.user.full_name) : "…"}</span>
            }
            maxHeight="md"
            placement="bottom-end"
            noResultsMessage="No teammate found"
          />
        </div>
        {error && <p className="text-13 text-danger-primary">Could not load this sprint. Refresh to try again.</p>}
        {!data && !error && (
          <Loader className="space-y-4">
            <Loader.Item height="160px" />
            <Loader.Item height="160px" />
          </Loader>
        )}
        {data?.sprints.map((sprint) => (
          <SprintSection key={sprint.label} sprint={sprint} capacity={data.capacity} isMe={data.user.is_me} />
        ))}
      </div>
    </div>
  );
}
