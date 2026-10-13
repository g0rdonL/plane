/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useContext, useState } from "react";
import { observer } from "mobx-react";
import { Popover } from "@headlessui/react";
import { EUserPermissionsLevel } from "@plane/constants";
import { useTranslation } from "@plane/i18n";
import { setToast, TOAST_TYPE } from "@plane/propel/toast";
import type { TIssueRecurrenceFrequency, TIssueRecurrencePayload } from "@plane/types";
import { EUserPermissions } from "@plane/types";
import { cn } from "@plane/utils";
// hooks
import { useUser } from "@/hooks/store/user";
import { StoreContext } from "@/lib/store-context";
// services
import { IssueRecurrenceService } from "@/services/issue/issue_recurrence.service";
// local imports
import { getNextRunLabel, getRecurrenceSummary, WEEKDAYS } from "./summary";

const recurrenceService = new IssueRecurrenceService();
const FREQUENCIES: (TIssueRecurrenceFrequency | null)[] = [null, "daily", "weekdays", "weekly", "monthly"];
const DAYS_OF_MONTH = Array.from({ length: 31 }, (_, i) => i + 1);

type Props = {
  workspaceSlug: string;
  projectId: string;
  issueId: string;
  disabled?: boolean;
};

export const IssueRecurrenceProperty = observer(function IssueRecurrenceProperty(props: Props) {
  const { workspaceSlug, projectId, issueId, disabled = false } = props;
  const { t } = useTranslation();
  const store = useContext(StoreContext);
  const {
    permission: { allowPermissions },
  } = useUser();
  const [isSaving, setIsSaving] = useState(false);

  const issue = store.issue.issues.getIssueById(issueId);
  const recurrence = issue?.recurrence ?? null;
  const canEdit =
    !disabled &&
    allowPermissions(
      [EUserPermissions.ADMIN, EUserPermissions.MEMBER],
      EUserPermissionsLevel.PROJECT,
      workspaceSlug,
      projectId
    );

  const save = async (payload: TIssueRecurrencePayload | null) => {
    setIsSaving(true);
    try {
      if (payload) {
        const next = await recurrenceService.set(workspaceSlug, projectId, issueId, payload);
        store.issue.issues.updateIssue(issueId, { recurrence: next });
      } else {
        await recurrenceService.remove(workspaceSlug, projectId, issueId);
        store.issue.issues.updateIssue(issueId, { recurrence: null });
      }
    } catch {
      setToast({ type: TOAST_TYPE.ERROR, title: t("toast.error"), message: t("recurrence.update_error") });
    } finally {
      setIsSaving(false);
    }
  };

  const selectFrequency = (frequency: TIssueRecurrenceFrequency | null) => {
    if (frequency === null) return void save(null);
    if (frequency === "weekly") {
      // default to today's weekday (Mon = 0)
      const today = (new Date().getDay() + 6) % 7;
      return void save({ frequency, weekdays: recurrence?.weekdays?.length ? recurrence.weekdays : [today] });
    }
    if (frequency === "monthly")
      return void save({ frequency, day_of_month: recurrence?.day_of_month ?? new Date().getDate() });
    return void save({ frequency });
  };

  const toggleWeekday = (day: number) => {
    if (!recurrence) return;
    const weekdays = recurrence.weekdays.includes(day)
      ? recurrence.weekdays.filter((d) => d !== day)
      : [...recurrence.weekdays, day];
    if (weekdays.length === 0) return; // weekly needs at least one day
    void save({ frequency: "weekly", weekdays });
  };

  const summaryLabel = getRecurrenceSummary(t, recurrence);

  if (!canEdit)
    return <span className={cn("px-2 text-body-xs-regular", { "text-placeholder": !recurrence })}>{summaryLabel}</span>;

  return (
    <Popover className="relative w-full">
      <Popover.Button
        type="button"
        disabled={isSaving}
        className={cn("h-7.5 w-full rounded-sm px-2 text-left text-body-xs-regular hover:bg-layer-1", {
          "text-placeholder": !recurrence,
        })}
      >
        {summaryLabel}
      </Popover.Button>
      <Popover.Panel className="absolute left-0 z-20 mt-1 w-56 rounded-md border border-subtle bg-surface-1 p-2 shadow-raised-200">
        <div className="flex flex-col gap-0.5">
          {FREQUENCIES.map((frequency) => {
            const isActive = (recurrence?.frequency ?? null) === frequency;
            return (
              <button
                key={frequency ?? "none"}
                type="button"
                disabled={isSaving}
                onClick={() => selectFrequency(frequency)}
                className={cn("rounded-sm px-2 py-1 text-left text-body-xs-regular hover:bg-layer-1", {
                  "bg-layer-2 text-primary": isActive,
                })}
              >
                {t(frequency ? `recurrence.${frequency}` : "recurrence.none")}
              </button>
            );
          })}
        </div>
        {recurrence?.frequency === "weekly" && (
          <div className="mt-2 flex gap-0.5 border-t border-subtle pt-2">
            {WEEKDAYS.map((day) => (
              <button
                key={day}
                type="button"
                disabled={isSaving}
                onClick={() => toggleWeekday(day)}
                className={cn("flex-1 rounded-sm py-1 text-11 font-medium", {
                  "bg-layer-2 text-primary": recurrence.weekdays.includes(day),
                  "text-tertiary hover:text-primary": !recurrence.weekdays.includes(day),
                })}
              >
                {t(`recurrence.days.${day}`)}
              </button>
            ))}
          </div>
        )}
        {recurrence?.frequency === "monthly" && (
          <label className="mt-2 flex items-center justify-between gap-2 border-t border-subtle pt-2 text-body-xs-regular">
            {t("recurrence.day_of_month")}
            <select
              value={recurrence.day_of_month ?? 1}
              disabled={isSaving}
              onChange={(e) => void save({ frequency: "monthly", day_of_month: Number(e.target.value) })}
              className="rounded-sm border border-subtle bg-surface-1 px-1 py-0.5"
            >
              {DAYS_OF_MONTH.map((day) => (
                <option key={day} value={day}>
                  {day}
                </option>
              ))}
            </select>
          </label>
        )}
        {recurrence && <p className="mt-2 px-2 text-11 text-tertiary">{getNextRunLabel(t, recurrence)}</p>}
      </Popover.Panel>
    </Popover>
  );
});
