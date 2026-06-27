import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";

import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";

function Harness({ value = "a" }: { value?: string }) {
  return (
    <Tabs value={value} onValueChange={() => {}}>
      <TabsList>
        <TabsTrigger value="a">A</TabsTrigger>
        <TabsTrigger value="b">B</TabsTrigger>
      </TabsList>
      <TabsContent value="a">Panel A</TabsContent>
      <TabsContent value="b">Panel B</TabsContent>
    </Tabs>
  );
}

describe("Tabs", () => {
  it("TabsList uses the control-height token", () => {
    render(<Harness />);
    expect(screen.getByRole("tablist")).toHaveClass("h-[var(--control-h-md)]");
  });

  it("TabsTrigger uses the shared focus ring (offset)", () => {
    render(<Harness />);
    expect(screen.getByRole("tab", { name: "A" })).toHaveClass("focus-visible:ring-offset-2");
  });

  it("active TabsTrigger uses the elevation-1 token shadow", () => {
    render(<Harness value="a" />);
    expect(screen.getByRole("tab", { name: "A" })).toHaveClass("shadow-[var(--elevation-1)]");
  });

  it("shows only the active panel (behavior preserved)", () => {
    render(<Harness value="a" />);
    expect(screen.getByText("Panel A")).toBeInTheDocument();
    expect(screen.queryByText("Panel B")).not.toBeInTheDocument();
  });
});
