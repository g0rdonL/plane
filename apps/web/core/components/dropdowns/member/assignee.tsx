/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import type { ComponentProps } from "react";
// local imports
import { MemberDropdown } from "./dropdown";

type TAssigneeDropdownProps = Omit<ComponentProps<typeof MemberDropdown>, "multiple" | "value" | "onChange"> & {
  value: string[] | null | undefined;
  onChange: (assigneeIds: string[]) => void;
};

/**
 * Stories carry at most one assignee. Keeps the `assignee_ids: string[]` shape the API expects
 * but renders a single-select picker; picking the current assignee again clears it.
 */
export function AssigneeDropdown(props: TAssigneeDropdownProps) {
  const { value, onChange, showUserDetails = true, ...rest } = props;
  const current = value?.[0] ?? null;

  return (
    <MemberDropdown
      {...rest}
      // single-value mode only prints the name when asked to; multi-select printed it for one assignee
      showUserDetails={showUserDetails}
      multiple={false}
      value={current}
      onChange={(memberId) => onChange(memberId && memberId !== current ? [memberId] : [])}
    />
  );
}
