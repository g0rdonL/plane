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
import { STATE_GROUPS } from "@plane/constants";
import { useTranslation } from "@plane/i18n";
import { AreaChart } from "@plane/propel/charts/area-chart";
import { EmptyStateCompact } from "@plane/propel/empty-state";
import type { IChartResponse, TAreaItem } from "@plane/types";
// hooks
import { useAnalytics } from "@/hooks/store/use-analytics";
// services
import { AnalyticsService } from "@/services/analytics.service";
// local imports
import AnalyticsSectionWrapper from "../analytics-section-wrapper";
import { ChartLoader } from "../loaders";
import WindowSelector from "./window-selector";

const analyticsService = new AnalyticsService();
const DAY_OPTIONS = [30, 60, 90];

const CumulativeFlowChart = observer(function CumulativeFlowChart() {
  const { selectedProjects, selectedCycle, selectedModule, isPeekView } = useAnalytics();
  const params = useParams();
  const { t } = useTranslation();
  const workspaceSlug = params.workspaceSlug.toString();
  const [days, setDays] = useState(30);

  const { data, isLoading } = useSWR(
    `momentum-cumulative-flow-${workspaceSlug}-${selectedProjects}-${selectedCycle}-${selectedModule}-${isPeekView}-${days}`,
    () =>
      analyticsService.getAdvanceAnalyticsCharts<IChartResponse>(
        workspaceSlug,
        "cumulative-flow",
        {
          ...(selectedProjects?.length > 0 && { project_ids: selectedProjects.join(",") }),
          ...(selectedCycle ? { cycle_id: selectedCycle } : {}),
          ...(selectedModule ? { module_id: selectedModule } : {}),
          days,
        },
        isPeekView
      )
  );

  const areas: TAreaItem<string>[] = useMemo(
    () => [
      {
        key: "backlog",
        label: t("workspace_projects.state.backlog"),
        stackId: "flow",
        fill: STATE_GROUPS.backlog.color,
        fillOpacity: 0.6,
        strokeColor: STATE_GROUPS.backlog.color,
        strokeOpacity: 1,
        showDot: false,
        smoothCurves: false,
      },
      {
        key: "unstarted",
        label: t("workspace_projects.state.unstarted"),
        stackId: "flow",
        fill: STATE_GROUPS.unstarted.color,
        fillOpacity: 0.6,
        strokeColor: STATE_GROUPS.unstarted.color,
        strokeOpacity: 1,
        showDot: false,
        smoothCurves: false,
      },
      {
        key: "started",
        label: t("workspace_projects.state.started"),
        stackId: "flow",
        fill: STATE_GROUPS.started.color,
        fillOpacity: 0.6,
        strokeColor: STATE_GROUPS.started.color,
        strokeOpacity: 1,
        showDot: false,
        smoothCurves: false,
      },
      {
        key: "completed",
        label: t("workspace_projects.state.completed"),
        stackId: "flow",
        fill: STATE_GROUPS.completed.color,
        fillOpacity: 0.6,
        strokeColor: STATE_GROUPS.completed.color,
        strokeOpacity: 1,
        showDot: false,
        smoothCurves: false,
      },
    ],
    [t]
  );

  const windowOptions = DAY_OPTIONS.map((value) => ({
    value,
    label: t("workspace_analytics.last_n_days", { count: value }),
  }));

  return (
    <AnalyticsSectionWrapper
      title={t("workspace_analytics.cumulative_flow")}
      actions={<WindowSelector value={days} options={windowOptions} onChange={setDays} />}
    >
      {isLoading ? (
        <ChartLoader />
      ) : data?.data && data.data.length > 0 ? (
        <>
          <AreaChart
            className="h-[320px] w-full"
            data={data.data}
            areas={areas}
            xAxis={{ key: "name", label: t("workspace_analytics.cumulative_flow") }}
            yAxis={{ key: "completed", label: t("common.no_of", { entity: "Stories" }), offset: -60, dx: -24 }}
            legend={{
              align: "left",
              verticalAlign: "bottom",
              layout: "horizontal",
              wrapperStyles: {
                justifyContent: "start",
                alignContent: "start",
                paddingLeft: "40px",
                paddingTop: "10px",
              },
            }}
          />
          <p className="mt-2 text-11 text-tertiary">
            Reconstructed from state transitions; stories imported without activity history show their initial state
            until their first change.
          </p>
        </>
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

export default CumulativeFlowChart;
