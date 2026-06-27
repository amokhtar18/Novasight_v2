import { describe, it, expect } from "vitest";
import { controlHeight, focusRing } from "@/components/ui/_shared";

describe("ui shared control constants", () => {
  it("exposes a sm/md/lg control-height scale bound to the tokens", () => {
    expect(controlHeight.sm).toBe("h-[var(--control-h-sm)]");
    expect(controlHeight.md).toBe("h-[var(--control-h-md)]");
    expect(controlHeight.lg).toBe("h-[var(--control-h-lg)]");
  });

  it("exposes a single focus-ring class string used by every control", () => {
    expect(focusRing).toContain("focus-visible:ring-2");
    expect(focusRing).toContain("focus-visible:ring-ring");
    expect(focusRing).toContain("focus-visible:ring-offset-2");
    expect(focusRing).toContain("outline-none");
  });
});
