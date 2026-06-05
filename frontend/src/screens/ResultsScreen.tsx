/**
 * ResultsScreen — query a dataset and render a chart.
 *
 * The default query does a COUNT(*) grouped by the first column the user can pick.
 * A simple spec editor (dimension + chart type) lets the user iterate.
 * The chart is driven entirely by a ChartSpec — the renderer is agnostic to
 * how the spec was produced (manual here; AI in future phases).
 */

import { useState } from "react";
import { ArrowLeft } from "lucide-react";

import { useDatasetQuery } from "@/api/hooks";
import { useAppStore } from "@/store/appStore";
import { ChartRenderer } from "@/components/chart/ChartRenderer";
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

  // Build the query and spec from current controls.
  const safeId = selectedDatasetId ?? "";
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

      <Card>
        <CardHeader>
          <CardTitle>Query &amp; Chart</CardTitle>
          <CardDescription>
            Dataset ID:{" "}
            <code className="text-xs bg-muted px-1 rounded">{safeId}</code>
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

          {data && (
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
        </CardContent>
      </Card>
    </div>
  );
}
