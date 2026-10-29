import type { InvestigationState, TimelineEntry } from "@/lib/types";

export const STAGES: { state: InvestigationState; label: string }[] = [
  { state: "ANALYZING_REPORT", label: "Report analysis" },
  { state: "ANALYZING_REPOSITORY", label: "Repository analysis" },
  { state: "GENERATING_TEST", label: "Test generation" },
  { state: "VALIDATING_TEST", label: "Test validation" },
  { state: "EXECUTING_TEST", label: "Sandbox execution" },
  { state: "VERIFYING_RESULT", label: "Result verification" },
];

export type StageStatus = "done" | "active" | "failed" | "pending" | "skipped";

const TERMINAL: InvestigationState[] = ["COMPLETED", "FAILED", "CANCELLED"];

export const isTerminal = (s: InvestigationState) => TERMINAL.includes(s);

/**
 * Derive each stage's status from the persisted timeline only (no guessing).
 * Stages can repeat (regeneration loops); a stage counts as reached if it appears at all.
 */
export function deriveStages(
  timeline: Pick<TimelineEntry, "state">[],
  current: InvestigationState,
): { state: InvestigationState; label: string; status: StageStatus; visits: number }[] {
  const visits = new Map<InvestigationState, number>();
  for (const e of timeline) visits.set(e.state, (visits.get(e.state) ?? 0) + 1);
  const lastStage = [...timeline].reverse().find((e) => !isTerminal(e.state) && e.state !== "CREATED");

  return STAGES.map(({ state, label }) => {
    const n = visits.get(state) ?? 0;
    let status: StageStatus;
    if (n === 0) {
      status = current === "COMPLETED" ? "skipped" : "pending";
    } else if (!isTerminal(current)) {
      status = current === state ? "active" : "done";
    } else if (current === "FAILED" && lastStage?.state === state) {
      status = "failed";
    } else {
      status = "done";
    }
    return { state, label, status, visits: n };
  });
}
