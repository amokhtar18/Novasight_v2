/**
 * SaveChartButton — persist a ChartSpec to the backend charts API.
 *
 * Unlike AddToDashboard (client-side localStorage), this saves the chart
 * server-side so it survives across devices and can later be composed onto a
 * persisted dashboard. Opens a small dialog to name the chart, then POSTs it.
 */

import { useState } from "react";
import { Save } from "lucide-react";
import { toast } from "sonner";

import { useCreateChart } from "@/api/hooks";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Dialog,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import type { ButtonProps } from "@/components/ui/button";
import type { ChartSourceKind, ChartSpec } from "@/types/api";

interface SaveChartButtonProps {
  spec: ChartSpec;
  /** Pre-fills the name field (e.g. the chart title). */
  defaultName: string;
  /** Where the spec reads its data (defaults to "semantic"). */
  sourceKind?: ChartSourceKind;
  /** The model/dataset id the spec references, for listing + re-grounding. */
  sourceRef?: string | null;
  variant?: ButtonProps["variant"];
  size?: ButtonProps["size"];
  className?: string;
}

export function SaveChartButton({
  spec,
  defaultName,
  sourceKind = "semantic",
  sourceRef = null,
  variant = "default",
  size = "sm",
  className,
}: SaveChartButtonProps) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState(defaultName);
  const { mutate, isPending } = useCreateChart();

  // Seed the name from the current suggested title each time the dialog opens.
  function openDialog() {
    setName(defaultName);
    setOpen(true);
  }

  function handleSave() {
    const trimmed = name.trim();
    if (!trimmed) return;
    mutate(
      { name: trimmed, spec, source_kind: sourceKind, source_ref: sourceRef },
      {
        onSuccess: (chart) => {
          setOpen(false);
          toast.success(`Saved “${chart.name}”`);
        },
        onError: (err) => {
          toast.error(err instanceof Error ? err.message : "Could not save the chart");
        },
      }
    );
  }

  return (
    <>
      <Button
        type="button"
        variant={variant}
        size={size}
        className={className}
        onClick={openDialog}
      >
        <Save className="h-4 w-4" aria-hidden />
        Save chart
      </Button>

      <Dialog open={open} onOpenChange={setOpen} title="Save chart">
        <DialogHeader>
          <DialogTitle>Save chart</DialogTitle>
          <DialogDescription>
            Saved charts are stored on the server and can be added to a dashboard.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-1.5">
          <Label htmlFor="save-chart-name">Chart name</Label>
          <Input
            id="save-chart-name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g. Total amount by region"
            autoFocus
          />
        </div>

        <DialogFooter>
          <Button variant="ghost" onClick={() => setOpen(false)}>
            Cancel
          </Button>
          <Button onClick={handleSave} disabled={isPending || !name.trim()}>
            <Save className="h-4 w-4" aria-hidden />
            {isPending ? "Saving…" : "Save"}
          </Button>
        </DialogFooter>
      </Dialog>
    </>
  );
}
