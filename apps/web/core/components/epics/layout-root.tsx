/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useEffect } from "react";
import { observer } from "mobx-react";
import { useParams } from "next/navigation";
import useSWR from "swr";
// plane imports
import { EUserPermissions, EUserPermissionsLevel, ISSUE_DISPLAY_FILTERS_BY_PAGE } from "@plane/constants";
import { EIssueLayoutTypes, EIssueServiceType, EIssuesStoreType } from "@plane/types";
import { Spinner } from "@plane/ui";
// components
import { BaseCalendarRoot } from "@/components/issues/issue-layouts/calendar/base-calendar-root";
import { BaseGanttRoot } from "@/components/issues/issue-layouts/gantt";
import { BaseKanBanRoot } from "@/components/issues/issue-layouts/kanban/base-kanban-root";
import { BaseListRoot } from "@/components/issues/issue-layouts/list/base-list-root";
import { ProjectIssueQuickActions } from "@/components/issues/issue-layouts/quick-action-dropdowns";
import { BaseSpreadsheetRoot } from "@/components/issues/issue-layouts/spreadsheet/base-spreadsheet-root";
import { ProjectLevelWorkItemFiltersHOC } from "@/components/work-item-filters/filters-hoc/project-level";
import { WorkItemFiltersRow } from "@/components/work-item-filters/filters-row";
// hooks
import { useIssueDetail } from "@/hooks/store/use-issue-detail";
import { useIssues } from "@/hooks/store/use-issues";
import { useProject } from "@/hooks/store/use-project";
import { useUserPermissions } from "@/hooks/store/user";
import { useAppRouter } from "@/hooks/use-app-router";
import { IssuesStoreContext } from "@/hooks/use-issue-layout-store";

/** Epics open as full pages: turn a peek request from any layout into a navigation. */
const EpicPeekRedirect = observer(function EpicPeekRedirect() {
  const router = useAppRouter();
  const {
    peekIssue,
    setPeekIssue,
    issue: { getIssueById },
  } = useIssueDetail(EIssueServiceType.EPICS);
  const { getProjectIdentifierById } = useProject();

  useEffect(() => {
    if (!peekIssue) return;
    const epic = getIssueById(peekIssue.issueId);
    const projectIdentifier = getProjectIdentifierById(peekIssue.projectId);
    setPeekIssue(undefined);
    if (epic && projectIdentifier) {
      router.push(`/${peekIssue.workspaceSlug}/browse/${projectIdentifier}-${epic.sequence_id}/`);
    }
  }, [peekIssue, getIssueById, getProjectIdentifierById, setPeekIssue, router]);

  return null;
});

const EpicsLayout = observer(function EpicsLayout(props: { activeLayout: EIssueLayoutTypes | undefined }) {
  const { workspaceSlug } = useParams();
  const { allowPermissions } = useUserPermissions();

  const canEditPropertiesBasedOnProject = (projectId: string) =>
    allowPermissions(
      [EUserPermissions.ADMIN, EUserPermissions.MEMBER],
      EUserPermissionsLevel.PROJECT,
      workspaceSlug?.toString(),
      projectId
    );
  const layoutProps = {
    QuickActions: ProjectIssueQuickActions,
    canEditPropertiesBasedOnProject,
    isEpic: true,
  };

  switch (props.activeLayout) {
    case EIssueLayoutTypes.LIST:
      return <BaseListRoot {...layoutProps} />;
    case EIssueLayoutTypes.KANBAN:
      return <BaseKanBanRoot {...layoutProps} />;
    case EIssueLayoutTypes.CALENDAR:
      return <BaseCalendarRoot {...layoutProps} />;
    case EIssueLayoutTypes.GANTT:
      return <BaseGanttRoot isEpic />;
    case EIssueLayoutTypes.SPREADSHEET:
      return <BaseSpreadsheetRoot {...layoutProps} />;
    default:
      return null;
  }
});

export const ProjectEpicsLayoutRoot = observer(function ProjectEpicsLayoutRoot() {
  // router
  const { workspaceSlug: routerWorkspaceSlug, projectId: routerProjectId } = useParams();
  const workspaceSlug = routerWorkspaceSlug ? routerWorkspaceSlug.toString() : undefined;
  const projectId = routerProjectId ? routerProjectId.toString() : undefined;
  // hooks
  const { issues, issuesFilter } = useIssues(EIssuesStoreType.EPIC);
  // derived values
  const workItemFilters = projectId ? issuesFilter?.getIssueFilters(projectId) : undefined;
  const activeLayout = workItemFilters?.displayFilters?.layout;

  useSWR(
    workspaceSlug && projectId ? `PROJECT_EPICS_${workspaceSlug}_${projectId}` : null,
    async () => {
      if (workspaceSlug && projectId) {
        await issuesFilter?.fetchFilters(workspaceSlug, projectId);
      }
    },
    { revalidateIfStale: false, revalidateOnFocus: false }
  );

  if (!workspaceSlug || !projectId || !workItemFilters) return <></>;
  return (
    <IssuesStoreContext.Provider value={EIssuesStoreType.EPIC}>
      <ProjectLevelWorkItemFiltersHOC
        entityType={EIssuesStoreType.EPIC}
        entityId={projectId}
        filtersToShowByLayout={ISSUE_DISPLAY_FILTERS_BY_PAGE.issues.filters}
        initialWorkItemFilters={workItemFilters}
        updateFilters={issuesFilter?.updateFilterExpression.bind(issuesFilter, workspaceSlug, projectId)}
        projectId={projectId}
        workspaceSlug={workspaceSlug}
      >
        {({ filter: epicsFilter }) => (
          <div className="relative flex h-full w-full flex-col overflow-hidden">
            {epicsFilter && <WorkItemFiltersRow filter={epicsFilter} />}
            <div className="relative h-full w-full overflow-auto bg-surface-1">
              {issues?.getIssueLoader() === "mutation" && (
                <div className="shadow-sm fixed top-[70px] right-[20px] z-50 flex h-[40px] w-[40px] items-center justify-center rounded-sm bg-layer-1">
                  <Spinner className="h-4 w-4" />
                </div>
              )}
              <EpicsLayout activeLayout={activeLayout} />
            </div>
            <EpicPeekRedirect />
          </div>
        )}
      </ProjectLevelWorkItemFiltersHOC>
    </IssuesStoreContext.Provider>
  );
});
