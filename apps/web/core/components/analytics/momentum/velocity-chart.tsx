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
import { LineChart } from "@plane/propel/charts/line-chart";
import { EmptyStateCompact } from "@plane/propel/empty-state";
import type { IChartResponse, TBarItem, TLineItem } from "@plane/types";
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

const VelocityChart = observer(function VelocityChart() {
  const { selectedProjects, selectedCycle, selectedModule, isPeekView } = useAnalytics();
  const params = useParams();
  const { t } = useTranslation();
  const workspaceSlug = params.workspaceSlug.toString();
  const [weeks, setWeeks] = useState(8);

  const { data, isLoading } = useSWR(
    `momentum-velocity-${workspaceSlug}-${selectedProjects}-${selectedCycle}-${selectedModule}-${isPeekView}-${weeks}`,
    () =>
      analyticsService.getAdvanceAnalyticsCharts<IChartResponse>(
        workspaceSlug,
        "velocity",
        {
          ...(selectedProjects?.length > 0 && { project_ids: selectedProjects.join(",") }),
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
        key: "committed_points",
        label: t("workspace_analytics.committed_points"),
        fill: "#94a3b8",
        textClassName: "",
        stackId: "committed",
      },
      {
        key: "completed_points",
        label: t("workspace_analytics.completed_points"),
        fill: "#16a34a",
        textClassName: "",
        stackId: "completed",
      },
    ],
    [t]
  );

  const lines: TLineItem<string>[] = useMemo(
    () => [
      {
        key: "rolling_avg",
        label: t("workspace_analytics.rolling_avg"),
        stroke: "#f59e0b",
        fill: "#f59e0b",
        smoothCurves: true,
        showDot: false,
        dashedLine: false,
      },
    ],
    [t]
  );

  const windowOptions = WEEK_OPTIONS.map((value) => ({
    value,
    label: t("workspace_analytics.last_n_weeks", { count: value }),
  }));
  const legend = {
    align: "left" as const,
    verticalAlign: "bottom" as const,
    layout: "horizontal" as const,
    wrapperStyles: { justifyContent: "start", alignContent: "start", paddingLeft: "40px", paddingTop: "10px" },
  };

  return (
    <AnalyticsSectionWrapper
      title={t("workspace_analytics.velocity")}
      actions={<WindowSelector value={weeks} options={windowOptions} onChange={setWeeks} />}
    >
      {isLoading ? (
        <ChartLoader />
      ) : data?.data && data.data.length > 0 ? (
        <div className="flex flex-col gap-6">
          <BarChart
            className="h-[320px] w-full"
            data={data.data}
            bars={bars}
            legend={legend}
            xAxis={{ key: "name", label: t("workspace_analytics.velocity") }}
            yAxis={{ key: "completed_points", label: t("common.points"), offset: -60, dx: -24 }}
          />
          <LineChart
            className="h-[160px] w-full"
            data={data.data}
            lines={lines}
            legend={legend}
            xAxis={{ key: "name" }}
            yAxis={{ key: "rolling_avg", label: t("workspace_analytics.rolling_avg"), offset: -60, dx: -24 }}
          />
        </div>
      ) : (
        <EmptyStateCompact
          assetKey="unknown"
          assetClassName="size-20"
          rootClassName="border border-subtle px-5 py-10 md:py-20 md:px-20"
          title={t("workspace_empty_state.analytics_work_items.title")}
        />
      )}
    </AnalyticsSectionWrapper>
  );
});

export default VelocityChart;
