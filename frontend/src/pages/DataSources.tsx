/**
 * DataSources — connect and manage data. Upload CSVs and browse existing
 * datasets (with status), each linking to its detail/suggestions view.
 */

import { Link, useNavigate } from "react-router-dom";
import {
  BarChart3,
  Database,
  FileSpreadsheet,
  MessageSquareText,
  Workflow,
} from "lucide-react";

import { useDatasets } from "@/api/hooks";
import { PageHeader } from "@/components/layout/PageHeader";
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

const STEPS = [
  { icon: FileSpreadsheet, label: "Upload a CSV" },
  { icon: MessageSquareText, label: "Ask a question or build a chart" },
  { icon: BarChart3, label: "Pin it to a dashboard" },
];

/** Map a dataset status to a badge variant. */
function statusVariant(status: string): BadgeProps["variant"] {
  const s = status.toLowerCase();
  if (s === "ready" || s === "loaded") return "success";
  if (s === "failed" || s === "error") return "danger";
  if (s === "pending" || s === "processing") return "warning";
  return "secondary";
}

export function DataSources() {
  const navigate = useNavigate();
  const { data: datasets, isLoading } = useDatasets();

  return (
    <div className="animate-in-up">
      <PageHeader
        title="Data sources"
        description="Upload a spreadsheet and it becomes queryable instantly — no SQL, no infrastructure."
      />

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        {/* Upload */}
        <Card className="bg-card/70 lg:col-span-2">
          <CardHeader>
            <CardTitle>Upload a CSV</CardTitle>
            <CardDescription>
              Drag a file here or click to browse. We validate it before uploading.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <UploadCard onUploaded={(d) => navigate(`/data/${d.id}`)} />
          </CardContent>
        </Card>

        {/* How it works */}
        <Card className="bg-card/70">
          <CardHeader>
            <CardTitle className="text-base">How it works</CardTitle>
          </CardHeader>
          <CardContent>
            <ol className="space-y-3" aria-label="How it works">
              {STEPS.map((s, i) => (
                <li key={s.label} className="flex items-center gap-3">
                  <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-primary/10 text-xs font-semibold text-primary">
                    {i + 1}
                  </span>
                  <s.icon className="h-4 w-4 text-muted-foreground" aria-hidden />
                  <span className="text-sm text-muted-foreground">{s.label}</span>
                </li>
              ))}
            </ol>
          </CardContent>
        </Card>
      </div>

      {/* Connecting a database lives in the Pipelines tab (the Ingest area). */}
      <p className="mt-4 text-sm text-muted-foreground">
        Connecting a SQL database?{" "}
        <Link
          to="/pipelines"
          className="inline-flex items-center gap-1 font-medium text-primary hover:underline"
        >
          <Workflow className="h-3.5 w-3.5" aria-hidden />
          Set it up in Pipelines
        </Link>
        .
      </p>

      {/* Dataset list */}
      <h3 className="mb-3 mt-8 text-sm font-medium text-muted-foreground">
        Your datasets
      </h3>

      {isLoading ? (
        <div className="space-y-2">
          <Skeleton className="h-16 w-full" />
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
  );
}
