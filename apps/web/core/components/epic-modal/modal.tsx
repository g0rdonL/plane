/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import React from "react";
import type { TIssue } from "@plane/types";
import { EIssuesStoreType } from "@plane/types";
import { CreateUpdateIssueModal } from "@/components/issues/issue-modal/modal";

export interface EpicModalProps {
  data?: Partial<TIssue>;
  isOpen: boolean;
  onClose: () => void;
  beforeFormSubmit?: () => Promise<void>;
  onSubmit?: (res: TIssue) => Promise<void>;
  fetchIssueDetails?: boolean;
  primaryButtonText?: {
    default: string;
    loading: string;
  };
  isProjectSelectionDisabled?: boolean;
}

export function CreateUpdateEpicModal(props: EpicModalProps) {
  const { data, primaryButtonText, ...rest } = props;
  return (
    <CreateUpdateIssueModal
      {...rest}
      data={data}
      storeType={EIssuesStoreType.EPIC}
      withDraftIssueWrapper={false}
      modalTitle={data?.id ? "Update epic" : "Create epic"}
      primaryButtonText={
        primaryButtonText ?? (data?.id ? undefined : { default: "Create epic", loading: "Creating epic" })
      }
    />
  );
}
