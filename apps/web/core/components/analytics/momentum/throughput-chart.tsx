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

const ThroughputChart = observer(function ThroughputChart() {
  const { selectedProjects, selectedCycle, selectedModule, isPeekView } = useAnalytics();
  const params = useParams();
  const { t } = useTranslation();
  const workspaceSlug = params.workspaceSlug.toString();
  const [weeks, setWeeks] = useState(12);

  const { data, isLoading } = useSWR(
    `momentum-throughput-${workspaceSlug}-${selectedProjects}-${selectedCycle}-${selectedModule}-${isPeekView}-${weeks}`,
    () =>
      analyticsService.getAdvanceAnalyticsCharts<IChartResponse>(
        workspaceSlug,
        "throughput",
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
        key: "completed_count",
        label: t("workspace_analytics.throughput"),
        fill: "#16a34a",
        textClassName: "",
        stackId: "completed",
      },
    ],
    [t]
  );

  const windowOptions = WEEK_OPTIONS.map((value) => ({
    value,
    label: t("workspace_analytics.last_n_weeks", { count: value }),
  }));

  return (
    <AnalyticsSectionWrapper
      title={t("workspace_analytics.throughput")}
      actions={<WindowSelector value={weeks} options={windowOptions} onChange={setWeeks} />}
    >
      {isLoading ? (
        <ChartLoader />
      ) : data?.data && data.data.length > 0 ? (
        <BarChart
          className="h-[320px] w-full"
          data={data.data}
          bars={bars}
          xAxis={{ key: "name", label: t("workspace_analytics.throughput") }}
          yAxis={{ key: "completed_count", label: t("common.no_of", { entity: "Stories" }), offset: -60, dx: -24 }}
        />
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

export default ThroughputChart;
