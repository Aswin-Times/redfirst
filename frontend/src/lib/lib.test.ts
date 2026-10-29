import { describe, expect, it } from "vitest";

import { errorMessage } from "@/lib/api";
import { formatDuration, humanize } from "@/lib/outcome";
import { deriveStages } from "@/lib/stages";
import { summarize } from "@/lib/summary";
import type { InvestigationState, InvestigationSummary } from "@/lib/types";

const t = (...states: InvestigationState[]) => states.map((state) => ({ state }));
const statuses = (timeline: { state: InvestigationState }[], current: InvestigationState) =>
  deriveStages(timeline, current).map((s) => s.status);

describe("deriveStages", () => {
  it("marks nothing started for a queued investigation", () => {
    expect(statuses(t("CREATED"), "CREATED")).toEqual(Array(6).fill("pending"));
  });

  it("marks the current stage active and earlier ones done", () => {
    const tl = t("CREATED", "ANALYZING_REPORT", "ANALYZING_REPOSITORY", "GENERATING_TEST");
    expect(statuses(tl, "GENERATING_TEST")).toEqual([
      "done", "done", "active", "pending", "pending", "pending",
    ]);
  });

  it("shows unreached stages as skipped when completed early", () => {
    const tl = t("CREATED", "ANALYZING_REPORT", "ANALYZING_REPOSITORY", "GENERATING_TEST",
      "VALIDATING_TEST", "COMPLETED");
    expect(statuses(tl, "COMPLETED")).toEqual([
      "done", "done", "done", "done", "skipped", "skipped",
    ]);
  });

  it("marks the stage where an infrastructure failure happened", () => {
    const tl = t("CREATED", "ANALYZING_REPORT", "ANALYZING_REPOSITORY", "GENERATING_TEST",
      "VALIDATING_TEST", "EXECUTING_TEST", "FAILED");
    expect(statuses(tl, "FAILED")).toEqual([
      "done", "done", "done", "done", "failed", "pending",
    ]);
  });

  it("counts repeated visits from regeneration loops", () => {
    const tl = t("GENERATING_TEST", "VALIDATING_TEST", "GENERATING_TEST", "VALIDATING_TEST");
    const gen = deriveStages(tl, "VALIDATING_TEST").find((s) => s.state === "GENERATING_TEST");
    expect(gen?.visits).toBe(2);
  });
});

describe("summarize", () => {
  const inv = (state: InvestigationState, outcome: InvestigationSummary["outcome"]) =>
    ({ state, outcome }) as InvestigationSummary;

  it("counts only real outcomes and running investigations", () => {
    const { counts, active } = summarize([
      inv("COMPLETED", "REPRODUCED"),
      inv("COMPLETED", "REPRODUCED"),
      inv("FAILED", "EXECUTION_ERROR"),
      inv("EXECUTING_TEST", null),
      inv("CANCELLED", null),
    ]);
    expect(counts).toEqual({
      REPRODUCED: 2, NOT_REPRODUCED: 0, INCONCLUSIVE: 0, EXECUTION_ERROR: 1,
    });
    expect(active).toBe(1);
  });
});

describe("errorMessage", () => {
  it("uses FastAPI string details", () => {
    expect(errorMessage(400, { detail: "archive rejected: path traversal" })).toBe(
      "archive rejected: path traversal",
    );
  });

  it("flattens validation errors with field names", () => {
    const body = { detail: [{ loc: ["body", "bug_report", "title"], msg: "too short" }] };
    expect(errorMessage(422, body)).toBe("bug_report.title: too short");
  });

  it("explains unreachable and server errors", () => {
    expect(errorMessage(0, null)).toMatch(/not reachable/);
    expect(errorMessage(502, null)).toMatch(/HTTP 502/);
  });
});

describe("formatting", () => {
  it("humanizes reasons and durations", () => {
    expect(humanize("setup_failure")).toBe("Setup failure");
    expect(formatDuration(850)).toBe("850 ms");
    expect(formatDuration(2400)).toBe("2.4 s");
    expect(formatDuration(null)).toBe("–");
  });
});
