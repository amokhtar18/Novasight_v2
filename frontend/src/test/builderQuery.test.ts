import { describe, expect, it } from "vitest";
import { buildChartQuery } from "@/pages/Builder";

describe("buildChartQuery", () => {
  it("emits time_dimensions with date_range, order, and limit", () => {
    const q = buildChartQuery({
      measures: ["s.total"],
      plainDims: [],
      timeDimension: { dimension: "s.created", granularity: "month" },
      dateRange: "last_30_days",
      filters: [],
      orderBy: { member: "s.total", dir: "desc" },
      rowLimit: 25,
    });
    expect(q.time_dimensions).toEqual([
      { dimension: "s.created", granularity: "month", date_range: "last_30_days" },
    ]);
    expect(q.order).toEqual({ "s.total": "desc" });
    expect(q.limit).toBe(25);
    expect(q.metric_refs).toEqual(["s.total"]);
  });

  it("omits order when no sort is chosen and omits date_range when unset", () => {
    const q = buildChartQuery({
      measures: ["s.total"],
      plainDims: ["s.region"],
      timeDimension: null,
      dateRange: null,
      filters: [],
      orderBy: null,
      rowLimit: 50,
    });
    expect(q.order).toEqual({});
    expect(q.time_dimensions).toEqual([]);
    expect(q.dimensions).toEqual(["s.region"]);
  });
});
