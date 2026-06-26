/** Tests for the chart numeric value formatter (#8). */
import { describe, it, expect } from "vitest";
import { formatChartValue } from "@/lib/chartFormat";

describe("formatChartValue", () => {
  it("formats currency with a symbol + fixed decimals", () => {
    expect(formatChartValue(10, { style: "currency", currency: "$", decimals: 0 })).toBe("$10");
  });
  it("appends % for percent style", () => {
    expect(formatChartValue(23.5, { style: "percent", decimals: 1 })).toBe("23.5%");
  });
  it("compacts large magnitudes", () => {
    expect(formatChartValue(1_500_000, { compact: true })).toBe("1.5M");
    expect(formatChartValue(2_300, { compact: true })).toBe("2.3K");
  });
  it("returns an empty string for non-finite values", () => {
    expect(formatChartValue(Number.NaN)).toBe("");
  });
  it("applies prefix and suffix", () => {
    expect(formatChartValue(5, { style: "plain", prefix: "≈", suffix: "/u" })).toBe("≈5/u");
  });
});
