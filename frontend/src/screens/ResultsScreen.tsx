/**
 * ResultsScreen — query a dataset and render a chart.
 *
 * The screen exposes two paths to a chart:
 *
 * 1. AI path (NLChartPanel) — the user types a natural-language description;
 *    the backend generates a ChartSpec + pre-fetched QueryResponse and the
 *    SAME ChartRenderer displays it.
 * 2. Manual path — the user picks a dimension and chart type; the screen
 *    runs a structured query and feeds the result into ChartRenderer.
 *
 * The manual builder is always visible and serves as the graceful fallback when
 * the AI path returns a 422 (ungroundable spec). The NLChartPanel calls the
 * `onFallback` prop which scrolls focus to / highlights the manual section.
 */

import { useRef, useState } from "react";
import { ArrowLeft, BarChart3, SlidersHorizontal } from "lucide-react";

import { useDatasetQuery } from "@/api/hooks";
import { useAppStore } from "@/store/appStore";
import { ChartRenderer } from "@/components/chart/ChartRenderer";
import { NLChartPanel } from "@/components/chart/NLChartPanel";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Label } from "@/components/ui/label";
import { EmptyState } from "@/components/ui/empty-state";
import type { ChartSpec, ChartType, QueryRequest } from "@/types/api";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Build a safe SQL-identifier-like column name from a free-text header. */
function toIdentifier(raw: string): string {
  // Replace non-word characters with underscores, ensure it starts with a letter.
  const sanitised = raw.replace(/[^A-Za-z0-9_]/g, "_");
  return /^[A-Za-z_]/.test(sanitised) ? sanitised : `col_${sanitised}`;
}

/** Build the default query: count rows grouped by the chosen dimension. */
function buildDefaultQuery(dimension: string, limit: number): QueryRequest {
  return {
    dimensions: [dimension],
    metrics: [{ function: "count" }],
    limit,
  };
}

/** Build a ChartSpec from the user's dimension choice, chart type, and query. */
function buildDefaultSpec(
  dimension: string,
  chartType: ChartType,
  datasetId: string | null,
  query: QueryRequest
): ChartSpec {
  return {
    version: "1",
    type: chartType,
    query: { dataset_id: datasetId, query },
    encoding: {
      x: dimension,
      series: [{ field: "count", name: "Count" }],
    },
    options: { title: `Count by ${dimension}` },
  };
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

const CHART_TYPES: ChartType[] = ["bar", "line", "pie"];
const DEFAULT_LIMIT = 50;

export function ResultsScreen() {
  const { selectedDatasetId, reset } = useAppStore((s) => ({
    selectedDatasetId: s.selectedDatasetId,
    reset: s.reset,
  }));

  // User-controlled dimension name and chart type.
  const [dimension, setDimension] = useState("category");
  const [chartType, setChartType] = useState<ChartType>("bar");

  // Ref to the manual builder section — used to scroll it into view when
  // the AI path falls back (422 ungroundable spec).
  const manualSectionRef = useRef<HTMLDivElement>(null);

  function handleAIFallback() {
    manualSectionRef.current?.scrollIntoView({
      behavior: "smooth",
      block: "start",
    });
    manualSectionRef.current?.focus({ preventScroll: true });
  }

  // Build the query and spec from current controls.
  const queryRequest = buildDefaultQuery(toIdentifier(dimension), DEFAULT_LIMIT);
  const spec = buildDefaultSpec(
    toIdentifier(dimension),
    chartType,
    selectedDatasetId,
    queryRequest
  );

  const { data, isLoading, isError, error } = useDatasetQuery(
    selectedDatasetId,
    queryRequest
  );

  return (
    <div className="min-h-screen bg-background p-4 space-y-4">
      {/* Navigation */}
      <div className="flex items-center gap-2">
        <Button
          variant="ghost"
          size="sm"
          onClick={reset}
          aria-label="Back to upload"
        >
          <ArrowLeft className="h-4 w-4 mr-1" aria-hidden />
          Upload another file
        </Button>
      </div>

      {/* AI-powered NL→chart panel */}
      <NLChartPanel onFallback={handleAIFallback} />

      {/* Manual builder — always visible; serves as the graceful fallback */}
      <div ref={manualSectionRef} tabIndex={-1} className="outline-none">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <SlidersHorizontal className="h-4 w-4" aria-hidden />
            Build it yourself
          </CardTitle>
          <CardDescription>
            Prefer to point and click? Choose a column to group by and a chart type.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {/* Simple controls to drive the chart spec */}
          <div className="flex flex-wrap gap-4">
            <div className="flex flex-col gap-1">
              <Label htmlFor="dimension-input">Group by column</Label>
              <input
                id="dimension-input"
                type="text"
                value={dimension}
                onChange={(e) => setDimension(e.target.value)}
                placeholder="e.g. category"
                className="h-9 rounded-md border border-input bg-background px-3 py-1 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                aria-describedby="dimension-hint"
              />
              <span id="dimension-hint" className="text-xs text-muted-foreground">
                Must be a column in your CSV
              </span>
            </div>

            <div className="flex flex-col gap-1">
              <Label htmlFor="chart-type-select">Chart type</Label>
              <select
                id="chart-type-select"
                value={chartType}
                onChange={(e) => setChartType(e.target.value as ChartType)}
                className="h-9 rounded-md border border-input bg-background px-3 py-1 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
              >
                {CHART_TYPES.map((t) => (
                  <option key={t} value={t}>
                    {t.charAt(0).toUpperCase() + t.slice(1)}
                  </option>
                ))}
              </select>
            </div>
          </div>

          {/* Results */}
          {isLoading && (
            <p className="text-sm text-muted-foreground" role="status">
              Running query…
            </p>
          )}

          {isError && (
            <Alert variant="destructive">
              <AlertTitle>Query failed</AlertTitle>
              <AlertDescription>
                {error instanceof Error
                  ? error.message
                  : "An unexpected error occurred."}
              </AlertDescription>
            </Alert>
          )}

          {data && data.row_count > 0 && (
            <div className="space-y-2">
              <p className="text-xs text-muted-foreground">
                {data.row_count} row{data.row_count !== 1 ? "s" : ""} returned
              </p>
              <ChartRenderer
                spec={spec}
                data={data}
                title={`${chartType} chart — count by ${dimension}`}
                className="h-96"
              />
            </div>
          )}

          {data && data.row_count === 0 && (
            <EmptyState
              icon={<BarChart3 className="h-6 w-6" />}
              title="No data to chart yet"
              description={`Nothing grouped by "${dimension}". Check the column name matches a header in your CSV, then try again.`}
            />
          )}
        </CardContent>
      </Card>
      </div>
    </div>
  );
}
