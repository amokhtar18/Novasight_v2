import { cn } from "@/lib/cn";

/** Loading placeholder with a subtle shimmer. */
export function Skeleton({
  className,
  ...props
}: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn(
        "relative overflow-hidden rounded-md bg-muted/60 animate-shimmer",
        className
      )}
      aria-hidden
      {...props}
    />
  );
}
