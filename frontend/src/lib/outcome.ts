import type { InvestigationState, Outcome } from "@/lib/types";

export const OUTCOME_INFO: Record<Outcome, { label: string; description: string }> = {
  REPRODUCED: {
    label: "Reproduced",
    description: "The test ran and showed the reported defect, supported by execution evidence.",
  },
  NOT_REPRODUCED: {
    label: "Not reproduced",
    description:
      "The test ran meaningfully but the defect did not appear. This does not prove the bug is absent.",
  },
  INCONCLUSIVE: {
    label: "Inconclusive",
    description: "The attempt could not establish whether the bug exists.",
  },
  EXECUTION_ERROR: {
    label: "Execution error",
    description: "The investigation could not complete because of an infrastructure problem.",
  },
};

export const STATE_LABEL: Record<InvestigationState, string> = {
  CREATED: "Queued",
  ANALYZING_REPORT: "Analyzing report",
  ANALYZING_REPOSITORY: "Analyzing repository",
  GENERATING_TEST: "Generating test",
  VALIDATING_TEST: "Validating test",
  EXECUTING_TEST: "Executing",
  VERIFYING_RESULT: "Verifying",
  COMPLETED: "Completed",
  FAILED: "Failed",
  CANCELLED: "Cancelled",
};

/** "setup_failure" -> "Setup failure" */
export const humanize = (value: string) =>
  value.charAt(0).toUpperCase() + value.slice(1).replaceAll("_", " ");

export function formatDate(iso: string): string {
  return new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

export function formatDuration(ms: number | null): string {
  if (ms == null) return "–";
  return ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`;
}
