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
import { BoardLayoutIcon, ListLayoutIcon, StateGroupIcon } from "@plane/propel/icons";
import { TOAST_TYPE, setToast } from "@plane/propel/toast";
import type { TSprintCapacity, TSprintCapacityItem, TSprintCapacitySprint, TStateGroups } from "@plane/types";
import { CustomSearchSelect, Input, Loader } from "@plane/ui";
// hooks
import { useAppRouter } from "@/hooks/use-app-router";
import useLocalStorage from "@/hooks/use-local-storage";
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
const stateRank = (group: string | null) => (group ? (STATE_GROUP_ORDER[group] ?? 6) : 6);
const isDone = (group: string | null) => group === "completed" || group === "cancelled";

type TLayout = "list" | "board";

// Board columns run left to right in workflow order; triage and stateless stories only get a column when present.
const BOARD_COLUMNS: { group: TStateGroups | "triage" | null; label: string; always: boolean }[] = [
  { group: "triage", label: "Triage", always: false },
  { group: "backlog", label: "Backlog", always: true },
  { group: "unstarted", label: "Todo", always: true },
  { group: "started", label: "In progress", always: true },
  { group: "completed", label: "Done", always: true },
  { group: "cancelled", label: "Cancelled", always: true },
  { group: null, label: "No state", always: false },
];
const columnOf = (group: string | null) => (BOARD_COLUMNS.some((column) => column.group === group) ? group : null);

const itemHref = (item: TSprintCapacityItem) =>
  `/${item.workspace_slug}/browse/${item.project_identifier}-${item.sequence_id}/`;

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

function BufferTag() {
  return (
    <span
      className="flex-shrink-0 rounded-sm bg-warning-subtle px-1.5 text-11 text-warning-primary"
      title="Added on or after Tuesday 00:00, so it uses the buffer"
    >
      buffer
    </span>
  );
}

function SprintList({ items }: { items: TSprintCapacityItem[] }) {
  const groups = items.reduce<Record<string, TSprintCapacityItem[]>>((acc, item) => {
    const key = `${item.workspace_name} / ${item.project_name}`;
    (acc[key] ||= []).push(item);
    return acc;
  }, {});
  // Array.prototype.sort is stable, so the API's order is kept within each status.
  for (const group of Object.values(groups)) group.sort((a, b) => stateRank(a.state_group) - stateRank(b.state_group));

  return (
    <>
      {Object.entries(groups).map(([group, groupItems]) => (
        <div key={group} className="space-y-1">
          <p className="text-11 font-medium tracking-wide text-tertiary uppercase">{group}</p>
          {groupItems.map((item) => (
            <Link
              key={item.id}
              href={itemHref(item)}
              className={`flex items-center gap-3 rounded-sm px-2 py-1.5 text-13 hover:bg-layer-transparent-hover ${isDone(item.state_group) ? "line-through opacity-60" : ""}`}
            >
              <span className="w-24 flex-shrink-0 text-tertiary">
                {item.project_identifier}-{item.sequence_id}
              </span>
              <span className={`flex-grow truncate ${isDone(item.state_group) ? "text-tertiary" : "text-primary"}`}>
                {item.name}
              </span>
              {item.is_buffer && <BufferTag />}
              <span className="w-24 flex-shrink-0 text-right text-12 text-secondary">{item.state_name}</span>
              <span className="w-12 flex-shrink-0 text-right text-12 font-medium text-primary">
                {item.points === null ? "–" : `${formatPoints(item.points)} pts`}
              </span>
            </Link>
          ))}
        </div>
      ))}
    </>
  );
}

// Read-only board: stories span workspaces with their own states, so columns are state groups and there is no drag.
function SprintBoard({ items }: { items: TSprintCapacityItem[] }) {
  const columns = BOARD_COLUMNS.map((column) => ({
    column,
    items: items.filter((item) => columnOf(item.state_group) === column.group),
  })).filter(({ column, items: columnItems }) => column.always || columnItems.length > 0);

  return (
    <div className="-mx-4 flex gap-3 overflow-x-auto px-4 pb-2">
      {columns.map(({ column, items: columnItems }) => {
        const points = columnItems.reduce((sum, item) => sum + (item.points ?? 0), 0);
        return (
          <div key={column.label} className="flex w-72 flex-shrink-0 flex-col gap-2 rounded-lg bg-layer-2 p-2">
            <div className="flex items-center gap-2 px-1 text-13 font-medium text-primary">
              {column.group && column.group !== "triage" && (
                <StateGroupIcon stateGroup={column.group} className="size-3.5 flex-shrink-0" />
              )}
              <span className="flex-grow truncate">{column.label}</span>
              <span className="font-normal text-12 text-tertiary">
                {columnItems.length} · {formatPoints(points)} pts
              </span>
            </div>
            {columnItems.map((item) => (
              <Link
                key={item.id}
                href={itemHref(item)}
                className={`flex flex-col gap-1.5 rounded-md border border-subtle bg-layer-1 px-3 py-2 text-13 hover:border-strong ${isDone(item.state_group) ? "line-through opacity-60" : ""}`}
              >
                <div className="flex items-center gap-2 text-12 text-tertiary">
                  <span className="flex-shrink-0">
                    {item.project_identifier}-{item.sequence_id}
                  </span>
                  <span className="flex-grow truncate" title={`${item.workspace_name} / ${item.project_name}`}>
                    {item.project_name}
                  </span>
                </div>
                <span className={`line-clamp-3 ${isDone(item.state_group) ? "text-tertiary" : "text-primary"}`}>
                  {item.name}
                </span>
                <div className="flex items-center gap-2 text-12">
                  <span className="flex-grow truncate text-secondary">{item.state_name}</span>
                  {item.is_buffer && <BufferTag />}
                  <span className="flex-shrink-0 font-medium text-primary">
                    {item.points === null ? "–" : `${formatPoints(item.points)} pts`}
                  </span>
                </div>
              </Link>
            ))}
          </div>
        );
      })}
    </div>
  );
}

function SprintSection({
  sprint,
  capacity,
  bufferCapacity,
  isMe,
  layout,
}: {
  sprint: TSprintCapacitySprint;
  capacity: number;
  bufferCapacity: number;
  isMe: boolean;
  layout: TLayout;
}) {
  // Done and cancelled stories are crossed out and leave the sums the capacity is checked against.
  const planned = sprint.remaining_points ?? sprint.planned_points;
  const buffer = sprint.remaining_buffer_points ?? sprint.buffer_points;
  const over = planned > capacity;
  // Planning stays open until Tuesday 00:00 Bangkok time of the sprint week; after that, additions use the buffer.
  const planningOpen = Date.now() < new Date(sprint.buffer_from).getTime();
  const under = planned < capacity && planningOpen;
  const bufferOver = buffer > bufferCapacity;
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
          <CapacityBadge used={planned} capacity={capacity} suffix="pts" />
          <span className="text-13 text-tertiary">+</span>
          <CapacityBadge used={buffer} capacity={bufferCapacity} suffix="buffer" />
        </div>
      </div>
      {(over || under || bufferOver || sprint.unestimated > 0) && (
        <ul className="space-y-0.5 text-12">
          {over && (
            <li className="text-danger-primary">
              Over capacity by {formatPoints(planned - capacity)} pts: move a story back to the backlog.
            </li>
          )}
          {under && (
            <li className="text-secondary">
              {formatPoints(capacity - planned)} pts left to plan before Tuesday 00:00.
            </li>
          )}
          {bufferOver && (
            <li className="text-danger-primary">
              Buffer used up by {formatPoints(buffer - bufferCapacity)} pts: something planned has to give.
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
      ) : sprint.items.length === 0 ? null : layout === "board" ? (
        <SprintBoard items={sprint.items} />
      ) : (
        <SprintList items={sprint.items} />
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

function LayoutToggle({ layout, onChange }: { layout: TLayout; onChange: (layout: TLayout) => void }) {
  const options = [
    { key: "list" as const, title: "List", Icon: ListLayoutIcon },
    { key: "board" as const, title: "Board", Icon: BoardLayoutIcon },
  ];
  return (
    <div className="flex items-center gap-0.5 rounded-md bg-layer-2 p-0.5">
      {options.map(({ key, title, Icon }) => (
        <button
          key={key}
          type="button"
          title={title}
          aria-label={`${title} layout`}
          aria-pressed={layout === key}
          onClick={() => onChange(key)}
          className={`grid size-7 place-items-center rounded-sm ${layout === key ? "bg-layer-1 text-primary shadow-raised-100" : "text-tertiary hover:text-secondary"}`}
        >
          <Icon className="size-3.5" />
        </button>
      ))}
    </div>
  );
}

export function MySprintRoot() {
  const router = useAppRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const userId = searchParams.get("user") ?? undefined;
  const { storedValue, setValue: setLayout } = useLocalStorage<TLayout>("my_sprint_layout", "list");
  const layout = storedValue ?? "list";

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
      <div className={`mx-auto space-y-4 p-6 ${layout === "board" ? "max-w-full" : "max-w-4xl"}`}>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <p className="max-w-xl text-13 text-secondary">
            {data?.user.is_me === false
              ? `${data.user.full_name}'s stories in this week's and next week's sprints, across all workspaces. Stories in projects you can't access are counted but not shown.`
              : `Everything assigned to you in this week's and next week's sprints, across all workspaces and projects. Plan ${data?.capacity ?? 8} points per sprint in total; stories added from Tuesday 00:00 use your ${data?.buffer_capacity ?? 2}-point buffer (Plane User Convention).`}
          </p>
          <div className="flex items-center gap-2">
            <LayoutToggle layout={layout} onChange={setLayout} />
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
            layout={layout}
          />
        ))}
      </div>
    </div>
  );
}
