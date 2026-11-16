import { act, cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { VerdictBanner } from "@/components/verdict-banner";
import { makeAttempt, makeReport, makeRun } from "@/lib/test-fixtures";

afterEach(cleanup);

const banner = () => screen.getByRole("region", { name: /verdict|investigating|execution error|cancelled|reproduced|inconclusive/i });

describe("VerdictBanner: finished investigations", () => {
  it("leads with the outcome, the reason and what it means", () => {
    render(<VerdictBanner report={makeReport()} />);
    expect(screen.getByRole("heading", { name: "Reproduced" })).toBeTruthy();
    expect(screen.getByText("Matching failure")).toBeTruthy();
    // Shown once, and once more in the screen-reader-only announcement.
    expect(screen.getAllByText(/failed the way the report predicts/i)).toHaveLength(2);
  });

  it("warns that a reproduction still needs a human reading the test", () => {
    render(<VerdictBanner report={makeReport()} />);
    expect(screen.getByText(/read the generated test before relying on this/i)).toBeTruthy();
  });

  it("says Not reproduced does not prove the bug is absent", () => {
    render(<VerdictBanner report={makeReport({
      outcome: "NOT_REPRODUCED", outcome_reason: "no_failure_observed",
      evidence: ["test passed under the tested conditions"],
    })} />);
    expect(screen.getByRole("heading", { name: "Not reproduced" })).toBeTruthy();
    expect(screen.getByText(/does not prove the bug is absent/i)).toBeTruthy();
  });

  it("explains an inconclusive result with its specific reason", () => {
    render(<VerdictBanner report={makeReport({
      outcome: "INCONCLUSIVE", outcome_reason: "control_failed", evidence: [],
    })} />);
    expect(screen.getByRole("heading", { name: "Inconclusive" })).toBeTruthy();
    expect(screen.getAllByText(/known-good control check failed/i)).toHaveLength(2);
  });

  it("shows how many runs agreed, the attempts, the evidence kind and the time taken", () => {
    render(<VerdictBanner report={makeReport({
      attempts: [makeAttempt(1, []), makeAttempt(2, [makeRun(0), makeRun(1), makeRun(2)])],
    })} />);
    const facts = within(banner()).getByRole("list", { name: "Key facts" });
    expect(facts.textContent).toContain("3 of 3 runs agreed");
    expect(facts.textContent).toContain("2 attempts");
    expect(facts.textContent).toContain("Failure inside the target code");
    expect(facts.textContent).toContain("12s");
  });

  it("does not claim agreement for a single run or for outcomes that do not require it", () => {
    const one = makeReport({ attempts: [makeAttempt(1, [makeRun(0)])] });
    render(<VerdictBanner report={one} />);
    expect(screen.queryByText(/runs agreed/)).toBeNull();
    expect(screen.getByText("1 run")).toBeTruthy();
    cleanup();
    render(<VerdictBanner report={makeReport({
      outcome: "INCONCLUSIVE", outcome_reason: "not_repeatable",
    })} />);
    expect(screen.queryByText(/runs agreed/)).toBeNull();
    expect(screen.getByText("3 runs")).toBeTruthy();
  });

  it("marks a wrong-value reproduction, which is weaker evidence", () => {
    render(<VerdictBanner report={makeReport({
      evidence: ["AssertionError: x", "assertion on target code's result failed in the main test"],
    })} />);
    expect(screen.getByText(/wrong value returned/i)).toBeTruthy();
  });
});

describe("VerdictBanner: other states", () => {
  it("shows progress, not a verdict, while running", () => {
    render(<VerdictBanner report={makeReport({
      state: "EXECUTING_TEST", outcome: null, outcome_reason: null, completed_at: null,
      created_at: new Date(Date.now() - 5_000).toISOString(),
    })} />);
    expect(screen.getByRole("heading", { name: "Investigating" })).toBeTruthy();
    expect(screen.getAllByText(/executing/i).length).toBeGreaterThan(0);
    expect(screen.getByRole("status").textContent).toMatch(/Investigating.*Executing/);
    expect(screen.queryByText("Reproduced")).toBeNull();
  });

  it("says a queued investigation is waiting for a worker", () => {
    render(<VerdictBanner report={makeReport({
      state: "CREATED", outcome: null, outcome_reason: null, completed_at: null, attempts: [],
    })} />);
    expect(screen.getAllByText(/waiting for a worker/i).length).toBeGreaterThan(0);
  });

  it("shows an infrastructure failure as an execution error with its detail", () => {
    render(<VerdictBanner report={makeReport({
      state: "FAILED", outcome: null, outcome_reason: null,
      error: { type: "SandboxUnavailable", detail: "docker is not reachable", retryable: true },
    })} />);
    expect(screen.getByRole("heading", { name: "Execution error" })).toBeTruthy();
    expect(screen.getByText("docker is not reachable")).toBeTruthy();
    expect(screen.getByText("SandboxUnavailable")).toBeTruthy();
    expect(screen.getByText(/may be temporary/i)).toBeTruthy();
    expect(screen.getByText(/nothing is concluded about the bug/i)).toBeTruthy();
  });

  it("does not invent a retry hint when the failure is not retryable", () => {
    render(<VerdictBanner report={makeReport({
      state: "FAILED", outcome: null, outcome_reason: null,
      error: { type: "Boom", detail: "x", retryable: false },
    })} />);
    expect(screen.queryByText(/may be temporary/i)).toBeNull();
  });

  it("shows a cancelled investigation without any outcome", () => {
    render(<VerdictBanner report={makeReport({
      state: "CANCELLED", outcome: null, outcome_reason: null,
    })} />);
    expect(screen.getByRole("heading", { name: "Cancelled" })).toBeTruthy();
  });
});

describe("VerdictBanner: screen reader announcements", () => {
  const running = (ageMs: number) => makeReport({
    state: "EXECUTING_TEST", outcome: null, outcome_reason: null, completed_at: null,
    created_at: new Date(Date.now() - ageMs).toISOString().replace("Z", ""),
  });

  it("does not re-announce every second while the timer ticks", () => {
    vi.useFakeTimers();
    try {
      const { container } = render(<VerdictBanner report={running(5_000)} />);
      const status = screen.getByRole("status");
      const spoken = status.textContent;
      const shown = container.querySelector('[aria-label="Key facts"]')?.textContent;
      act(() => vi.advanceTimersByTime(4_000));
      expect(status.textContent).toBe(spoken);
      expect(status.textContent).not.toMatch(/\d+s/);
      expect(container.querySelector('[aria-label="Key facts"]')?.textContent).not.toBe(shown);
    } finally {
      vi.useRealTimers();
    }
  });

  it("announces the result when the investigation finishes", () => {
    const { rerender } = render(<VerdictBanner report={running(5_000)} />);
    expect(screen.getByRole("status").textContent).not.toMatch(/Reproduced/);
    rerender(<VerdictBanner report={makeReport()} />);
    expect(screen.getByRole("status").textContent).toMatch(/Reproduced.*failed the way the report predicts/);
  });

  it("has exactly one live region, and it is not the banner itself", () => {
    render(<VerdictBanner report={makeReport()} />);
    const regions = screen.getAllByRole("status");
    expect(regions).toHaveLength(1);
    expect(regions[0].className).toContain("sr-only");
  });
});
