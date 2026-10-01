/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { observer } from "mobx-react";
import useSWR from "swr";
// plane imports
import type { TEpicProgress } from "@plane/types";
// hooks
import { useIssueDetail } from "@/hooks/store/use-issue-detail";
// services
import { IssueService } from "@/services/issue";

const issueService = new IssueService();

const STATE_GROUPS: {
  key: "backlog" | "unstarted" | "started" | "completed" | "cancelled";
  label: string;
  color: string;
}[] = [
  { key: "completed", label: "Done", color: "#46A758" },
  { key: "started", label: "In progress", color: "#F59E0B" },
  { key: "unstarted", label: "Todo", color: "#3F76FF" },
  { key: "backlog", label: "Backlog", color: "#A3A3A3" },
  { key: "cancelled", label: "Cancelled", color: "#9AA4BC" },
];

const formatPoints = (value: number) => (Number.isInteger(value) ? `${value}` : value.toFixed(1));

type Props = {
  workspaceSlug: string;
  projectId: string;
  epicId: string;
};

export const EpicProgress = observer(function EpicProgress(props: Props) {
  const { workspaceSlug, projectId, epicId } = props;
  // store hooks
  const {
    subIssues: { subIssuesByIssueId, stateDistributionByIssueId },
  } = useIssueDetail();
  // refetch whenever the epic's work items or their states change
  const revision = JSON.stringify([subIssuesByIssueId(epicId) ?? [], stateDistributionByIssueId(epicId) ?? {}]);

  const { data } = useSWR<TEpicProgress>(
    `EPIC_PROGRESS_${epicId}_${revision}`,
    () => issueService.getEpicProgress(workspaceSlug, projectId, epicId),
    { keepPreviousData: true }
  );

  if (!data) return null;

  const total = data.total_issues;
  const completed = data.completed_issues;
  const percentage = total ? Math.round((completed / total) * 100) : 0;
  const hasPoints = data.total_estimate_points > 0;
  const pointsPercentage = hasPoints
    ? Math.round((data.completed_estimate_points / data.total_estimate_points) * 100)
    : 0;
  const barBase = hasPoints ? data.total_estimate_points : total;

  return (
    <div className="space-y-3 rounded-lg border border-subtle bg-layer-1 p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h4 className="text-13 font-medium text-primary">Epic progress</h4>
        <div className="flex items-center gap-4 text-12 text-secondary">
          <span>
            <span className="font-medium text-primary">{completed}</span>/{total} work items done ({percentage}%)
          </span>
          {hasPoints && (
            <span>
              <span className="font-medium text-primary">{formatPoints(data.completed_estimate_points)}</span>/
              {formatPoints(data.total_estimate_points)} points ({pointsPercentage}%)
            </span>
          )}
          {data.overdue_issues > 0 && <span className="text-danger-primary">{data.overdue_issues} overdue</span>}
        </div>
      </div>
      <div className="flex h-2 w-full overflow-hidden rounded-full bg-layer-2">
        {barBase > 0 &&
          STATE_GROUPS.map((group) => {
            const value = hasPoints ? data[`${group.key}_estimate_points`] : data[`${group.key}_issues`];
            if (!value) return null;
            return (
              <div
                key={group.key}
                className="h-full"
                style={{ width: `${(value / barBase) * 100}%`, backgroundColor: group.color }}
                title={`${group.label}: ${hasPoints ? `${formatPoints(value)} points` : `${value} work items`}`}
              />
            );
          })}
      </div>
      <div className="flex flex-wrap gap-x-4 gap-y-1 text-11 text-tertiary">
        {STATE_GROUPS.map((group) => (
          <span key={group.key} className="flex items-center gap-1.5">
            <span className="size-2 rounded-full" style={{ backgroundColor: group.color }} />
            {group.label} {data[`${group.key}_issues`]}
            {hasPoints && ` · ${formatPoints(data[`${group.key}_estimate_points`])} pts`}
          </span>
        ))}
      </div>
      {total === 0 && (
        <p className="text-12 text-tertiary">
          Add work items to this epic below. Progress and story points roll up automatically.
        </p>
      )}
    </div>
  );
});
