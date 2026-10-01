/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { API_BASE_URL } from "@plane/constants";
import type { TSprintCapacity } from "@plane/types";
import { APIService } from "@/services/api.service";

export class SprintCapacityService extends APIService {
  constructor() {
    super(API_BASE_URL);
  }

  async getMySprintCapacity(): Promise<TSprintCapacity> {
    return this.get(`/api/users/me/sprint-capacity/`)
      .then((response) => response?.data)
      .catch((error) => {
        throw error?.response?.data;
      });
  }
}
