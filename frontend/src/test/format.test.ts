/**
 * Tests for the formatting helpers — null-safety and basic correctness.
 */

import { describe, it, expect } from "vitest";
import { formatBytes, formatCell, humanize } from "@/lib/format";

describe("formatBytes", () => {
  it("formats common sizes", () => {
    expect(formatBytes(0)).toBe("0 B");
    expect(formatBytes(512)).toBe("512 B");
    expect(formatBytes(1536)).toBe("1.5 KB");
    expect(formatBytes(1024 * 1024)).toBe("1.0 MB");
  });
  it("is null-safe", () => {
    expect(formatBytes(null)).toBe("—");
    expect(formatBytes(undefined)).toBe("—");
    expect(formatBytes(-1)).toBe("—");
  });
});

describe("formatCell", () => {
  it("renders nulls as an em dash", () => {
    expect(formatCell(null)).toBe("—");
    expect(formatCell(undefined)).toBe("—");
  });
  it("localizes numbers and stringifies the rest", () => {
    expect(formatCell(1000)).toBe((1000).toLocaleString());
    expect(formatCell(true)).toBe("true");
    expect(formatCell("hi")).toBe("hi");
  });
});

describe("humanize", () => {
  it("title-cases snake/kebab identifiers", () => {
    expect(humanize("total_sales")).toBe("Total Sales");
    expect(humanize("avg")).toBe("Avg");
    expect(humanize("created-at")).toBe("Created At");
  });
});
