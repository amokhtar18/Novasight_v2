import * as React from "react";
import { cn } from "@/lib/cn";
import { focusRing } from "@/components/ui/_shared";

const textareaBase = cn(
  "flex w-full resize-y rounded-md border border-input bg-background/60 px-3 py-2 text-sm shadow-sm transition-colors",
  "placeholder:text-muted-foreground disabled:cursor-not-allowed disabled:opacity-50",
  focusRing
);

export interface TextareaProps
  extends React.TextareaHTMLAttributes<HTMLTextAreaElement> {
  /** Mark the field invalid: sets aria-invalid and a destructive ring. */
  invalid?: boolean;
}

export const Textarea = React.forwardRef<HTMLTextAreaElement, TextareaProps>(
  ({ className, invalid, rows = 4, ...props }, ref) => (
    <textarea
      ref={ref}
      rows={rows}
      aria-invalid={invalid ? true : undefined}
      className={cn(
        textareaBase,
        invalid && "border-destructive focus-visible:ring-destructive",
        className
      )}
      {...props}
    />
  )
);
Textarea.displayName = "Textarea";
