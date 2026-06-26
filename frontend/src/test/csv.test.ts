import { describe, expect, it } from "vitest";
import { toCsv } from "@/lib/csv";
import type { QueryResponse } from "@/types/api";

describe("toCsv", () => {
  it("renders headers + rows", () => {
    const data: QueryResponse = {
      columns: ["region", "sales"],
      rows: [["west", 100], ["east", 200]],
      row_count: 2,
    };
    expect(toCsv(data)).toBe("region,sales\nwest,100\neast,200");
  });

  it("escapes commas, quotes, and newlines", () => {
    const data: QueryResponse = {
      columns: ["label", "note"],
      rows: [['a,b', 'he said "hi"'], ["line1\nline2", null]],
      row_count: 2,
    };
    expect(toCsv(data)).toBe('label,note\n"a,b","he said ""hi"""\n"line1\nline2",');
  });
});
