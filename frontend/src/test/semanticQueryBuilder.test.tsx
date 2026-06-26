import { describe, expect, it } from "vitest";
import { filtersAfterDrop, parseFilterValues } from "@/components/chart/SemanticQueryBuilder";
import type { SemanticFilter } from "@/types/api";

describe("filter helpers", () => {
  it("appends a default-equals filter for a dropped member", () => {
    const next = filtersAfterDrop([], "s.region");
    expect(next).toEqual([{ member: "s.region", operator: "equals", values: [] }]);
  });

  it("does not duplicate a member already filtered", () => {
    const existing: SemanticFilter[] = [{ member: "s.region", operator: "equals", values: ["west"] }];
    expect(filtersAfterDrop(existing, "s.region")).toBe(existing);
  });

  it("parses comma-separated values, trimming blanks", () => {
    expect(parseFilterValues("west, east ,")).toEqual(["west", "east"]);
  });
});
