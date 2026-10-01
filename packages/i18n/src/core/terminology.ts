/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

/**
 * Aight fork: rename "work item" to "story" and "cycle" to "sprint" in the English UI.
 * Applied to translation bundles as they load, so upstream locale files stay untouched.
 * Longest phrases first so "sub-work items" is not caught by "work items".
 */
const ENGLISH_TERMS: [RegExp, string][] = [
  [/Sub-work items/g, "Sub-stories"],
  [/sub-work items/g, "sub-stories"],
  [/Sub-work item/g, "Sub-story"],
  [/sub-work item/g, "sub-story"],
  [/Work Items/g, "Stories"],
  [/Work items/g, "Stories"],
  [/work items/g, "stories"],
  [/Work Item/g, "Story"],
  [/Work item/g, "Story"],
  [/work item/g, "story"],
  [/\bCycles\b/g, "Sprints"],
  [/\bcycles\b/g, "sprints"],
  [/\bCycle\b/g, "Sprint"],
  [/\bcycle\b/g, "sprint"],
];

export const applyTerminology = (text: string): string =>
  ENGLISH_TERMS.reduce((value, [pattern, replacement]) => value.replace(pattern, replacement), text);

const transform = (value: unknown): unknown => {
  if (typeof value === "string") return applyTerminology(value);
  if (Array.isArray(value)) return value.map(transform);
  if (value && typeof value === "object")
    return Object.fromEntries(Object.entries(value).map(([key, entry]) => [key, transform(entry)]));
  return value;
};

export const applyTerminologyToBundle = (language: string, bundle: unknown): unknown =>
  language === "en" ? transform(bundle) : bundle;
