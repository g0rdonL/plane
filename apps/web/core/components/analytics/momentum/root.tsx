/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import React from "react";
import AnalyticsWrapper from "../analytics-wrapper";
import TotalInsights from "../total-insights";
import CumulativeFlowChart from "./cumulative-flow-chart";
import CycleTimeChart from "./cycle-time-chart";
import ThroughputChart from "./throughput-chart";
import VelocityChart from "./velocity-chart";

function Momentum() {
  return (
    <AnalyticsWrapper i18nTitle="workspace_analytics.momentum">
      <div className="flex flex-col gap-14">
        <TotalInsights analyticsType="momentum" />
        <VelocityChart />
        <ThroughputChart />
        <CycleTimeChart />
        <CumulativeFlowChart />
      </div>
    </AnalyticsWrapper>
  );
}

export { Momentum };
