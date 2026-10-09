/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

// plane imports
import { cn } from "@plane/utils";

type Props<T extends number> = {
  value: T;
  options: { value: T; label: string }[];
  onChange: (value: T) => void;
};

function WindowSelector<T extends number>({ value, options, onChange }: Props<T>) {
  return (
    <div className="flex shrink-0 items-center gap-0.5 rounded-md border border-subtle bg-layer-1 p-0.5">
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          onClick={() => onChange(option.value)}
          className={cn(
            "rounded-sm px-2 py-0.5 text-11 font-medium transition-colors",
            option.value === value ? "bg-layer-2 text-primary" : "text-tertiary hover:text-primary"
          )}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}

export default WindowSelector;
