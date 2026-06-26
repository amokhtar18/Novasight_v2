/**
 * Immutable helper for patching a typed family slice inside ChartOptions.type_options.
 *
 * Usage:
 *   setOptions(setFamily(options, "cartesian", { stacked: true }))
 *
 * Guarantees that neither `options` nor `options.type_options` nor the family object
 * is mutated — each level is spread into a new object.
 */

import type { ChartOptions, TypeOptions } from "@/types/api";

export function setFamily<K extends keyof NonNullable<TypeOptions>>(
  options: ChartOptions,
  family: K,
  patch: Partial<NonNullable<NonNullable<TypeOptions>[K]>>
): ChartOptions {
  const to = options.type_options ?? {};
  return {
    ...options,
    type_options: {
      ...to,
      [family]: { ...(to[family] ?? {}), ...patch },
    },
  };
}
