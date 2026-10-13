/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { sortBy } from "lodash-es";
import type { TIssueRecurrence } from "@plane/types";

type TTranslate = (key: string, params?: Record<string, unknown>) => string;

export const WEEKDAYS = [0, 1, 2, 3, 4, 5, 6];

export const getRecurrenceSummary = (t: TTranslate, recurrence: TIssueRecurrence | null | undefined): string => {
  if (!recurrence) return t("recurrence.none");
  if (recurrence.frequency === "weekly") {
    const days = sortBy(recurrence.weekdays)
      .map((day) => t(`recurrence.days.${day}`))
      .join(", ");
    return t("recurrence.weekly_on", { days });
  }
  if (recurrence.frequency === "monthly") return t("recurrence.monthly_on", { day: recurrence.day_of_month ?? 1 });
  return t(`recurrence.${recurrence.frequency}`);
};

export const getNextRunLabel = (t: TTranslate, recurrence: TIssueRecurrence): string => {
  const date = new Date(recurrence.next_run_at).toLocaleDateString(undefined, {
    weekday: "short",
    day: "numeric",
    month: "short",
  });
  return t("recurrence.next", { date });
};
