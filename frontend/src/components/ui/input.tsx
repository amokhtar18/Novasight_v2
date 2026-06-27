import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/cn";
import { controlHeight, focusRing } from "@/components/ui/_shared";

const inputVariants = cva(
  cn(
    "flex w-full rounded-md border border-input bg-background/60 text-sm shadow-sm transition-colors",
    "placeholder:text-muted-foreground disabled:cursor-not-allowed disabled:opacity-50",
    focusRing
  ),
  {
    variants: {
      size: {
        sm: cn(controlHeight.sm, "px-2.5 py-1"),
        md: cn(controlHeight.md, "px-3 py-1"),
        lg: cn(controlHeight.lg, "px-3.5 py-2"),
      },
    },
    defaultVariants: { size: "md" },
  }
);

export interface InputProps
  extends Omit<React.InputHTMLAttributes<HTMLInputElement>, "size">,
    VariantProps<typeof inputVariants> {
  /** Mark the field invalid: sets aria-invalid and a destructive ring. */
  invalid?: boolean;
}

export const Input = React.forwardRef<HTMLInputElement, InputProps>(
  ({ className, type = "text", size, invalid, ...props }, ref) => (
    <input
      ref={ref}
      type={type}
      aria-invalid={invalid ? true : undefined}
      className={cn(
        inputVariants({ size }),
        invalid && "border-destructive focus-visible:ring-destructive",
        className
      )}
      {...props}
    />
  )
);
Input.displayName = "Input";
