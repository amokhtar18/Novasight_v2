import { describe, expect, it, vi } from "vitest";
import { toCsv, downloadCsv } from "@/lib/csv";
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

  it("escapes carriage returns", () => {
    const data: QueryResponse = { columns: ["x"], rows: [["a\rb"]], row_count: 1 };
    expect(toCsv(data)).toBe('x\n"a\rb"');
  });
});

describe("downloadCsv", () => {
  it("creates an object URL, clicks an anchor, then revokes the URL", () => {
    const fakeUrl = "blob:fake-url";
    const createObjectURL = vi.fn().mockReturnValue(fakeUrl);
    const revokeObjectURL = vi.fn();
    const click = vi.fn();

    vi.stubGlobal("URL", { createObjectURL, revokeObjectURL });
    vi
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(click);

    const data: QueryResponse = {
      columns: ["a"],
      rows: [["1"]],
      row_count: 1,
    };

    downloadCsv(data, "export");

    expect(createObjectURL).toHaveBeenCalledOnce();
    const blob: Blob = createObjectURL.mock.calls[0][0];
    expect(blob).toBeInstanceOf(Blob);
    expect(blob.type).toBe("text/csv;charset=utf-8;");

    expect(click).toHaveBeenCalledOnce();
    expect(revokeObjectURL).toHaveBeenCalledWith(fakeUrl);

    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });
});
