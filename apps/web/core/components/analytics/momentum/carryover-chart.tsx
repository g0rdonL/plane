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

const CarryoverChart = observer(function CarryoverChart() {
  const { selectedProjects, selectedCycle, selectedModule, isPeekView } = useAnalytics();
  const params = useParams();
  const { t } = useTranslation();
  const workspaceSlug = params.workspaceSlug.toString();
  const [weeks, setWeeks] = useState(8);

  const { data, isLoading } = useSWR(
    `momentum-carryover-${workspaceSlug}-${selectedProjects}-${selectedCycle}-${selectedModule}-${isPeekView}-${weeks}`,
    () =>
      analyticsService.getAdvanceAnalyticsCharts<IChartResponse>(
        workspaceSlug,
        "carryover",
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
        key: "carryover_points",
        label: t("workspace_analytics.carryover_points"),
        fill: "#dc2626",
        textClassName: "",
        stackId: "carryover",
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
      title={t("workspace_analytics.carryover")}
      actions={<WindowSelector value={weeks} options={windowOptions} onChange={setWeeks} />}
    >
      {isLoading ? (
        <ChartLoader />
      ) : data?.data && data.data.length > 0 ? (
        <BarChart
          className="h-[320px] w-full"
          data={data.data}
          bars={bars}
          legend={legend}
          xAxis={{ key: "name", label: t("workspace_analytics.carryover") }}
          yAxis={{ key: "committed_points", label: t("common.points"), offset: -60, dx: -24 }}
        />
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

export default CarryoverChart;
