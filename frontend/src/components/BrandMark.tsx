/**
 * BrandMark — the NovaSight infinity/Möbius mark, rendered as an inline SVG so
 * it inherits the active theme via a gradient (primary → info). Echoes the
 * brushed-metal Möbius strip in /branding.
 */

import { cn } from "@/lib/cn";

export function BrandMark({
  className,
  title = "NovaSight",
}: {
  className?: string;
  title?: string;
}) {
  return (
    <svg
      viewBox="0 0 64 32"
      role="img"
      aria-label={title}
      className={cn("h-6 w-auto", className)}
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
    >
      <defs>
        <linearGradient id="brandStroke" x1="0" y1="0" x2="64" y2="32" gradientUnits="userSpaceOnUse">
          <stop offset="0" stopColor="hsl(var(--primary))" />
          <stop offset="1" stopColor="hsl(var(--info))" />
        </linearGradient>
      </defs>
      {/* Lemniscate (∞) — a continuous Möbius-like loop. */}
      <path
        d="M16 16c0-6 5-9 9-5l14 10c4 4 9 1 9-5s-5-9-9-5L25 26c-4 4-9 1-9-5z"
        stroke="url(#brandStroke)"
        strokeWidth="3.2"
        strokeLinejoin="round"
        strokeLinecap="round"
      />
    </svg>
  );
}
