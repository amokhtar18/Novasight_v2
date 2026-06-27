import * as React from "react";
import { ChevronsUpDown } from "lucide-react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/cn";
import { controlHeight, focusRing } from "@/components/ui/_shared";

const selectVariants = cva(
  cn(
    "w-full appearance-none rounded-md border border-input bg-background/60 pr-8 text-sm shadow-sm transition-colors",
    "disabled:cursor-not-allowed disabled:opacity-50",
    focusRing
  ),
  {
    variants: {
      size: {
        sm: cn(controlHeight.sm, "pl-2.5"),
        md: cn(controlHeight.md, "pl-3"),
        lg: cn(controlHeight.lg, "pl-3.5"),
      },
    },
    defaultVariants: { size: "md" },
  }
);

export interface SelectProps
  extends Omit<React.SelectHTMLAttributes<HTMLSelectElement>, "size">,
    VariantProps<typeof selectVariants> {
  /** Mark the field invalid: sets aria-invalid and a destructive ring. */
  invalid?: boolean;
}

/**
 * Styled native <select> — accessible by default and keyboard friendly, without
 * pulling in a popup-menu dependency. Wrap <option> children as usual.
 */
export const Select = React.forwardRef<HTMLSelectElement, SelectProps>(
  ({ className, size, invalid, children, ...props }, ref) => (
    <div className="relative">
      <select
        ref={ref}
        aria-invalid={invalid ? true : undefined}
        className={cn(
          selectVariants({ size }),
          invalid && "border-destructive focus-visible:ring-destructive",
          className
        )}
        {...props}
      >
        {children}
      </select>
      <ChevronsUpDown
        className="pointer-events-none absolute right-2 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground"
        aria-hidden
      />
    </div>
  )
);
Select.displayName = "Select";
