import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { ActivityChart } from "@/components/activity-chart";
import { NeedsAttention } from "@/components/needs-attention";
import { OutcomeBar } from "@/components/outcome-bar";
import { outcomeShares } from "@/lib/dashboard";
import type { InvestigationSummary, Outcome } from "@/lib/types";

afterEach(cleanup);

const counts = (c: Partial<Record<Outcome, number>>) =>
  ({ REPRODUCED: 0, NOT_REPRODUCED: 0, INCONCLUSIVE: 0, EXECUTION_ERROR: 0, ...c });

describe("OutcomeBar", () => {
  it("describes the whole breakdown for assistive technology", () => {
    render(<OutcomeBar shares={outcomeShares(counts({ REPRODUCED: 3, NOT_REPRODUCED: 1 }))} />);
    const bar = screen.getByRole("img");
    expect(bar.getAttribute("aria-label")).toBe(
      "Outcomes: 3 reproduced (75%), 1 not reproduced (25%)",
    );
  });

  it("links every outcome with results to the list filtered by it", () => {
    render(<OutcomeBar shares={outcomeShares(counts({ REPRODUCED: 3, INCONCLUSIVE: 1 }))} />);
    const legend = screen.getByRole("list", { name: "Outcome legend" });
    expect(within(legend).getByRole("link", { name: /Reproduced/ }).getAttribute("href"))
      .toBe("/investigations?result=REPRODUCED");
    expect(within(legend).getByRole("link", { name: /Inconclusive/ }).getAttribute("href"))
      .toBe("/investigations?result=INCONCLUSIVE");
  });

  it("keeps the bar itself free of interactive elements (they may not sit inside role=img)", () => {
    render(<OutcomeBar shares={outcomeShares(counts({ REPRODUCED: 3, INCONCLUSIVE: 1 }))} />);
    expect(screen.getByRole("img").querySelectorAll("a, button, [tabindex]")).toHaveLength(0);
  });

  it("shows counts and percentages, and keeps empty outcomes in the legend without a link", () => {
    render(<OutcomeBar shares={outcomeShares(counts({ REPRODUCED: 1, NOT_REPRODUCED: 1 }))} />);
    const legend = screen.getByRole("list", { name: "Outcome legend" });
    expect(legend.textContent).toContain("50%");
    expect(within(legend).queryByRole("link", { name: /Execution error/ })).toBeNull();
    expect(legend.textContent).toContain("Execution error");
  });

  it("says so instead of drawing an empty bar when nothing has finished", () => {
    render(<OutcomeBar shares={outcomeShares(counts({}))} />);
    expect(screen.getByText(/no finished investigations yet/i)).toBeTruthy();
    expect(screen.queryByRole("img")).toBeNull();
  });
});

describe("ActivityChart", () => {
  const days = Array.from({ length: 14 }, (_, i) => ({
    date: `2026-11-${String(i + 3).padStart(2, "0")}`, count: i === 13 ? 5 : i === 12 ? 2 : 0,
  }));

  it("summarises the period in text", () => {
    render(<ActivityChart days={days} />);
    expect(screen.getByRole("img").getAttribute("aria-label")).toBe(
      "Investigations per day, last 14 days: 7 in total, busiest day 5",
    );
  });

  it("draws one bar per day with its own count", () => {
    const { container } = render(<ActivityChart days={days} />);
    const bars = container.querySelectorAll("[data-bar]");
    expect(bars).toHaveLength(14);
    expect(bars[13].getAttribute("title")).toBe("2026-11-16: 5");
  });

  it("copes with no activity at all", () => {
    render(<ActivityChart days={days.map((d) => ({ ...d, count: 0 }))} />);
    expect(screen.getByRole("img").getAttribute("aria-label")).toContain("0 in total");
  });
});

describe("NeedsAttention", () => {
  const inv = (over: Partial<InvestigationSummary>): InvestigationSummary => ({
    id: "abc12345-0000", project_id: "p", repository_id: "r", title: "register crashes",
    state: "EXECUTING_TEST", outcome: null, outcome_reason: null,
    created_at: new Date().toISOString().replace("Z", ""),
    updated_at: new Date().toISOString().replace("Z", ""), completed_at: null, ...over,
  });

  it("lists each investigation as a link with its state", () => {
    render(<NeedsAttention items={[inv({}), inv({ id: "def", title: "other", state: "FAILED" })]} />);
    const link = screen.getByRole("link", { name: "register crashes" });
    expect(link.getAttribute("href")).toBe("/investigations/abc12345-0000");
    expect(screen.getByText("Executing")).toBeTruthy();
    expect(screen.getByRole("heading", { name: /needs attention/i })).toBeTruthy();
  });

  it("renders nothing when there is nothing to attend to", () => {
    const { container } = render(<NeedsAttention items={[]} />);
    expect(container.textContent).toBe("");
  });
});
