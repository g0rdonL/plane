/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { API_BASE_URL } from "@plane/constants";
import type { TSprintCapacity, TSprintCapacityPerson, TSprintCapacitySettings } from "@plane/types";
import { APIService } from "@/services/api.service";

export class SprintCapacityService extends APIService {
  constructor() {
    super(API_BASE_URL);
  }

  async getSprintCapacity(userId?: string): Promise<TSprintCapacity> {
    return this.get(`/api/users/me/sprint-capacity/`, { params: userId ? { user_id: userId } : {} })
      .then((response) => response?.data)
      .catch((error) => {
        throw error?.response?.data;
      });
  }

  async updateMyCapacity(data: { planned: number; buffer: number }): Promise<TSprintCapacitySettings> {
    return this.patch(`/api/users/me/sprint-capacity/`, data)
      .then((response) => response?.data)
      .catch((error) => {
        throw error?.response?.data;
      });
  }

  async getPeople(): Promise<TSprintCapacityPerson[]> {
    return this.get(`/api/users/me/sprint-capacity/people/`)
      .then((response) => response?.data)
      .catch((error) => {
        throw error?.response?.data;
      });
  }
}
