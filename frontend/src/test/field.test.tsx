import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";

import { Field } from "@/components/molecules/Field";
import { Input } from "@/components/ui/input";

describe("Field", () => {
  it("associates the label with the control", () => {
    render(
      <Field label="Email">
        <Input />
      </Field>
    );
    // getByLabelText resolves the control via the generated htmlFor/id link.
    expect(screen.getByLabelText("Email")).toBeInTheDocument();
  });

  it("links an error message and marks the control invalid", () => {
    render(
      <Field label="Email" error="Required">
        <Input />
      </Field>
    );
    const input = screen.getByLabelText("Email");
    expect(input).toHaveAttribute("aria-invalid", "true");
    const describedBy = input.getAttribute("aria-describedby");
    expect(describedBy).toBeTruthy();
    expect(screen.getByText("Required").id).toBe(describedBy);
  });

  it("shows the hint when there is no error", () => {
    render(
      <Field label="Email" hint="We never share it">
        <Input />
      </Field>
    );
    expect(screen.getByText("We never share it")).toBeInTheDocument();
  });

  it("hides the hint when an error is present", () => {
    render(
      <Field label="Email" hint="We never share it" error="Required">
        <Input />
      </Field>
    );
    expect(screen.queryByText("We never share it")).not.toBeInTheDocument();
    expect(screen.getByText("Required")).toBeInTheDocument();
  });
});
