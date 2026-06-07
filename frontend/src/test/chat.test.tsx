/**
 * Tests for the Chat page (#11 UI).
 *
 * The chat hook + toast are mocked. Covers: sending a question renders the user
 * turn and the grounded answer with its tool badges, and a suggestion chip sends.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";

import type { ChatResponse } from "@/types/api";

vi.mock("@/api/hooks", () => ({ useChat: vi.fn() }));

import { Chat } from "@/pages/Chat";
import { useChat } from "@/api/hooks";

const mockUseChat = vi.mocked(useChat);

function makeMutation(overrides: {
  isPending?: boolean;
  isError?: boolean;
  mutate?: (...args: unknown[]) => void;
}) {
  return {
    isPending: overrides.isPending ?? false,
    isError: overrides.isError ?? false,
    error: null,
    mutate: overrides.mutate ?? vi.fn(),
    data: undefined,
    reset: vi.fn(),
    mutateAsync: vi.fn(),
    status: "idle" as const,
    variables: undefined,
    context: undefined,
    isSuccess: false,
    isIdle: true,
    failureCount: 0,
    failureReason: null,
    submittedAt: 0,
  };
}

beforeEach(() => {
  // @ts-expect-error partial mock
  mockUseChat.mockReturnValue(makeMutation({}));
});

afterEach(() => vi.clearAllMocks());

describe("Chat page", () => {
  it("renders the empty state with suggestions", () => {
    render(<Chat />);
    expect(screen.getByRole("button", { name: /what semantic models/i })).toBeInTheDocument();
  });

  it("sends a question and renders the grounded answer with tool badges", () => {
    const answer: ChatResponse = {
      answer: "The west region leads with 100.5.",
      tools_used: ["list_semantic_models", "query_semantic_model"],
    };
    const mutate = vi.fn(
      (_vars: unknown, cbs?: { onSuccess?: (r: ChatResponse) => void }) => {
        cbs?.onSuccess?.(answer);
      }
    );
    // @ts-expect-error partial mock
    mockUseChat.mockReturnValue(makeMutation({ mutate }));

    render(<Chat />);
    fireEvent.change(screen.getByLabelText(/message/i), {
      target: { value: "which region leads?" },
    });
    fireEvent.click(screen.getByRole("button", { name: /send/i }));

    expect(mutate).toHaveBeenCalledWith(
      { message: "which region leads?" },
      expect.objectContaining({ onSuccess: expect.any(Function) })
    );
    // User turn + grounded answer + tool badges rendered.
    expect(screen.getByText("which region leads?")).toBeInTheDocument();
    expect(screen.getByText(/west region leads/i)).toBeInTheDocument();
    expect(screen.getByText("query_semantic_model")).toBeInTheDocument();
  });

  it("sends when a suggestion chip is clicked", () => {
    const mutate = vi.fn();
    // @ts-expect-error partial mock
    mockUseChat.mockReturnValue(makeMutation({ mutate }));
    render(<Chat />);
    fireEvent.click(screen.getByRole("button", { name: /what semantic models/i }));
    expect(mutate).toHaveBeenCalledWith(
      { message: "What semantic models can I query?" },
      expect.anything()
    );
  });
});
