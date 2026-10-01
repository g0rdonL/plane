/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useState } from "react";
import { observer } from "mobx-react";
import { useParams } from "next/navigation";
// plane imports
import { EpicIcon, WorkItemsIcon } from "@plane/propel/icons";
import { TOAST_TYPE, setToast } from "@plane/propel/toast";
import { CustomMenu } from "@plane/ui";
// store hooks
import { useIssueDetail } from "@/hooks/store/use-issue-detail";
// components
import { IssueIdentifier } from "@/components/issues/issue-detail/issue-identifier";
// services
import { IssueService } from "@/services/issue";

const issueService = new IssueService();

export type TIssueTypeSwitcherProps = {
  issueId: string;
  disabled: boolean;
};

export const IssueTypeSwitcher = observer(function IssueTypeSwitcher(props: TIssueTypeSwitcherProps) {
  const { issueId, disabled } = props;
  // states
  const [isConverting, setIsConverting] = useState(false);
  // router
  const { workspaceSlug } = useParams();
  // store hooks
  const {
    issue: { getIssueById },
    fetchIssue,
  } = useIssueDetail();
  // derived values
  const issue = getIssueById(issueId);

  if (!issue || !issue.project_id) return <></>;

  const isEpic = !!issue.is_epic;
  const projectId = issue.project_id;

  const handleConvert = async (toEpic: boolean) => {
    if (!workspaceSlug || toEpic === isEpic) return;
    setIsConverting(true);
    try {
      await issueService.convertWorkItem(workspaceSlug.toString(), projectId, issueId, toEpic);
      await fetchIssue(workspaceSlug.toString(), projectId, issueId);
      setToast({
        type: TOAST_TYPE.SUCCESS,
        title: "Converted",
        message: toEpic ? "This story is now an epic." : "This epic is now a story.",
      });
    } catch {
      setToast({
        type: TOAST_TYPE.ERROR,
        title: "Error",
        message: "Could not convert this story. Please try again.",
      });
    } finally {
      setIsConverting(false);
    }
  };

  const TypeIcon = isEpic ? EpicIcon : WorkItemsIcon;

  return (
    <div className="flex items-center gap-2">
      <CustomMenu
        disabled={disabled || isConverting}
        closeOnSelect
        customButton={
          <span className="flex items-center gap-1 rounded-sm bg-layer-1 px-2 py-0.5 text-11 font-medium text-secondary">
            <TypeIcon className="size-3.5" />
            {isEpic ? "Epic" : "Story"}
          </span>
        }
        placement="bottom-start"
      >
        <CustomMenu.MenuItem onClick={() => void handleConvert(false)} disabled={!isEpic}>
          <div className="flex items-center gap-2">
            <WorkItemsIcon className="size-3.5" />
            Story
          </div>
        </CustomMenu.MenuItem>
        <CustomMenu.MenuItem onClick={() => void handleConvert(true)} disabled={isEpic}>
          <div className="flex items-center gap-2">
            <EpicIcon className="size-3.5" />
            Epic
          </div>
        </CustomMenu.MenuItem>
      </CustomMenu>
      <IssueIdentifier issueId={issueId} projectId={projectId} size="md" enableClickToCopyIdentifier />
    </div>
  );
});
