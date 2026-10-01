/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { PageHead } from "@/components/core/page-title";
import { MySprintRoot } from "@/components/my-sprint/root";

export default function MySprintPage() {
  return (
    <>
      <PageHead title="My sprint" />
      <MySprintRoot />
    </>
  );
}
