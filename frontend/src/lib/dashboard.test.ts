import { describe, expect, it } from "vitest";

import {
  dailyCounts, headline, needsAttention, outcomeShares, relativeTime, resultParam,
} from "@/lib/dashboard";
import type { InvestigationSummary, Outcome } from "@/lib/types";

/** An API-style timestamp (UTC, no zone suffix) for a local date and time. */
const api = (y: number, m: number, d: number, h = 12, min = 0) =>
  new Date(y, m - 1, d, h, min).toISOString().replace("Z", "");

const inv = (over: Partial<InvestigationSummary> = {}): InvestigationSummary => ({
  id: "i", project_id: "p", repository_id: "r", title: "t", state: "COMPLETED",
  outcome: "REPRODUCED", outcome_reason: null, created_at: api(2026, 11, 16),
  updated_at: api(2026, 11, 16), completed_at: null, ...over,
});

const counts = (c: Partial<Record<Outcome, number>>) =>
  ({ REPRODUCED: 0, NOT_REPRODUCED: 0, INCONCLUSIVE: 0, EXECUTION_ERROR: 0, ...c });

describe("outcomeShares", () => {
  it("gives each outcome its count and a whole-number percentage that adds up to 100", () => {
    const shares = outcomeShares(counts({ REPRODUCED: 1, NOT_REPRODUCED: 1, INCONCLUSIVE: 1 }));
    expect(shares.map((s) => s.count)).toEqual([1, 1, 1, 0]);
    expect(shares.reduce((n, s) => n + s.percent, 0)).toBe(100);
  });

  it("uses the largest remainder so rounding never leaves 99 or 101", () => {
    const shares = outcomeShares(counts({ REPRODUCED: 2, NOT_REPRODUCED: 1, INCONCLUSIVE: 4 }));
    expect(shares.reduce((n, s) => n + s.percent, 0)).toBe(100);
    expect(shares.find((s) => s.outcome === "INCONCLUSIVE")?.percent).toBe(57);
  });

  it("is all zeros, not NaN, when there are no outcomes", () => {
    const shares = outcomeShares(counts({}));
    expect(shares.every((s) => s.percent === 0 && s.count === 0)).toBe(true);
  });

  it("keeps the four outcomes in a fixed order", () => {
    expect(outcomeShares(counts({})).map((s) => s.outcome)).toEqual([
      "REPRODUCED", "NOT_REPRODUCED", "INCONCLUSIVE", "EXECUTION_ERROR",
    ]);
  });
});

describe("dailyCounts", () => {
  const now = new Date(2026, 10, 16, 15, 0).getTime();

  it("returns one bucket per day, oldest first, ending today", () => {
    const days = dailyCounts([], 14, now);
    expect(days).toHaveLength(14);
    expect(days.at(-1)?.date).toBe("2026-11-16");
    expect(days[0].date).toBe("2026-11-03");
  });

  it("counts investigations on the local day they were created", () => {
    const days = dailyCounts([
      inv({ created_at: api(2026, 11, 16, 0, 5) }),
      inv({ created_at: api(2026, 11, 16, 23, 55) }),
      inv({ created_at: api(2026, 11, 15, 9) }),
    ], 14, now);
    expect(days.at(-1)?.count).toBe(2);
    expect(days.at(-2)?.count).toBe(1);
  });

  it("ignores investigations older than the window or from the future", () => {
    const days = dailyCounts([
      inv({ created_at: api(2026, 10, 1) }),
      inv({ created_at: api(2026, 11, 20) }),
    ], 14, now);
    expect(days.reduce((n, d) => n + d.count, 0)).toBe(0);
  });
});

describe("relativeTime", () => {
  const now = new Date(2026, 10, 16, 15, 0).getTime();
  it.each([
    [api(2026, 11, 16, 15, 0), "just now"],
    [api(2026, 11, 16, 14, 59), "1m ago"],
    [api(2026, 11, 16, 14, 30), "30m ago"],
    [api(2026, 11, 16, 12, 0), "3h ago"],
    [api(2026, 11, 14, 15, 0), "2d ago"],
  ])("%s -> %s", (iso, text) => expect(relativeTime(iso, now)).toBe(text));

  it("treats a timestamp slightly in the future (clock skew) as just now", () => {
    expect(relativeTime(api(2026, 11, 16, 15, 1), now)).toBe("just now");
  });

  it("falls back to a date after a week", () => {
    expect(relativeTime(api(2026, 11, 1), now)).toMatch(/Nov/);
  });
});

describe("needsAttention", () => {
  it("lists running, queued and failed investigations, newest first", () => {
    const items = [
      inv({ id: "done", state: "COMPLETED" }),
      inv({ id: "queued", state: "CREATED", outcome: null, created_at: api(2026, 11, 15) }),
      inv({ id: "running", state: "EXECUTING_TEST", outcome: null, created_at: api(2026, 11, 16) }),
      inv({ id: "failed", state: "FAILED", outcome: null, created_at: api(2026, 11, 14) }),
      inv({ id: "cancelled", state: "CANCELLED", outcome: null }),
    ];
    expect(needsAttention(items).map((i) => i.id)).toEqual(["running", "queued", "failed"]);
  });

  it("is empty when everything finished normally", () => {
    expect(needsAttention([inv(), inv({ state: "CANCELLED", outcome: null })])).toEqual([]);
  });
});

describe("headline", () => {
  it("summarises the non-zero outcomes and what is still running", () => {
    expect(headline(counts({ REPRODUCED: 7, NOT_REPRODUCED: 2, INCONCLUSIVE: 1 }), 2, 12)).toBe(
      "12 investigations: 7 reproduced, 2 not reproduced, 1 inconclusive; 2 still running.",
    );
  });

  it("uses the singular for one", () => {
    expect(headline(counts({ REPRODUCED: 1 }), 0, 1)).toBe("1 investigation: 1 reproduced.");
  });

  it("works with only running investigations", () => {
    expect(headline(counts({}), 3, 3)).toBe("3 investigations: 3 still running.");
  });

  it("pluralises execution errors", () => {
    expect(headline(counts({ EXECUTION_ERROR: 2 }), 0, 2)).toBe("2 investigations: 2 execution errors.");
    expect(headline(counts({ EXECUTION_ERROR: 1 }), 0, 1)).toBe("1 investigation: 1 execution error.");
  });

  it("says so when there is nothing yet", () => {
    expect(headline(counts({}), 0, 0)).toBe("No investigations yet.");
  });
});

describe("resultParam", () => {
  it.each([
    ["REPRODUCED", "REPRODUCED"], ["NOT_REPRODUCED", "NOT_REPRODUCED"],
    ["INCONCLUSIVE", "INCONCLUSIVE"], ["EXECUTION_ERROR", "EXECUTION_ERROR"],
    ["running", "running"], [null, ""], ["", ""], ["reproduced", ""], ["bogus", ""],
  ])("%j -> %j", (raw, want) => expect(resultParam(raw)).toBe(want));
});
