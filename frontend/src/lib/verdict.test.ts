import { describe, expect, it } from "vitest";

import { formatElapsed, reasonInfo, runTimes, verdictFacts } from "@/lib/verdict";
import { makeAttempt as attempt, makeReport as report, makeRun as run } from "@/lib/test-fixtures";

describe("verdictFacts", () => {
  it("counts the runs of the attempt that was executed and the attempts it took", () => {
    const facts = verdictFacts(report({
      attempts: [attempt(1, []), attempt(2, [run(0), run(1), run(2)])],
    }));
    expect(facts.runs).toBe(3);
    expect(facts.attempts).toBe(2);
  });

  it("says where the failure came from, from the evidence only", () => {
    expect(verdictFacts(report()).evidenceKind).toBe("Failure inside the target code");
    expect(
      verdictFacts(report({
        evidence: ["AssertionError: x", "assertion on target code's result failed in the main test"],
      })).evidenceKind,
    ).toBe("Wrong value returned (a failed assertion)");
    expect(verdictFacts(report({ evidence: ["test passed under the tested conditions"] }))
      .evidenceKind).toBeNull();
  });

  it("only claims agreement for outcomes that require every run to agree", () => {
    expect(verdictFacts(report()).unanimous).toBe(true);
    expect(verdictFacts(report({ outcome: "NOT_REPRODUCED", outcome_reason: "no_failure_observed" }))
      .unanimous).toBe(true);
    expect(verdictFacts(report({ outcome: "INCONCLUSIVE", outcome_reason: "not_repeatable" }))
      .unanimous).toBe(false);
    expect(verdictFacts(report({ outcome: null, state: "FAILED" })).unanimous).toBe(false);
  });

  it("handles a report with no executions", () => {
    const facts = verdictFacts(report({ attempts: [attempt(1, [])], outcome: "INCONCLUSIVE" }));
    expect(facts.runs).toBe(0);
    expect(facts.attempts).toBe(1);
  });
});

describe("elapsed time", () => {
  const at = (state: string, time: string) => ({ state, at: `2026-01-01T${time}`, message: "" }) as never;

  it("separates waiting in the queue from the time the work took", () => {
    const t = runTimes(report({
      completed_at: "2026-01-01T00:10:12",
      timeline: [at("CREATED", "00:00:00"), at("ANALYZING_REPORT", "00:10:00"), at("COMPLETED", "00:10:12")],
    }));
    expect(t).toEqual({ started: true, queuedMs: 600_000, runMs: 12_000 });
  });

  it("times a running investigation from when it started, not from when it was created", () => {
    const t = runTimes(report({
      state: "EXECUTING_TEST", completed_at: null,
      timeline: [at("CREATED", "00:00:00"), at("ANALYZING_REPORT", "00:10:00")],
    }), Date.parse("2026-01-01T00:10:05Z"));
    expect(t).toEqual({ started: true, queuedMs: 600_000, runMs: 5_000 });
  });

  it("counts a queued investigation as waiting, with no run time", () => {
    const t = runTimes(report({
      state: "CREATED", completed_at: null, timeline: [at("CREATED", "00:00:00")],
    }), Date.parse("2026-01-01T00:03:00Z"));
    expect(t).toEqual({ started: false, queuedMs: 180_000, runMs: 0 });
  });

  it("falls back to the creation time when there is no timeline", () => {
    expect(runTimes(report())).toEqual({ started: true, queuedMs: 0, runMs: 12_000 });
  });

  it("never goes negative when clocks disagree", () => {
    const t = runTimes(report({ state: "EXECUTING_TEST", completed_at: null, timeline: [] }),
      Date.parse("2025-12-31T23:59:00Z"));
    expect(t.runMs).toBe(0);
    expect(t.queuedMs).toBe(0);
  });

  it.each([
    [0, "0s"], [900, "0s"], [12_000, "12s"], [65_000, "1m 5s"], [3_600_000, "1h 0m"],
  ])("formats %d ms as %s", (ms, text) => expect(formatElapsed(ms)).toBe(text));
});

describe("reasonInfo", () => {
  it("explains every reason code the backend can produce", () => {
    const codes = [
      "matching_failure", "no_failure_observed", "runner_failure", "setup_failure",
      "control_failed", "resource_limit", "unrelated_failure", "signature_mismatch",
      "not_repeatable", "no_expected_behavior", "target_not_exercised", "generation_exhausted",
      "model_refused", "invalid_report", "unclassifiable",
    ];
    for (const code of codes) expect(reasonInfo(code).length).toBeGreaterThan(20);
  });

  it("falls back to a humanised code for a reason it does not know", () => {
    expect(reasonInfo("brand_new_reason")).toBe("Brand new reason");
    expect(reasonInfo(null)).toBe("");
  });
});
