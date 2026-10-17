/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useMemo, useState } from "react";
import { observer } from "mobx-react";
import { useParams } from "next/navigation";
import useSWR from "swr";
// plane imports
import { useTranslation } from "@plane/i18n";
import { BarChart } from "@plane/propel/charts/bar-chart";
import { EmptyStateCompact } from "@plane/propel/empty-state";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@plane/propel/table";
import type { IChartResponse, TBarItem } from "@plane/types";
// hooks
import { useAnalytics } from "@/hooks/store/use-analytics";
// services
import { AnalyticsService } from "@/services/analytics.service";
// local imports
import AnalyticsSectionWrapper from "../analytics-section-wrapper";
import { ChartLoader } from "../loaders";
import WindowSelector from "./window-selector";

const analyticsService = new AnalyticsService();
const WEEK_OPTIONS = [4, 8, 12, 26];

type TEstimateAccuracyRow = {
  key: string;
  name: string;
  count: number;
  median_days: number | null;
  p85_days: number | null;
  min_days: number;
  max_days: number;
  reestimated_count: number;
};

type TEstimateAccuracyResponse = IChartResponse & { unestimated_count: number };

const EstimateAccuracyChart = observer(function EstimateAccuracyChart() {
  const { selectedProjects, selectedAssignees, selectedCycle, selectedModule, isPeekView } = useAnalytics();
  const params = useParams();
  const { t } = useTranslation();
  const workspaceSlug = params.workspaceSlug.toString();
  const [weeks, setWeeks] = useState(8);

  const { data, isLoading } = useSWR(
    `momentum-estimate-accuracy-${workspaceSlug}-${selectedProjects}-${selectedAssignees}-${selectedCycle}-${selectedModule}-${isPeekView}-${weeks}`,
    () =>
      analyticsService.getAdvanceAnalyticsCharts<TEstimateAccuracyResponse>(
        workspaceSlug,
        "estimate-accuracy",
        {
          ...(selectedProjects?.length > 0 && { project_ids: selectedProjects.join(",") }),
          ...(selectedAssignees?.length > 0 && { assignee_ids: selectedAssignees.join(",") }),
          ...(selectedCycle ? { cycle_id: selectedCycle } : {}),
          ...(selectedModule ? { module_id: selectedModule } : {}),
          weeks,
        },
        isPeekView
      )
  );

  const bars: TBarItem<string>[] = useMemo(
    () => [
      {
        key: "median_days",
        label: t("workspace_analytics.estimate_median_days"),
        fill: "#2563eb",
        textClassName: "",
        stackId: "median",
      },
      {
        key: "p85_days",
        label: t("workspace_analytics.estimate_p85_days"),
        fill: "#93c5fd",
        textClassName: "",
        stackId: "p85",
      },
    ],
    [t]
  );

  const windowOptions = WEEK_OPTIONS.map((value) => ({
    value,
    label: t("workspace_analytics.last_n_weeks", { count: value }),
  }));

  const rows = (data?.data ?? []) as unknown as TEstimateAccuracyRow[];
  const legend = {
    align: "left" as const,
    verticalAlign: "bottom" as const,
    layout: "horizontal" as const,
    wrapperStyles: { justifyContent: "start", alignContent: "start", paddingLeft: "40px", paddingTop: "10px" },
  };

  return (
    <AnalyticsSectionWrapper
      title={t("workspace_analytics.estimate_accuracy")}
      actions={<WindowSelector value={weeks} options={windowOptions} onChange={setWeeks} />}
    >
      {isLoading ? (
        <ChartLoader />
      ) : rows.length > 0 ? (
        <div className="flex flex-col gap-6">
          <BarChart
            className="h-[320px] w-full"
            data={data?.data ?? []}
            bars={bars}
            legend={legend}
            xAxis={{ key: "name", label: t("workspace_analytics.estimate_points") }}
            yAxis={{ key: "median_days", label: t("workspace_analytics.estimate_days"), offset: -60, dx: -24 }}
          />
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t("workspace_analytics.estimate_points")}</TableHead>
                <TableHead className="text-right">{t("workspace_analytics.estimate_stories")}</TableHead>
                <TableHead className="text-right">{t("workspace_analytics.estimate_median_days")}</TableHead>
                <TableHead className="text-right">{t("workspace_analytics.estimate_p85_days")}</TableHead>
                <TableHead className="text-right">{t("workspace_analytics.estimate_range")}</TableHead>
                <TableHead className="text-right">{t("workspace_analytics.estimate_reestimated")}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((row) => {
                const reestimatedPct = row.count > 0 ? Math.round((row.reestimated_count / row.count) * 100) : 0;
                return (
                  <TableRow key={row.key}>
                    <TableCell className="font-medium">{row.name}</TableCell>
                    <TableCell className="text-right">{row.count}</TableCell>
                    <TableCell className="text-right">{row.median_days ?? "—"}</TableCell>
                    <TableCell className="text-right">{row.p85_days ?? "—"}</TableCell>
                    <TableCell className="text-right">
                      {row.min_days}–{row.max_days}
                    </TableCell>
                    <TableCell className="text-right">
                      {row.reestimated_count} ({reestimatedPct}%)
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
          {!!data?.unestimated_count && (
            <p className="text-13 text-tertiary">
              {t("workspace_analytics.estimate_unestimated_note", { count: data.unestimated_count })}
            </p>
          )}
        </div>
      ) : (
        <EmptyStateCompact
          assetKey="unknown"
          assetClassName="size-20"
          rootClassName="border border-subtle px-5 py-10 md:py-20 md:px-20"
          title={t("workspace_analytics.momentum_empty_state")}
        />
      )}
    </AnalyticsSectionWrapper>
  );
});

export default EstimateAccuracyChart;
