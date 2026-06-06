/**
 * Explore (Ask AI) — natural-language querying over the governed semantic layer.
 *
 * The user asks a question; the backend grounds it, generates validated SQL,
 * executes it read-only, and returns rows. We surface the SQL for transparency,
 * the results as a table, an optional auto-chart, and a one-click AI summary.
 *
 * All safety is enforced server-side; the UI only renders validated output and
 * never constructs SQL itself (golden rule #3).
 */

import { useMemo, useState } from "react";
import { Check, Copy, Lightbulb, Send, Sparkles } from "lucide-react";

import { useInsight, useNLQuery } from "@/api/hooks";
import { PageHeader } from "@/components/layout/PageHeader";
import { ChartRenderer } from "@/components/chart/ChartRenderer";
import { TableRenderer } from "@/components/chart/TableRenderer";
import { AddToDashboard } from "@/components/dashboard/AddToDashboard";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Spinner } from "@/components/ui/spinner";
import type { ChartSpec, NLQueryResponse, QueryResponse } from "@/types/api";

const EXAMPLES = [
  "What are the top 5 categories by total revenue?",
  "Show monthly sales for the last year",
  "Average order value by region",
];

/** Adapt an NL→SQL response to the QueryResponse shape the renderers expect. */
function toQueryResponse(r: NLQueryResponse): QueryResponse {
  return { columns: r.columns, rows: r.rows, row_count: r.row_count };
}

/** Best-effort auto-chart: first non-numeric column as x, first numeric as series. */
function autoChartSpec(r: NLQueryResponse): ChartSpec | null {
  if (r.columns.length < 2 || r.rows.length === 0) return null;
  const firstRow = r.rows[0];
  const numericIdx = firstRow.findIndex((v) => typeof v === "number");
  if (numericIdx === -1) return null;
  const xIdx = firstRow.findIndex((v, i) => i !== numericIdx && typeof v !== "number");
  const x = r.columns[xIdx === -1 ? 0 : xIdx];
  const field = r.columns[numericIdx];
  return {
    version: "1",
    type: "bar",
    query: {},
    encoding: { x, series: [{ field }] },
    options: { title: "" },
  };
}

export function Explore() {
  const [question, setQuestion] = useState("");
  const [copied, setCopied] = useState(false);
  const [showChart, setShowChart] = useState(false);

  const nlQuery = useNLQuery();
  const insight = useInsight();
  const result = nlQuery.data ?? null;

  const chartSpec = useMemo(
    () => (result ? autoChartSpec(result) : null),
    [result]
  );

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const q = question.trim();
    if (!q) return;
    setShowChart(false);
    insight.reset();
    nlQuery.mutate({ question: q });
  }

  function handleSummarize() {
    if (!result) return;
    insight.mutate({
      columns: result.columns,
      rows: result.rows,
      context_hint: question.trim() || undefined,
    });
  }

  async function copySql() {
    if (!result) return;
    await navigator.clipboard.writeText(result.sql);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  }

  return (
    <div className="animate-in-up">
      <PageHeader
        title="Ask AI"
        description="Ask a question in plain English. Answers are generated as validated, read-only SQL over your governed metrics."
      />

      <Card className="bg-card/70">
        <CardContent className="pt-6">
          <form onSubmit={handleSubmit} className="space-y-3">
            <div className="flex flex-col gap-2 sm:flex-row">
              <input
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
                placeholder="e.g. top 5 products by revenue this quarter"
                aria-label="Your question"
                maxLength={2000}
                className="h-11 flex-1 rounded-lg border border-input bg-background/60 px-4 text-sm shadow-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              />
              <Button
                type="submit"
                size="lg"
                disabled={nlQuery.isPending || question.trim().length === 0}
                className="sm:w-auto"
              >
                {nlQuery.isPending ? (
                  <Spinner className="text-primary-foreground" />
                ) : (
                  <Send className="h-4 w-4" aria-hidden />
                )}
                Ask
              </Button>
            </div>
            <div className="flex flex-wrap gap-2" role="group" aria-label="Example questions">
              {EXAMPLES.map((ex) => (
                <button
                  key={ex}
                  type="button"
                  onClick={() => setQuestion(ex)}
                  className="rounded-full border border-input bg-background/40 px-3 py-1 text-xs text-muted-foreground transition-colors hover:border-primary hover:text-primary"
                >
                  {ex}
                </button>
              ))}
            </div>
          </form>
        </CardContent>
      </Card>

      {/* Errors */}
      {nlQuery.isError && (
        <Alert variant="destructive" className="mt-6">
          <AlertTitle>Couldn't answer that</AlertTitle>
          <AlertDescription>
            {nlQuery.error instanceof Error
              ? nlQuery.error.message
              : "Try rephrasing your question."}
          </AlertDescription>
        </Alert>
      )}

      {/* Results */}
      {result && (
        <div className="mt-6 space-y-6">
          {/* SQL transparency */}
          <Card className="bg-card/70">
            <CardHeader className="flex-row items-center justify-between space-y-0 pb-3">
              <CardTitle className="text-sm font-medium text-muted-foreground">
                Generated SQL (validated, read-only)
              </CardTitle>
              <Button variant="ghost" size="sm" onClick={copySql}>
                {copied ? (
                  <Check className="h-4 w-4 text-success" aria-hidden />
                ) : (
                  <Copy className="h-4 w-4" aria-hidden />
                )}
                {copied ? "Copied" : "Copy"}
              </Button>
            </CardHeader>
            <CardContent>
              <pre className="overflow-auto rounded-lg border bg-background/60 p-4 text-xs leading-relaxed">
                <code>{result.sql}</code>
              </pre>
            </CardContent>
          </Card>

          {/* Result table + actions */}
          <Card className="bg-card/70">
            <CardHeader className="flex-row flex-wrap items-center justify-between gap-2 space-y-0">
              <CardTitle className="flex items-center gap-2 text-base">
                Results
                <Badge variant="secondary">
                  {result.row_count} row{result.row_count === 1 ? "" : "s"}
                </Badge>
              </CardTitle>
              <div className="flex flex-wrap items-center gap-2">
                {chartSpec && (
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => setShowChart((v) => !v)}
                  >
                    <Sparkles className="h-4 w-4" aria-hidden />
                    {showChart ? "Show table" : "Visualize"}
                  </Button>
                )}
                <Button
                  variant="outline"
                  size="sm"
                  onClick={handleSummarize}
                  disabled={insight.isPending || result.row_count === 0}
                >
                  {insight.isPending ? (
                    <Spinner />
                  ) : (
                    <Lightbulb className="h-4 w-4" aria-hidden />
                  )}
                  Summarize
                </Button>
                {chartSpec && (
                  <AddToDashboard
                    spec={{ ...chartSpec, options: { title: question.trim() || "Query result" } }}
                    title={question.trim() || "Query result"}
                    data={toQueryResponse(result)}
                  />
                )}
              </div>
            </CardHeader>
            <CardContent className="space-y-4">
              {insight.isError && (
                <Alert variant="destructive">
                  <AlertTitle>Couldn't summarize</AlertTitle>
                  <AlertDescription>
                    {insight.error instanceof Error
                      ? insight.error.message
                      : "Please try again."}
                  </AlertDescription>
                </Alert>
              )}
              {insight.data && (
                <Alert>
                  <Lightbulb className="h-4 w-4" aria-hidden />
                  <AlertTitle>AI summary</AlertTitle>
                  <AlertDescription>{insight.data.summary}</AlertDescription>
                </Alert>
              )}

              {showChart && chartSpec ? (
                <ChartRenderer
                  spec={chartSpec}
                  data={toQueryResponse(result)}
                  title="Query result"
                  className="h-80"
                />
              ) : (
                <TableRenderer data={toQueryResponse(result)} />
              )}
            </CardContent>
          </Card>
        </div>
      )}
    </div>
  );
}
