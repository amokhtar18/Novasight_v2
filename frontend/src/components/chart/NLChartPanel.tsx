/**
 * NLChartPanel — "Describe your chart" natural-language input.
 *
 * Submits a free-text prompt to POST /api/v1/ai/chart via the `useNLChart`
 * mutation. On success it renders the returned `spec` + `data` through the
 * EXISTING `ChartRenderer` (same renderer used for manually-configured charts).
 *
 * Fallback behaviour:
 *   - 422 (ungroundable spec): friendly message + `onFallback()` callback so
 *     the parent can reveal the manual builder controls.
 *   - 503 (service unavailable): transient retry prompt.
 *   - Never renders a partial/invalid chart; never crashes.
 *
 * Accessibility: the textarea has an explicit <Label>, status messages use
 * role="status" (non-urgent live region) or role="alert" (urgent errors).
 */

import { useState } from "react";
import { Sparkles } from "lucide-react";

import { useNLChart } from "@/api/hooks";
import { NLChartError } from "@/api/client";
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
import type { NLChartResponse } from "@/types/api";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface NLChartPanelProps {
  /**
   * Called when a 422 is returned (ungroundable spec). The parent should
   * keep the manual builder visible/accessible so the user can proceed.
   */
  onFallback?: () => void;
  /**
   * Called with the validated {spec, data} on success — lets the parent offer
   * follow-up actions (e.g. "Add to dashboard") on the AI-generated chart.
   */
  onResult?: (result: NLChartResponse) => void;
  /**
   * Example prompts surfaced as one-click chips, so a non-technical user has a
   * starting point instead of a blank box. Defaults to a generic starter set.
   */
  suggestions?: string[];
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

const MAX_CHARS = 2000;

/** Generic starter prompts that work for most datasets. */
const DEFAULT_SUGGESTIONS = [
  "Top 10 by total sales as a bar chart",
  "Trend over time as a line chart",
  "Share by category as a pie chart",
];

export function NLChartPanel({
  onFallback,
  onResult,
  suggestions = DEFAULT_SUGGESTIONS,
}: NLChartPanelProps) {
  const [prompt, setPrompt] = useState("");
  // Holds the last successful AI result so the chart persists while the user
  // edits the prompt for a follow-up.
  const [aiResult, setAiResult] = useState<NLChartResponse | null>(null);

  const { mutate, isPending, error, reset: resetMutation } = useNLChart();

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const trimmed = prompt.trim();
    if (!trimmed) return;

    // Clear the previous AI result and any prior error so the UI is fresh.
    setAiResult(null);
    resetMutation();

    mutate(
      { request: trimmed },
      {
        onSuccess: (result) => {
          setAiResult(result);
          onResult?.(result);
        },
        onError: (err) => {
          if (err instanceof NLChartError && err.kind === "ungroundable") {
            onFallback?.();
          }
        },
      }
    );
  }

  // Derive a human-readable error message and kind.
  const nlError =
    error instanceof NLChartError ? error : null;
  const isUngroundable = nlError?.kind === "ungroundable";
  const isServiceUnavailable = nlError?.kind === "service_unavailable";
  const isOtherError = error !== null && nlError === null;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Sparkles className="h-4 w-4" aria-hidden />
          Describe your chart
        </CardTitle>
        <CardDescription>
          Type what you want to see — e.g. "total sales by region as a bar
          chart" — and the AI will build it for you.
        </CardDescription>
      </CardHeader>

      <CardContent className="space-y-4">
        {/* Input form */}
        <form onSubmit={handleSubmit} className="space-y-3">
          <div className="flex flex-col gap-1">
            <Label htmlFor="nl-chart-prompt">Chart description</Label>
            <textarea
              id="nl-chart-prompt"
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              placeholder="e.g. total sales by region as a bar chart"
              maxLength={MAX_CHARS}
              rows={3}
              disabled={isPending}
              aria-describedby="nl-chart-hint"
              className="rounded-md border border-input bg-background px-3 py-2 text-sm shadow-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:opacity-50 resize-none"
            />
            <span
              id="nl-chart-hint"
              className="text-xs text-muted-foreground"
            >
              {prompt.length}/{MAX_CHARS} characters
            </span>
          </div>

          {/* Contextual example prompts — click to fill the box. */}
          {suggestions.length > 0 && (
            <div className="flex flex-col gap-1">
              <span className="text-xs text-muted-foreground">Try one of these:</span>
              <div className="flex flex-wrap gap-2" role="group" aria-label="Example prompts">
                {suggestions.map((s) => (
                  <button
                    key={s}
                    type="button"
                    onClick={() => setPrompt(s)}
                    disabled={isPending}
                    className="rounded-full border border-input bg-background px-3 py-1 text-xs text-muted-foreground hover:border-primary hover:text-primary transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:opacity-50"
                  >
                    {s}
                  </button>
                ))}
              </div>
            </div>
          )}

          <Button
            type="submit"
            disabled={isPending || prompt.trim().length === 0}
            size="sm"
          >
            {isPending ? "Generating…" : "Generate chart"}
          </Button>
        </form>

        {/* Loading state */}
        {isPending && (
          <p className="text-sm text-muted-foreground" role="status">
            Generating chart — this may take a moment…
          </p>
        )}

        {/* 422 fallback — role="alert" so screen-reader users are notified the
            chart failed (a user-triggered error is as important as the 503 case). */}
        {isUngroundable && (
          <Alert role="alert">
            <AlertTitle>Could not generate that chart</AlertTitle>
            <AlertDescription>
              {nlError.message
                ? nlError.message
                : "The description couldn't be turned into a valid chart."}
              {" "}Try rephrasing, or build it manually using the controls below.
            </AlertDescription>
          </Alert>
        )}

        {/* 503 transient error */}
        {isServiceUnavailable && (
          <Alert variant="destructive" role="alert" aria-live="assertive">
            <AlertTitle>Service unavailable</AlertTitle>
            <AlertDescription>
              The chart generation service is temporarily unavailable. Please
              try again in a moment.
            </AlertDescription>
          </Alert>
        )}

        {/* Other unexpected errors */}
        {isOtherError && (
          <Alert variant="destructive" role="alert" aria-live="assertive">
            <AlertTitle>Something went wrong</AlertTitle>
            <AlertDescription>
              {error instanceof Error
                ? error.message
                : "An unexpected error occurred."}
            </AlertDescription>
          </Alert>
        )}

        {/* AI-generated chart */}
        {aiResult && !isPending && (
          <div className="space-y-2">
            <p className="text-xs text-muted-foreground" role="status">
              AI-generated chart — {aiResult.data.row_count} row
              {aiResult.data.row_count !== 1 ? "s" : ""} returned
            </p>
            <ChartRenderer
              spec={aiResult.spec}
              data={aiResult.data}
              title={
                aiResult.spec.options?.title ??
                `AI-generated ${aiResult.spec.type} chart`
              }
              className="h-96"
            />
          </div>
        )}
      </CardContent>
    </Card>
  );
}
