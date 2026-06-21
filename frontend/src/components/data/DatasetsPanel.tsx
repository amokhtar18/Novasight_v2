/**
 * DatasetsPanel — CSV upload + the tenant's datasets, as an embeddable panel.
 *
 * Extracted from the old standalone Data sources page so it can live inside the
 * Ingest hub's "Data sources" tab (#1) alongside SQL/file source connections. CSV
 * upload remains the file on-ramp: upload here, model it, then chart it.
 */

import { Link, useNavigate } from "react-router-dom";
import { Database } from "lucide-react";

import { useDatasets } from "@/api/hooks";
import { UploadCard } from "@/components/data/UploadCard";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/ui/empty-state";
import { formatBytes, formatRelativeTime } from "@/lib/format";
import type { BadgeProps } from "@/components/ui/badge";

/** Map a dataset status to a badge variant. */
function statusVariant(status: string): BadgeProps["variant"] {
  const s = status.toLowerCase();
  if (s === "ready" || s === "loaded") return "success";
  if (s === "failed" || s === "error") return "danger";
  if (s === "pending" || s === "processing") return "warning";
  return "secondary";
}

export function DatasetsPanel() {
  const navigate = useNavigate();
  const { data: datasets, isLoading } = useDatasets();

  return (
    <Card className="bg-card/70">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <Database className="h-4 w-4" aria-hidden />
          Files (CSV)
        </CardTitle>
        <CardDescription>
          Upload a spreadsheet and it becomes queryable instantly — no SQL, no infrastructure.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-6">
        <UploadCard onUploaded={(d) => navigate(`/data/${d.id}`)} />

        <div>
          <h3 className="mb-3 text-sm font-medium text-muted-foreground">Your datasets</h3>
          {isLoading ? (
            <div className="space-y-2">
              <Skeleton className="h-16 w-full" />
              <Skeleton className="h-16 w-full" />
            </div>
          ) : datasets && datasets.length ? (
            <div className="overflow-hidden rounded-xl border bg-card/70">
              <ul className="divide-y divide-border/60">
                {datasets.map((d) => (
                  <li key={d.id}>
                    <Link
                      to={`/data/${d.id}`}
                      className="flex items-center justify-between gap-4 p-4 transition-colors hover:bg-accent/40"
                    >
                      <div className="flex min-w-0 items-center gap-3">
                        <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
                          <Database className="h-5 w-5" aria-hidden />
                        </span>
                        <div className="min-w-0">
                          <p className="truncate text-sm font-medium">{d.name}</p>
                          <p className="truncate text-xs text-muted-foreground">
                            {d.original_filename} · {formatBytes(d.size_bytes)} ·{" "}
                            {formatRelativeTime(d.created_at)}
                          </p>
                        </div>
                      </div>
                      <Badge variant={statusVariant(d.status)}>{d.status}</Badge>
                    </Link>
                  </li>
                ))}
              </ul>
            </div>
          ) : (
            <EmptyState
              icon={<Database className="h-6 w-6" />}
              title="No datasets yet"
              description="Upload your first CSV above to get started."
            />
          )}
        </div>
      </CardContent>
    </Card>
  );
}
