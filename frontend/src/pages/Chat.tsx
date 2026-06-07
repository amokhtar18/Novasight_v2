/**
 * Chat — ask questions over the governed semantic layer (#11).
 *
 * Sends a question to POST /ai/chat, which runs a grounded tool-dispatch loop on
 * the backend (the model may only call governed, tenant-scoped tools). The reply
 * shows the answer plus which tools the assistant used, for transparency.
 */

import { useRef, useState } from "react";
import { MessageSquare, Send, Sparkles, User } from "lucide-react";

import { useChat } from "@/api/hooks";
import { PageHeader } from "@/components/layout/PageHeader";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Spinner } from "@/components/ui/spinner";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";

interface Turn {
  role: "user" | "assistant";
  text: string;
  tools?: string[];
}

const SUGGESTIONS = [
  "What semantic models can I query?",
  "Show total amount by region.",
  "Which region has the highest sales?",
];

export function Chat() {
  const chat = useChat();
  const [input, setInput] = useState("");
  const [turns, setTurns] = useState<Turn[]>([]);
  const listRef = useRef<HTMLDivElement>(null);

  function send(message: string) {
    const trimmed = message.trim();
    if (!trimmed || chat.isPending) return;
    setTurns((t) => [...t, { role: "user", text: trimmed }]);
    setInput("");
    chat.mutate(
      { message: trimmed },
      {
        onSuccess: (resp) => {
          setTurns((t) => [
            ...t,
            { role: "assistant", text: resp.answer, tools: resp.tools_used },
          ]);
          requestAnimationFrame(() =>
            listRef.current?.scrollTo({ top: listRef.current.scrollHeight })
          );
        },
      }
    );
  }

  return (
    <div className="animate-in-up flex h-[calc(100vh-9rem)] flex-col">
      <PageHeader
        title="Chat"
        description="Ask about your data in plain English. Answers are grounded on the governed semantic layer — every figure traces to a tool result."
      />

      <div
        ref={listRef}
        className="flex-1 space-y-4 overflow-y-auto rounded-xl border bg-card/40 p-4"
      >
        {turns.length === 0 && (
          <div className="flex h-full flex-col items-center justify-center gap-4 text-center">
            <span className="flex h-12 w-12 items-center justify-center rounded-xl bg-primary/10 text-primary">
              <MessageSquare className="h-6 w-6" aria-hidden />
            </span>
            <p className="max-w-md text-sm text-muted-foreground">
              Ask a question about your data. The assistant queries only governed
              models — it never invents numbers.
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
              {turn.role === "user" ? (
                <User className="h-4 w-4" />
              ) : (
                <Sparkles className="h-4 w-4" />
              )}
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
            </div>
          </div>
        ))}

        {chat.isPending && (
          <div className="flex items-center gap-2 pl-11 text-sm text-muted-foreground">
            <Spinner label="Thinking" />
          </div>
        )}

        {chat.isError && (
          <Alert variant="destructive">
            <AlertTitle>Chat failed</AlertTitle>
            <AlertDescription>
              {chat.error instanceof Error
                ? chat.error.message
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
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Ask about your data…"
          aria-label="Message"
          maxLength={2000}
          className="flex h-10 w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm shadow-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
        />
        <Button type="submit" disabled={!input.trim() || chat.isPending}>
          <Send className="h-4 w-4" aria-hidden />
          Send
        </Button>
      </form>
    </div>
  );
}
