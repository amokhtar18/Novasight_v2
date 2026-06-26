import * as React from "react";
import { cn } from "@/lib/cn";

export type CheckboxProps = React.InputHTMLAttributes<HTMLInputElement>;

/**
 * Styled native checkbox — accessible by default (keyboard + screen reader) and
 * consistent with the project's hand-rolled primitives (see Select/Dialog), without
 * pulling in a popup/primitive dependency. Wrap in a <label> for the control text.
 */
export const Checkbox = React.forwardRef<HTMLInputElement, CheckboxProps>(
  ({ className, ...props }, ref) => (
    <input
      ref={ref}
      type="checkbox"
      className={cn(
        "h-4 w-4 shrink-0 cursor-pointer rounded border-input accent-primary",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        "disabled:cursor-not-allowed disabled:opacity-50",
        className
      )}
      {...props}
    />
  )
);
Checkbox.displayName = "Checkbox";
