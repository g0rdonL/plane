/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

// plane imports
import type { TFilterProperty, TSupportedOperators } from "@plane/types";
import { EQUALITY_OPERATOR, COLLECTION_OPERATOR } from "@plane/types";
// local imports
import type { TCreateFilterConfigParams, IFilterIconConfig, TCreateFilterConfig } from "../../../rich-filters";
import { createFilterConfig, getMultiSelectConfig, createOperatorConfigEntry } from "../../../rich-filters";

// ------------ Sprint filter (Aight fork) ------------

export type TSprintFilterValue = "current" | "next";

/** Relative sprints: the server resolves them to each project's cycles for this / next Monday-Sunday week. */
export const SPRINT_FILTER_OPTIONS: { key: TSprintFilterValue; title: string }[] = [
  { key: "current", title: "This sprint" },
  { key: "next", title: "Next sprint" },
];

export type TCreateSprintFilterParams = TCreateFilterConfigParams & IFilterIconConfig<TSprintFilterValue>;

export const getSprintMultiSelectConfig = (
  params: TCreateSprintFilterParams,
  singleValueOperator: TSupportedOperators
) =>
  getMultiSelectConfig<{ key: TSprintFilterValue; title: string }, TSprintFilterValue, TSprintFilterValue>(
    {
      items: SPRINT_FILTER_OPTIONS,
      getId: (sprint) => sprint.key,
      getLabel: (sprint) => sprint.title,
      getValue: (sprint) => sprint.key,
      getIconData: (sprint) => sprint.key,
    },
    {
      singleValueOperator,
      ...params,
    },
    {
      getOptionIcon: params.getOptionIcon,
    }
  );

export const getSprintFilterConfig =
  <P extends TFilterProperty>(key: P): TCreateFilterConfig<P, TCreateSprintFilterParams> =>
  (params: TCreateSprintFilterParams) =>
    createFilterConfig<P>({
      id: key,
      label: "Sprint",
      ...params,
      icon: params.filterIcon,
      supportedOperatorConfigsMap: new Map([
        createOperatorConfigEntry(COLLECTION_OPERATOR.IN, params, (updatedParams) =>
          getSprintMultiSelectConfig(updatedParams, EQUALITY_OPERATOR.EXACT)
        ),
      ]),
    });
