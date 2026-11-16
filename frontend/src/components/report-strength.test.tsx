import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { ReportStrength } from "@/components/report-strength";
import { EMPTY_VALUES, type FormValues } from "@/lib/report-form";

afterEach(cleanup);

const values = (over: Partial<FormValues> = {}) => ({ ...EMPTY_VALUES, ...over });
const item = (label: string) => screen.getByText(label).closest("li")!;

describe("ReportStrength", () => {
  it("lists what the report gives REDFIRST, with the consequence of each", () => {
    render(<ReportStrength values={values()} />);
    expect(screen.getByRole("heading", { name: "What REDFIRST will use" })).toBeTruthy();
    expect(screen.getAllByRole("listitem")).toHaveLength(5);
    expect(within(item("Expected behavior")).getByText(/at most Inconclusive/)).toBeTruthy();
  });

  it("marks provided fields and says so to screen readers", () => {
    render(<ReportStrength values={values({ expected_behavior: "x", stack_trace: "tb" })} />);
    expect(item("Expected behavior").getAttribute("data-provided")).toBe("true");
    expect(item("Stack trace").getAttribute("data-provided")).toBe("true");
    expect(item("Environment").getAttribute("data-provided")).toBe("false");
    expect(within(item("Expected behavior")).getByText("provided")).toBeTruthy();
    expect(within(item("Environment")).getByText("not provided")).toBeTruthy();
  });

  it("updates the consequence once the expected behavior is given", () => {
    const { rerender } = render(<ReportStrength values={values()} />);
    expect(screen.getByText(/at most Inconclusive/)).toBeTruthy();
    rerender(<ReportStrength values={values({ expected_behavior: "it should raise" })} />);
    expect(screen.queryByText(/at most Inconclusive/)).toBeNull();
  });

  it("never shows a score", () => {
    const { container } = render(<ReportStrength values={values({ expected_behavior: "x" })} />);
    expect(container.textContent).not.toMatch(/\d+\s?%|score|\d+\s*\/\s*\d+/i);
  });
});
