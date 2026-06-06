import { Loader2 } from "lucide-react";
import { cn } from "@/lib/cn";

/** Accessible loading spinner. */
export function Spinner({
  className,
  label = "Loading",
}: {
  className?: string;
  label?: string;
}) {
  return (
    <Loader2
      role="status"
      aria-label={label}
      className={cn("h-4 w-4 animate-spin text-muted-foreground", className)}
    />
  );
}
