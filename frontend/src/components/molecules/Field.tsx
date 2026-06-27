import * as React from "react";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/cn";

type ControlChild = React.ReactElement<{
  id?: string;
  "aria-invalid"?: boolean | "true" | "false";
  "aria-describedby"?: string;
}>;

interface FieldProps {
  /** Visible label text. */
  label: string;
  /** Optional explicit id for the control; auto-generated when omitted. */
  htmlFor?: string;
  /** Helper text shown below the control when there is no error. */
  hint?: string;
  /** Error message; when set, links the message and marks the control invalid. */
  error?: string;
  /** Show a required asterisk. */
  required?: boolean;
  className?: string;
  /** The single control element (Input, Select, Textarea, …). */
  children: ControlChild;
}

/**
 * Field — composes Label + control + hint/error and auto-wires the a11y
 * relationships (htmlFor/id, aria-invalid, aria-describedby) so pages stop
 * hand-wiring them. Pass exactly one control as the child.
 */
export function Field({
  label,
  htmlFor,
  hint,
  error,
  required,
  className,
  children,
}: FieldProps) {
  const generatedId = React.useId();
  const controlId = htmlFor ?? children.props.id ?? generatedId;
  const hintId = hint && !error ? `${controlId}-hint` : undefined;
  const errorId = error ? `${controlId}-error` : undefined;
  const describedBy =
    [hintId, errorId].filter(Boolean).join(" ") || undefined;

  const control = React.cloneElement(children, {
    id: controlId,
    "aria-invalid": error ? true : children.props["aria-invalid"],
    "aria-describedby": describedBy ?? children.props["aria-describedby"],
  });

  return (
    <div className={cn("space-y-1.5", className)}>
      <Label htmlFor={controlId}>
        {label}
        {required && (
          <span aria-hidden className="ml-0.5 text-destructive">
            *
          </span>
        )}
      </Label>
      {control}
      {hintId && (
        <p id={hintId} className="text-xs text-muted-foreground">
          {hint}
        </p>
      )}
      {errorId && (
        <p id={errorId} className="text-xs text-destructive">
          {error}
        </p>
      )}
    </div>
  );
}

Field.displayName = "Field";
