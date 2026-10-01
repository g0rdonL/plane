/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

export type TEpicAnalyticsGroup =
  | "backlog_issues"
  | "unstarted_issues"
  | "started_issues"
  | "completed_issues"
  | "cancelled_issues"
  | "overdue_issues";

export type TEpicAnalytics = {
  backlog_issues: number;
  unstarted_issues: number;
  started_issues: number;
  completed_issues: number;
  cancelled_issues: number;
  overdue_issues: number;
};

export type TEpicProgress = TEpicAnalytics & {
  total_issues: number;
  total_estimate_points: number;
  backlog_estimate_points: number;
  unstarted_estimate_points: number;
  started_estimate_points: number;
  completed_estimate_points: number;
  cancelled_estimate_points: number;
};

export type TSprintCapacityItem = {
  id: string;
  name: string;
  workspace_slug: string;
  workspace_name: string;
  project_id: string;
  project_identifier: string;
  project_name: string;
  sequence_id: number;
  state_name: string | null;
  state_group: string | null;
  points: number | null;
};

export type TSprintCapacitySprint = {
  label: string;
  start_date: string;
  end_date: string;
  is_current: boolean;
  planned_points: number;
  done_points: number;
  unestimated: number;
  items: TSprintCapacityItem[];
};

export type TSprintCapacity = {
  capacity: number;
  sprints: TSprintCapacitySprint[];
};
