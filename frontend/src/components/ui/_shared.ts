/**
 * Shared control primitives contract.
 *
 * `controlHeight` binds the sm/md/lg control-size tokens (defined in index.css)
 * to Tailwind height classes, so Button/Input/Select/Textarea share one height
 * scale. `focusRing` is the single source of truth for the focus-visible ring,
 * so every interactive control focuses identically.
 */

/** Control-height scale, driven by the --control-h-* tokens in index.css. */
export const controlHeight = {
  sm: "h-[var(--control-h-sm)]",
  md: "h-[var(--control-h-md)]",
  lg: "h-[var(--control-h-lg)]",
} as const;

/** Unified focus-visible ring shared by every interactive control. */
export const focusRing =
  "outline-none ring-offset-background focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2";
