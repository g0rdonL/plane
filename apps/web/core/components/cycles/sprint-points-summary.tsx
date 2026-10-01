/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 *
 * aight fork: story point sums for a sprint, split into Todo, In progress (In Progress + In Review),
 * and Done. Backed by the unstarted/started/completed state groups.
 */

import { observer } from "mobx-react";
import { Tooltip } from "@plane/propel/tooltip";
import type { ICycle } from "@plane/types";
import { cn } from "@plane/utils";

const formatPoints = (value: number | undefined) => {
  const v = value ?? 0;
  return Number.isInteger(v) ? `${v}` : v.toFixed(1);
};

const BUCKETS = [
  { key: "unstarted_estimate_points", label: "Todo", dot: "bg-[#9AA4BC]" },
  { key: "started_estimate_points", label: "In progress", dot: "bg-[#F59E0B]" },
  { key: "completed_estimate_points", label: "Done", dot: "bg-[#16A34A]" },
] as const;

type TPointsValues = Partial<Record<(typeof BUCKETS)[number]["key"], number>>;

type TPointsSummaryProps = {
  values: TPointsValues | undefined;
  isMobile?: boolean;
  className?: string;
};

/** Todo / In progress / Done story point chips. Renders nothing until values are loaded. */
export const PointsSummary = observer(function PointsSummary(props: TPointsSummaryProps) {
  const { values, isMobile = false, className } = props;
  if (!values || BUCKETS.every((b) => values[b.key] === undefined)) return null;

  return (
    <Tooltip
      isMobile={isMobile}
      tooltipHeading="Story points"
      tooltipContent="Includes sub-work items. In progress = In Progress + In Review."
      position="bottom"
    >
      <div
        className={cn(
          "flex flex-shrink-0 cursor-default items-center gap-2 rounded-md bg-layer-1 px-2 py-0.5 text-11 text-tertiary",
          className
        )}
      >
        {BUCKETS.map((b) => (
          <span key={b.key} className="flex items-center gap-1 whitespace-nowrap">
            <span className={cn("size-1.5 flex-shrink-0 rounded-full", b.dot)} />
            <span>{b.label}</span>
            <span className="font-semibold text-secondary">{formatPoints(values[b.key])}</span>
          </span>
        ))}
        <span className="text-placeholder">pts</span>
      </div>
    </Tooltip>
  );
});

type Props = {
  cycle: ICycle | undefined;
  isMobile?: boolean;
  className?: string;
};

export const SprintPointsSummary = observer(function SprintPointsSummary(props: Props) {
  const { cycle, ...rest } = props;
  return <PointsSummary values={cycle} {...rest} />;
});
