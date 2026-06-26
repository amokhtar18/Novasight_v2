/**
 * ChartActionsMenu — Superset-style "⋯" actions on a chart (Slice A).
 *
 * View as table (re-renders the same QueryResponse as a table), View query (the
 * grounded *semantic* query — never SQL), Download CSV, and Download PNG (via the
 * renderer's toPng handle; hidden for non-ECharts table/number charts).
 */
import { useState } from "react";
import { MoreHorizontal } from "lucide-react";

import {
  Dialog,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { TableRenderer } from "@/components/chart/TableRenderer";
import type { ChartRendererHandle } from "@/components/chart/ChartRenderer";
import { downloadCsv } from "@/lib/csv";
import type { ChartSpec, QueryResponse } from "@/types/api";

interface ChartActionsMenuProps {
  spec: ChartSpec;
  data: QueryResponse;
  /** Ref to the rendered chart for PNG export; omit for table/number tiles. */
  chartHandle?: React.RefObject<ChartRendererHandle | null>;
  title?: string;
}

export function ChartActionsMenu({ spec, data, chartHandle, title = "chart" }: ChartActionsMenuProps) {
  const [open, setOpen] = useState(false);
  const [showTable, setShowTable] = useState(false);
  const [showQuery, setShowQuery] = useState(false);

  const isEcharts = spec.type !== "table" && spec.type !== "number";

  function handlePng() {
    const url = chartHandle?.current?.toPng();
    if (!url) return;
    const a = document.createElement("a");
    a.href = url;
    a.download = `${title}.png`;
    document.body.appendChild(a);
    a.click();
    a.remove();
  }

  return (
    <>
      <div className="relative">
        <button
          type="button"
          aria-label="Chart actions"
          aria-expanded={open}
          aria-haspopup="menu"
          onClick={() => setOpen((v) => !v)}
          className="inline-flex h-8 w-8 cursor-pointer items-center justify-center rounded-md border text-muted-foreground hover:bg-accent hover:text-foreground"
        >
          <MoreHorizontal className="h-4 w-4" aria-hidden />
        </button>
        {open && (
          <div
            role="menu"
            className="absolute right-0 z-30 mt-1 w-44 rounded-md border bg-popover p-1 shadow-md"
          >
            <MenuItem onClick={() => { setShowTable(true); setOpen(false); }}>View as table</MenuItem>
            <MenuItem onClick={() => { setShowQuery(true); setOpen(false); }}>View query</MenuItem>
            <MenuItem onClick={() => { downloadCsv(data, title); setOpen(false); }}>Download CSV</MenuItem>
            {isEcharts && (
              <MenuItem onClick={() => { handlePng(); setOpen(false); }}>Download PNG</MenuItem>
            )}
          </div>
        )}
      </div>

      <Dialog open={showTable} onOpenChange={setShowTable} title="View as table">
        <DialogHeader>
          <DialogTitle>{title} — table</DialogTitle>
          <DialogDescription>The same query result, shown as a table.</DialogDescription>
        </DialogHeader>
        <div className="max-h-[60vh] overflow-auto">
          <TableRenderer data={data} spec={spec} />
        </div>
      </Dialog>

      <Dialog open={showQuery} onOpenChange={setShowQuery} title="View query">
        <DialogHeader>
          <DialogTitle>Semantic query</DialogTitle>
          <DialogDescription>
            The grounded semantic query this chart runs — governed members only, no SQL.
          </DialogDescription>
        </DialogHeader>
        <pre className="max-h-[60vh] overflow-auto rounded-md bg-muted p-3 text-xs">
          {JSON.stringify(spec.query, null, 2)}
        </pre>
      </Dialog>
    </>
  );
}

function MenuItem({ onClick, children }: { onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      type="button"
      role="menuitem"
      onClick={onClick}
      className="block w-full rounded px-2 py-1.5 text-left text-sm hover:bg-accent"
    >
      {children}
    </button>
  );
}
