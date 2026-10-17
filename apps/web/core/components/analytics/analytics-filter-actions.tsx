/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

// plane web components
import { observer } from "mobx-react";
import { useParams } from "next/navigation";
// plane package imports
import { useTranslation } from "@plane/i18n";
// hooks
import { useAnalytics } from "@/hooks/store/use-analytics";
import { useProject } from "@/hooks/store/use-project";
// components
import { MemberDropdown } from "@/components/dropdowns/member/dropdown";
import { ProjectSelect } from "./select/project";

const AnalyticsFilterActions = observer(function AnalyticsFilterActions() {
  const { t } = useTranslation();
  const params = useParams();
  const { selectedProjects, updateSelectedProjects, selectedAssignees, updateSelectedAssignees } = useAnalytics();
  const { joinedProjectIds } = useProject();
  // the assignee filter is only meaningful for the momentum tab
  const isMomentumTab = params?.tabId === "momentum";
  return (
    <div className="flex items-center justify-end gap-2">
      <ProjectSelect
        value={selectedProjects}
        onChange={(val) => {
          updateSelectedProjects(val ?? []);
        }}
        projectIds={joinedProjectIds}
      />
      {isMomentumTab && (
        <MemberDropdown
          multiple
          value={selectedAssignees}
          onChange={(val) => {
            updateSelectedAssignees(val ?? []);
          }}
          buttonVariant="border-with-text"
          placeholder={t("workspace_analytics.all_members")}
          showUserDetails
          dropdownArrow
        />
      )}
      {/* <DurationDropdown
        buttonVariant="border-with-text"
        value={selectedDuration}
        onChange={(val) => {
          updateSelectedDuration(val);
        }}
        dropdownArrow
      /> */}
    </div>
  );
});

export default AnalyticsFilterActions;
