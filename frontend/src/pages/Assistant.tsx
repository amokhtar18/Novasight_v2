/**
 * Assistant — the unified AI surface (#7/#11): one grounded agent for chat, charts,
 * NL→SQL, and insights, replacing the separate Ask AI / Chat / Insights pages.
 *
 * Sends a message to POST /ai/assistant (the #13 agent framework). The reply shows the
 * grounded answer, which skills ran, plus any proposed **charts** (save or pin) and
 * **insight summaries** — propose-then-confirm: nothing is persisted until you act.
 * When a session has produced charts, "Build dashboard" assembles them into one.
 */

import { useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { LayoutDashboard, Lightbulb, Send, Sparkles, User } from "lucide-react";
import { toast } from "sonner";

import {
  useAddDashboardTile,
  useAssistant,
  useCreateChart,
  useCreateDashboard,
} from "@/api/hooks";
import { useChartData } from "@/lib/useChartData";
import { PageHeader } from "@/components/layout/PageHeader";
import { ChartRenderer } from "@/components/chart/ChartRenderer";
import { SaveChartButton } from "@/components/chart/SaveChartButton";
import { AddToDashboard } from "@/components/dashboard/AddToDashboard";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Spinner } from "@/components/ui/spinner";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import type { ChartSpec } from "@/types/api";

interface Turn {
  role: "user" | "assistant";
  text: string;
  tools?: string[];
  charts?: ChartSpec[];
  insights?: string[];
}

const SUGGESTIONS = [
  "What semantic models can I query?",
  "Chart total amount by region.",
  "Summarize sales by region.",
  "Which region has the highest sales?",
];

export function Assistant() {
  const assistant = useAssistant();
  const createDashboard = useCreateDashboard();
  const createChart = useCreateChart();
  const addTile = useAddDashboardTile();
  const navigate = useNavigate();

  const [input, setInput] = useState("");
  const [turns, setTurns] = useState<Turn[]>([]);
  const [building, setBuilding] = useState(false);
  const listRef = useRef<HTMLDivElement>(null);

  const sessionCharts = turns.flatMap((t) => t.charts ?? []);

  function send(message: string) {
    const trimmed = message.trim();
    if (!trimmed || assistant.isPending) return;
    setTurns((t) => [...t, { role: "user", text: trimmed }]);
    setInput("");
    assistant.mutate(
      { message: trimmed },
      {
        onSuccess: (resp) => {
          setTurns((t) => [
            ...t,
            {
              role: "assistant",
              text: resp.answer,
              tools: resp.tools_used,
              charts: resp.charts,
              insights: resp.insights,
            },
          ]);
          requestAnimationFrame(() =>
            listRef.current?.scrollTo({ top: listRef.current.scrollHeight })
          );
        },
      }
    );
  }

  async function buildDashboard() {
    if (sessionCharts.length === 0 || building) return;
    setBuilding(true);
    try {
      const board = await createDashboard.mutateAsync({ name: "Assistant dashboard" });
      for (const spec of sessionCharts) {
        const chart = await createChart.mutateAsync({
          name: spec.options?.title ?? "Chart",
          spec,
          source_kind: "semantic",
        });
        await addTile.mutateAsync({ dashboardId: board.id, tile: { chart_id: chart.id } });
      }
      toast.success("Dashboard created");
      navigate(`/dashboards/${board.id}`);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not build the dashboard");
    } finally {
      setBuilding(false);
    }
  }

  return (
    <div className="animate-in-up flex h-[calc(100vh-9rem)] flex-col">
      <PageHeader
        title="Assistant"
        description="Ask about your data in plain English — chat, charts, and insights, all grounded on the governed semantic layer. Every figure traces to a skill result."
        actions={
          sessionCharts.length > 0 ? (
            <Button variant="outline" size="sm" onClick={buildDashboard} disabled={building}>
              <LayoutDashboard className="h-4 w-4" aria-hidden />
              {building ? "Building…" : `Build dashboard (${sessionCharts.length})`}
            </Button>
          ) : undefined
        }
      />

      <div
        ref={listRef}
        className="flex-1 space-y-4 overflow-y-auto rounded-xl border bg-card/40 p-4"
      >
        {turns.length === 0 && (
          <div className="flex h-full flex-col items-center justify-center gap-4 text-center">
            <span className="flex h-12 w-12 items-center justify-center rounded-xl bg-primary/10 text-primary">
              <Sparkles className="h-6 w-6" aria-hidden />
            </span>
            <p className="max-w-md text-sm text-muted-foreground">
              Ask a question, request a chart, or ask for a summary. The assistant queries
              only governed models — it never invents numbers.
            </p>
            <div className="flex flex-wrap justify-center gap-2">
              {SUGGESTIONS.map((s) => (
                <Button key={s} variant="outline" size="sm" onClick={() => send(s)}>
                  {s}
                </Button>
              ))}
            </div>
          </div>
        )}

        {turns.map((turn, i) => (
          <div key={i} className="flex gap-3">
            <span
              className={
                "flex h-8 w-8 shrink-0 items-center justify-center rounded-lg " +
                (turn.role === "user"
                  ? "bg-secondary text-secondary-foreground"
                  : "bg-primary/10 text-primary")
              }
              aria-hidden
            >
              {turn.role === "user" ? <User className="h-4 w-4" /> : <Sparkles className="h-4 w-4" />}
            </span>
            <div className="min-w-0 flex-1">
              <p className="whitespace-pre-wrap text-sm leading-relaxed">{turn.text}</p>
              {turn.tools && turn.tools.length > 0 && (
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {[...new Set(turn.tools)].map((t) => (
                    <Badge key={t} variant="secondary" className="text-xs">
                      {t}
                    </Badge>
                  ))}
                </div>
              )}
              {turn.insights?.map((summary, j) => (
                <InsightCard key={j} summary={summary} />
              ))}
              {turn.charts?.map((spec, j) => (
                <AssistantChart key={j} spec={spec} />
              ))}
            </div>
          </div>
        ))}

        {assistant.isPending && (
          <div className="flex items-center gap-2 pl-11 text-sm text-muted-foreground">
            <Spinner label="Thinking" />
          </div>
        )}

        {assistant.isError && (
          <Alert variant="destructive">
            <AlertTitle>Assistant failed</AlertTitle>
            <AlertDescription>
              {assistant.error instanceof Error
                ? assistant.error.message
                : "The assistant is temporarily unavailable. Please try again."}
            </AlertDescription>
          </Alert>
        )}
      </div>

      <form
        className="mt-4 flex gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          send(input);
        }}
      >
        <Input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Ask, chart, or summarize…"
          aria-label="Message"
          maxLength={2000}
        />
        <Button type="submit" disabled={!input.trim() || assistant.isPending}>
          <Send className="h-4 w-4" aria-hidden />
          Send
        </Button>
      </form>
    </div>
  );
}

function InsightCard({ summary }: { summary: string }) {
  return (
    <div className="mt-3 flex gap-2 rounded-lg border bg-background/50 p-3">
      <Lightbulb className="mt-0.5 h-4 w-4 shrink-0 text-primary" aria-hidden />
      <p className="text-sm leading-relaxed">{summary}</p>
    </div>
  );
}

/**
 * AssistantChart — render a proposed chart inline and let the user keep it. Re-runs the
 * spec's grounded query (useChartData), then offers Save / pin-to-dashboard.
 */
function AssistantChart({ spec }: { spec: ChartSpec }) {
  const { data, isLoading, isError } = useChartData(spec);
  const title = spec.options?.title ?? "AI chart";

  return (
    <div className="mt-3 rounded-lg border bg-background/50 p-3">
      {isLoading ? (
        <div className="flex h-56 items-center justify-center">
          <Spinner label="Loading chart" />
        </div>
      ) : isError || !data || data.row_count === 0 ? (
        <p className="text-xs text-muted-foreground">This chart could not be rendered.</p>
      ) : (
        <>
          <ChartRenderer spec={spec} data={data} title={title} className="h-56" />
          <div className="mt-2 flex flex-wrap justify-end gap-2">
            <SaveChartButton spec={spec} defaultName={title} sourceKind="semantic" />
            <AddToDashboard spec={spec} title={title} />
          </div>
        </>
      )}
    </div>
  );
}
