/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useState } from "react";
import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import useSWR from "swr";
// plane imports
import { Button } from "@plane/propel/button";
import { TOAST_TYPE, setToast } from "@plane/propel/toast";
import type { TSprintCapacity, TSprintCapacitySprint } from "@plane/types";
import { CustomSearchSelect, Input, Loader } from "@plane/ui";
// hooks
import { useAppRouter } from "@/hooks/use-app-router";
// services
import { SprintCapacityService } from "@/services/sprint-capacity.service";

const service = new SprintCapacityService();

const fullName = (person: { first_name: string; last_name: string; display_name: string }) =>
  `${person.first_name} ${person.last_name}`.trim() || person.display_name;

// Done first, then the rest in workflow order, so finished work sits at the top of each project.
const STATE_GROUP_ORDER: Record<string, number> = {
  completed: 0,
  cancelled: 1,
  started: 2,
  unstarted: 3,
  backlog: 4,
  triage: 5,
};
const stateRank = (group: string) => STATE_GROUP_ORDER[group] ?? 6;

const formatPoints = (value: number) => (Number.isInteger(value) ? `${value}` : value.toFixed(1));
const formatRange = (start: string, end: string) => {
  const opts: Intl.DateTimeFormatOptions = { day: "numeric", month: "short" };
  return `${new Date(`${start}T00:00:00`).toLocaleDateString("en-GB", opts)} – ${new Date(`${end}T00:00:00`).toLocaleDateString("en-GB", opts)}`;
};

function CapacityBadge({ used, capacity, suffix }: { used: number; capacity: number; suffix: string }) {
  const tone =
    used > capacity
      ? "bg-danger-subtle text-danger-primary"
      : used === capacity && capacity > 0
        ? "bg-success-subtle text-success-primary"
        : "bg-layer-2 text-secondary";
  return (
    <span className={`rounded-full px-3 py-1 text-13 font-semibold whitespace-nowrap ${tone}`}>
      {formatPoints(used)} / {capacity} {suffix}
    </span>
  );
}

function PointsField({ label, value, onChange }: { label: string; value: string; onChange: (v: string) => void }) {
  return (
    <label className="flex items-center gap-1.5 text-12 text-secondary">
      {label}
      <Input
        type="number"
        min={0}
        max={40}
        step={1}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-16"
        inputSize="xs"
      />
    </label>
  );
}

function CapacitySettings({ data, onSaved }: { data: TSprintCapacity; onSaved: () => void }) {
  const [editing, setEditing] = useState(false);
  const [planned, setPlanned] = useState(`${data.capacity}`);
  const [buffer, setBuffer] = useState(`${data.buffer_capacity}`);
  const [saving, setSaving] = useState(false);

  const open = () => {
    setPlanned(`${data.capacity}`);
    setBuffer(`${data.buffer_capacity}`);
    setEditing(true);
  };
  const save = async () => {
    setSaving(true);
    try {
      await service.updateMyCapacity({ planned: Number(planned), buffer: Number(buffer) });
      setEditing(false);
      onSaved();
    } catch (error) {
      setToast({
        type: TOAST_TYPE.ERROR,
        title: "Could not save",
        message: (error as { error?: string })?.error ?? "Use whole numbers from 0 to 40.",
      });
    } finally {
      setSaving(false);
    }
  };

  if (!editing)
    return (
      <button type="button" onClick={open} className="text-12 text-accent-primary hover:underline">
        Set my points
      </button>
    );
  return (
    <div className="flex flex-wrap items-center gap-3 rounded-lg border border-subtle bg-layer-1 px-3 py-2">
      <PointsField label="Planned" value={planned} onChange={setPlanned} />
      <PointsField label="Buffer" value={buffer} onChange={setBuffer} />
      <span className="text-11 text-tertiary">pts per sprint · 1 pt = half a day</span>
      <Button variant="primary" onClick={save} loading={saving}>
        Save
      </Button>
      <Button variant="secondary" onClick={() => setEditing(false)}>
        Cancel
      </Button>
    </div>
  );
}

function SprintSection({
  sprint,
  capacity,
  bufferCapacity,
  isMe,
}: {
  sprint: TSprintCapacitySprint;
  capacity: number;
  bufferCapacity: number;
  isMe: boolean;
}) {
  const over = sprint.planned_points > capacity;
  // Planning stays open until Tuesday 00:00 HKT of the sprint week; after that, additions use the buffer.
  const planningOpen = Date.now() < new Date(sprint.buffer_from).getTime();
  const under = sprint.planned_points < capacity && planningOpen;
  const bufferOver = sprint.buffer_points > bufferCapacity;
  const groups = sprint.items.reduce<Record<string, typeof sprint.items>>((acc, item) => {
    const key = `${item.workspace_name} / ${item.project_name}`;
    (acc[key] ||= []).push(item);
    return acc;
  }, {});
  // Array.prototype.sort is stable, so the API's order is kept within each status.
  for (const items of Object.values(groups)) items.sort((a, b) => stateRank(a.state_group) - stateRank(b.state_group));

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
        <div className="flex items-center gap-1.5">
          <CapacityBadge used={sprint.planned_points} capacity={capacity} suffix="pts" />
          <span className="text-13 text-tertiary">+</span>
          <CapacityBadge used={sprint.buffer_points} capacity={bufferCapacity} suffix="buffer" />
        </div>
      </div>
      {(over || under || bufferOver || sprint.unestimated > 0) && (
        <ul className="space-y-0.5 text-12">
          {over && (
            <li className="text-danger-primary">
              Over capacity by {formatPoints(sprint.planned_points - capacity)} pts: move a story back to the backlog.
            </li>
          )}
          {under && (
            <li className="text-secondary">
              {formatPoints(capacity - sprint.planned_points)} pts left to plan before Tuesday 00:00.
            </li>
          )}
          {bufferOver && (
            <li className="text-danger-primary">
              Buffer used up by {formatPoints(sprint.buffer_points - bufferCapacity)} pts: something planned has to
              give.
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
                {item.is_buffer && (
                  <span
                    className="flex-shrink-0 rounded-sm bg-warning-subtle px-1.5 text-11 text-warning-primary"
                    title="Added on or after Tuesday 00:00, so it uses the buffer"
                  >
                    buffer
                  </span>
                )}
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
  const { data, error, mutate } = useSWR(
    `MY_SPRINT_CAPACITY_${userId ?? "me"}`,
    () => service.getSprintCapacity(userId),
    {
      revalidateOnFocus: true,
    }
  );

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
              : `Everything assigned to you in this week's and next week's sprints, across all workspaces and projects. Plan ${data?.capacity ?? 8} points per sprint in total; stories added from Tuesday 00:00 use your ${data?.buffer_capacity ?? 2}-point buffer (Plane User Convention).`}
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
        {data?.user.is_me && <CapacitySettings data={data} onSaved={() => void mutate()} />}
        {error && <p className="text-13 text-danger-primary">Could not load this sprint. Refresh to try again.</p>}
        {!data && !error && (
          <Loader className="space-y-4">
            <Loader.Item height="160px" />
            <Loader.Item height="160px" />
          </Loader>
        )}
        {data?.sprints.map((sprint) => (
          <SprintSection
            key={sprint.label}
            sprint={sprint}
            capacity={data.capacity}
            bufferCapacity={data.buffer_capacity}
            isMe={data.user.is_me}
          />
        ))}
      </div>
    </div>
  );
}
