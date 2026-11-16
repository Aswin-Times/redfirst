import { OUTCOME_INFO } from "@/lib/outcome";
import type { EvidenceReport } from "@/lib/types";

/** The tab title for an investigation: its status first, so several open tabs can be told apart. */
export function investigationTitle(report: Pick<EvidenceReport, "outcome" | "state" | "bug_report">): string {
  const { outcome, state } = report;
  let prefix: string;
  if (outcome && outcome !== "EXECUTION_ERROR") prefix = OUTCOME_INFO[outcome].label;
  else if (state === "FAILED" || outcome === "EXECUTION_ERROR") prefix = "Failed";
  else if (state === "CANCELLED") prefix = "Cancelled";
  else if (state === "CREATED") prefix = "Queued";
  else prefix = "Running";
  return `${prefix}: ${report.bug_report.title}`;
}
