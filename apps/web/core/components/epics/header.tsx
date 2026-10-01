/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useState } from "react";
import { observer } from "mobx-react";
import { useParams } from "next/navigation";
// plane imports
import { EUserPermissions, EUserPermissionsLevel } from "@plane/constants";
import { Button } from "@plane/propel/button";
import { EpicIcon } from "@plane/propel/icons";
import { EIssuesStoreType } from "@plane/types";
import { Breadcrumbs, Header } from "@plane/ui";
// components
import { CommonProjectBreadcrumbs } from "@/components/breadcrumbs/common";
import { BreadcrumbLink } from "@/components/common/breadcrumb-link";
import { CountChip } from "@/components/common/count-chip";
import { CreateUpdateEpicModal } from "@/components/epic-modal/modal";
import { HeaderFilters } from "@/components/issues/filters";
// hooks
import { useIssues } from "@/hooks/store/use-issues";
import { useProject } from "@/hooks/store/use-project";
import { useUserPermissions } from "@/hooks/store/user";
import { useAppRouter } from "@/hooks/use-app-router";

export const EpicsHeader = observer(function EpicsHeader() {
  // states
  const [isCreateModalOpen, setIsCreateModalOpen] = useState(false);
  // router
  const router = useAppRouter();
  const { workspaceSlug, projectId } = useParams();
  // store hooks
  const {
    issues: { getGroupIssueCount },
  } = useIssues(EIssuesStoreType.EPIC);
  const { currentProjectDetails, loader } = useProject();
  const { allowPermissions } = useUserPermissions();
  // derived values
  const epicsCount = getGroupIssueCount(undefined, undefined, false);
  const canUserCreateEpic = allowPermissions(
    [EUserPermissions.ADMIN, EUserPermissions.MEMBER],
    EUserPermissionsLevel.PROJECT
  );

  return (
    <>
      <CreateUpdateEpicModal
        isOpen={isCreateModalOpen}
        onClose={() => setIsCreateModalOpen(false)}
        data={{ project_id: projectId?.toString() }}
        isProjectSelectionDisabled
      />
      <Header>
        <Header.LeftItem>
          <div className="flex items-center gap-2.5">
            <Breadcrumbs onBack={() => router.back()} isLoading={loader === "init-loader"} className="flex-grow-0">
              <CommonProjectBreadcrumbs workspaceSlug={workspaceSlug?.toString()} projectId={projectId?.toString()} />
              <Breadcrumbs.Item
                component={
                  <BreadcrumbLink
                    label="Epics"
                    href={`/${workspaceSlug}/projects/${projectId}/epics/`}
                    icon={<EpicIcon className="h-4 w-4 text-tertiary" />}
                    isLast
                  />
                }
                isLast
              />
            </Breadcrumbs>
            {epicsCount && epicsCount > 0 ? <CountChip count={epicsCount} /> : null}
          </div>
        </Header.LeftItem>
        <Header.RightItem>
          <div className="hidden gap-2 md:flex">
            {workspaceSlug && projectId && (
              <HeaderFilters
                projectId={projectId.toString()}
                currentProjectDetails={currentProjectDetails}
                workspaceSlug={workspaceSlug.toString()}
                canUserCreateIssue={canUserCreateEpic}
                storeType={EIssuesStoreType.EPIC}
              />
            )}
          </div>
          {canUserCreateEpic && (
            <Button variant="primary" size="lg" onClick={() => setIsCreateModalOpen(true)}>
              <div className="block sm:hidden">Epic</div>
              <div className="hidden sm:block">Add epic</div>
            </Button>
          )}
        </Header.RightItem>
      </Header>
    </>
  );
});
