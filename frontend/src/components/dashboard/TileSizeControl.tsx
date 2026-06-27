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

  const [draftW, setDraftW] = useState(w);
  const [draftH, setDraftH] = useState(h);
  const [lastW, setLastW] = useState(w);
  const [lastH, setLastH] = useState(h);
  if (lastW !== w) { setLastW(w); setDraftW(w); }
  if (lastH !== h) { setLastH(h); setDraftH(h); }

  function commit() {
    onResize(clamp(Number(draftW)), clamp(Number(draftH)));
  }

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
        aria-haspopup="true"
        onClick={() => setOpen((v) => !v)}
        className="rounded p-1 text-muted-foreground hover:bg-accent hover:text-foreground"
      >
        <Maximize2 className="h-4 w-4" />
      </button>
      {open && (
        <div
          role="group"
          aria-label={`Resize ${title}`}
          className="absolute right-0 z-[var(--z-dropdown)] mt-1 w-44 space-y-2 rounded-md border bg-popover p-3 text-popover-foreground shadow-[var(--elevation-2)]"
        >
          <label className="flex items-center justify-between gap-2 text-xs">
            Width
            <input
              type="number"
              min={MIN}
              max={MAX}
              value={draftW}
              aria-label={`Width of ${title}`}
              onChange={(e) => setDraftW(Number(e.target.value))}
              onBlur={commit}
              onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); commit(); } }}
              className="h-7 w-16 rounded border bg-transparent px-2 text-right text-sm"
            />
          </label>
          <label className="flex items-center justify-between gap-2 text-xs">
            Height
            <input
              type="number"
              min={MIN}
              max={MAX}
              value={draftH}
              aria-label={`Height of ${title}`}
              onChange={(e) => setDraftH(Number(e.target.value))}
              onBlur={commit}
              onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); commit(); } }}
              className="h-7 w-16 rounded border bg-transparent px-2 text-right text-sm"
            />
          </label>
        </div>
      )}
    </div>
  );
}
