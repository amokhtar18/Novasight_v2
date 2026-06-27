import { useState } from "react";
import { BookMarked } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { SavedChartsList } from "@/components/chart/SavedChartsList";
import type { ChartSpec } from "@/types/api";

export function SavedChartsDrawer({ onEdit }: { onEdit: (spec: ChartSpec) => void }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <Button variant="outline" size="sm" onClick={() => setOpen(true)}>
        <BookMarked className="h-4 w-4" aria-hidden /> Saved charts
      </Button>
      <Dialog open={open} onOpenChange={setOpen} title="Saved charts">
        <SavedChartsList onEdit={(spec) => { onEdit(spec); setOpen(false); }} />
      </Dialog>
    </>
  );
}
