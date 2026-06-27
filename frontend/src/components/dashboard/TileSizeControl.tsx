/**
 * TileSizeControl — keyboard-accessible width/height control for a tile (edit
 * mode). The accessibility fallback for pointer-only gridstack drag-resize: it
 * emits the new size through `onResize`, which the grid applies via gridstack
 * (same persist path as a drag). Full keyboard-drag is a known gridstack limit.
 */
import { useEffect, useRef, useState } from "react";
import { Maximize2 } from "lucide-react";

const MIN = 1;
const MAX = 12;

function clamp(v: number): number {
  const n = Math.round(v);
  if (Number.isNaN(n)) return MIN;
  return Math.max(MIN, Math.min(MAX, n));
}

export function TileSizeControl({
  title,
  w,
  h,
  onResize,
}: {
  title: string;
  w: number;
  h: number;
  onResize: (w: number, h: number) => void;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    function onClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("keydown", onKey);
    document.addEventListener("mousedown", onClick);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("mousedown", onClick);
    };
  }, [open]);

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        aria-label={`Size of ${title}`}
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className="rounded p-1 text-muted-foreground hover:bg-accent hover:text-foreground"
      >
        <Maximize2 className="h-4 w-4" />
      </button>
      {open && (
        <div className="absolute right-0 z-20 mt-1 w-44 space-y-2 rounded-md border bg-popover p-3 text-popover-foreground shadow-md">
          <label className="flex items-center justify-between gap-2 text-xs">
            Width
            <input
              type="number"
              min={MIN}
              max={MAX}
              value={w}
              aria-label={`Width of ${title}`}
              onChange={(e) => onResize(clamp(Number(e.target.value)), h)}
              className="h-7 w-16 rounded border bg-transparent px-2 text-right text-sm"
            />
          </label>
          <label className="flex items-center justify-between gap-2 text-xs">
            Height
            <input
              type="number"
              min={MIN}
              max={MAX}
              value={h}
              aria-label={`Height of ${title}`}
              onChange={(e) => onResize(w, clamp(Number(e.target.value)))}
              className="h-7 w-16 rounded border bg-transparent px-2 text-right text-sm"
            />
          </label>
        </div>
      )}
    </div>
  );
}
