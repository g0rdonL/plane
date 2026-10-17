/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import React from "react";
import AnalyticsWrapper from "../analytics-wrapper";
import TotalInsights from "../total-insights";
import CarryoverChart from "./carryover-chart";
import CumulativeFlowChart from "./cumulative-flow-chart";
import CycleTimeChart from "./cycle-time-chart";
import EstimateAccuracyChart from "./estimate-accuracy-chart";
import ThroughputChart from "./throughput-chart";
import VelocityChart from "./velocity-chart";

function Momentum() {
  return (
    <AnalyticsWrapper i18nTitle="workspace_analytics.momentum">
      <div className="flex flex-col gap-14">
        <TotalInsights analyticsType="momentum" />
        <VelocityChart />
        <CarryoverChart />
        <ThroughputChart />
        <CycleTimeChart />
        <EstimateAccuracyChart />
        <CumulativeFlowChart />
      </div>
    </AnalyticsWrapper>
  );
}

export { Momentum };
