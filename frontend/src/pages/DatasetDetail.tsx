/**
 * DatasetDetail — one dataset's home. Shows metadata and, on request, AI-
 * generated chart suggestions (each grounded on the dataset's profiled schema).
 * Suggestions can be pinned to a dashboard or opened in the builder.
 */

import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  ArrowLeft,
  Database,
  Lightbulb,
  Sparkles,
  Wand2,
} from "lucide-react";

import { useDatasets, useSuggestions } from "@/api/hooks";
import { PageHeader } from "@/components/layout/PageHeader";
import { SpecChart } from "@/components/chart/SpecChart";
import { AddToDashboard } from "@/components/dashboard/AddToDashboard";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/ui/empty-state";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { formatBytes, formatRelativeTime } from "@/lib/format";

export function DatasetDetail() {
  const { datasetId = "" } = useParams();
  const { data: datasets } = useDatasets();
  const dataset = datasets?.find((d) => d.id === datasetId);

  const [requested, setRequested] = useState(false);
  const {
    data: suggestions,
    isFetching,
    isError,
    error,
  } = useSuggestions(datasetId, requested);

  return (
    <div className="animate-in-up">
      <Link
        to="/data"
        className="mb-4 inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="h-4 w-4" aria-hidden />
        All datasets
      </Link>

      <PageHeader
        title={dataset?.name ?? "Dataset"}
        description={
          dataset
            ? `${dataset.original_filename} · ${formatBytes(dataset.size_bytes)} · added ${formatRelativeTime(dataset.created_at)}`
            : "Loading dataset…"
        }
        actions={
          <>
            {dataset && <Badge variant="outline">{dataset.status}</Badge>}
            <Button asChild variant="outline" size="sm">
              <Link to="/build">
                <Wand2 className="h-4 w-4" aria-hidden />
                Open in builder
              </Link>
            </Button>
            <Button asChild size="sm">
              <Link to="/explore">
                <Sparkles className="h-4 w-4" aria-hidden />
                Ask AI
              </Link>
            </Button>
          </>
        }
      />

      <Card className="bg-card/70">
        <CardHeader className="flex-row items-center justify-between space-y-0">
          <CardTitle className="flex items-center gap-2 text-base">
            <Lightbulb className="h-4 w-4 text-primary" aria-hidden />
            AI chart suggestions
          </CardTitle>
          {requested && (
            <Button
              size="sm"
              variant="ghost"
              onClick={() => setRequested(false)}
              disabled={isFetching}
            >
              Reset
            </Button>
          )}
        </CardHeader>
        <CardContent>
          {!requested ? (
            <EmptyState
              icon={<Lightbulb className="h-6 w-6" />}
              title="Discover charts automatically"
              description="We profile this dataset and propose a handful of useful charts you can pin or refine."
              action={
                <Button onClick={() => setRequested(true)}>
                  <Sparkles className="h-4 w-4" aria-hidden />
                  Generate suggestions
                </Button>
              }
            />
          ) : isFetching ? (
            <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
              <Skeleton className="h-72 w-full" />
              <Skeleton className="h-72 w-full" />
            </div>
          ) : isError ? (
            <Alert variant="destructive">
              <AlertTitle>Couldn't generate suggestions</AlertTitle>
              <AlertDescription>
                {error instanceof Error ? error.message : "Please try again."}
              </AlertDescription>
            </Alert>
          ) : suggestions && suggestions.suggestions.length ? (
            <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
              {suggestions.suggestions.map((s, i) => (
                <div key={i} className="rounded-xl border bg-background/40 p-4">
                  <div className="mb-1 flex items-start justify-between gap-2">
                    <h3 className="text-sm font-medium">{s.title}</h3>
                    <Badge variant="outline">{s.spec.type}</Badge>
                  </div>
                  <p className="mb-3 text-xs text-muted-foreground">{s.rationale}</p>
                  <SpecChart spec={s.spec} title={s.title} />
                  <div className="mt-3 flex justify-end">
                    <AddToDashboard spec={s.spec} title={s.title} />
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <EmptyState
              icon={<Database className="h-6 w-6" />}
              title="No suggestions"
              description={
                suggestions?.note ??
                "This dataset didn't yield automatic suggestions. Try the builder instead."
              }
            />
          )}
        </CardContent>
      </Card>
    </div>
  );
}
