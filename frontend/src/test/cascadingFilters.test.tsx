// frontend/src/test/cascadingFilters.test.tsx
import { describe, expect, it, vi } from "vitest";
import { render } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { DashboardFilterBar } from "@/components/dashboard/DashboardFilterBar";
import type { NativeFilter } from "@/types/api";

const calls: unknown[] = [];
vi.mock("@/api/hooks", () => ({
  useSemanticValues: (req: unknown) => { calls.push(req); return { data: { values: [] }, isLoading: false }; },
}));

const filters: NativeFilter[] = [
  { id: "country", kind: "value", member: "geo.country", operator: "equals" },
  { id: "city", kind: "value", member: "geo.city", operator: "equals", parent_id: "country" },
];

describe("cascading", () => {
  it("passes the parent selection as constraints on the child values request", () => {
    calls.length = 0;
    const qc = new QueryClient();
    render(
      <QueryClientProvider client={qc}>
        <DashboardFilterBar
          filters={filters}
          selections={{ country: { kind: "value", values: ["US"] }, city: { kind: "value", values: [] } }}
          onSelectionChange={() => {}} onClearAll={() => {}} editing={false}
        />
      </QueryClientProvider>
    );
    const childReq = calls.find((c) => (c as { member?: string })?.member === "geo.city") as { constraints?: unknown[] };
    expect(childReq?.constraints).toEqual([{ member: "geo.country", operator: "equals", values: ["US"] }]);
  });
});
