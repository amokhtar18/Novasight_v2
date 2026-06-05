/**
 * EmptyState — a friendly placeholder for "nothing here yet" moments.
 *
 * Used for first-run/empty screens (no datasets, no chart yet) so a non-technical
 * user always sees guidance instead of a blank panel.
 */

import * as React from "react";
import { cn } from "@/lib/cn";

interface EmptyStateProps {
  /** Decorative icon (e.g. a lucide icon element). */
  icon?: React.ReactNode;
  title: string;
  description?: React.ReactNode;
  /** Optional call-to-action (e.g. a Button). */
  action?: React.ReactNode;
  className?: string;
}

export function EmptyState({
  icon,
  title,
  description,
  action,
  className,
}: EmptyStateProps) {
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center rounded-lg border border-dashed border-muted-foreground/30 p-8 text-center",
        className
      )}
    >
      {icon && (
        <div className="mb-3 text-muted-foreground/70" aria-hidden>
          {icon}
        </div>
      )}
      <p className="text-sm font-medium text-foreground">{title}</p>
      {description && (
        <p className="mt-1 max-w-sm text-sm text-muted-foreground">{description}</p>
      )}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}
