// frontend/src/test/nativeFilterEditor.test.tsx
import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";

import { NativeFilterEditor } from "@/components/dashboard/NativeFilterEditor";
import type { DashboardTileRead } from "@/types/api";

vi.mock("@/api/hooks", () => ({
  useSemanticModels: () => ({
    data: [{
      name: "regional_sales", title: "Regional Sales",
      measures: [{ name: "regional_sales.total_amount", title: "Total", type: "number" }],
      dimensions: [
        { name: "regional_sales.region", title: "Region", type: "string" },
        { name: "regional_sales.order_date", title: "Order Date", type: "time" },
      ],
    }],
  }),
}));

const tiles: DashboardTileRead[] = [];

describe("NativeFilterEditor", () => {
  it("saves a new value filter with member + label", () => {
    const onSave = vi.fn();
    render(<NativeFilterEditor open initial={null} existing={[]} tiles={tiles} onOpenChange={() => {}} onSave={onSave} />);
    fireEvent.change(screen.getByLabelText(/dimension/i), { target: { value: "regional_sales.region" } });
    fireEvent.click(screen.getByRole("button", { name: /save/i }));
    expect(onSave).toHaveBeenCalledWith(expect.objectContaining({ kind: "value", member: "regional_sales.region" }));
  });

  it("offers only value filters as cascading parents", () => {
    render(
      <NativeFilterEditor
        open initial={null}
        existing={[
          { id: "v1", kind: "value", member: "regional_sales.region" },
          { id: "t1", kind: "time", member: "regional_sales.order_date" },
        ]}
        tiles={tiles} onOpenChange={() => {}} onSave={() => {}}
      />
    );
    const parent = screen.getByLabelText(/parent filter/i) as HTMLSelectElement;
    const optionValues = Array.from(parent.options).map((o) => o.value);
    expect(optionValues).toContain("v1");
    expect(optionValues).not.toContain("t1");
  });
});
