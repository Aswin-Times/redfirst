import { parseEvidence } from "@/lib/evidence";
import { humanize, parseTimestamp } from "@/lib/outcome";
import type { EvidenceReport } from "@/lib/types";

/** One plain sentence per outcome reason code (backend/redfirst/domain/enums.py). */
const REASONS: Record<string, string> = {
  matching_failure:
    "The generated test failed the way the report predicts, with evidence tied to the repository's code.",
  no_failure_observed:
    "The test ran properly and passed, so the reported behavior did not appear under the tested conditions.",
  runner_failure:
    "REDFIRST could not run the test (a sandbox or runner problem), so nothing is concluded about the bug.",
  setup_failure:
    "The test never got as far as exercising the bug: an import, fixture or collection step failed first.",
  control_failed:
    "A known-good control check failed too, so the test setup itself cannot be trusted.",
  resource_limit: "The run hit a time, memory or output limit before it could finish.",
  unrelated_failure:
    "The test failed, but not in the target code, so it does not show the reported bug.",
  signature_mismatch: "The test failed with a different error than the report predicts.",
  not_repeatable: "Repeated runs disagreed with each other, so the result is not reliable.",
  no_expected_behavior:
    "The report did not say what should happen, so there is nothing to check the behavior against.",
  target_not_exercised:
    "The test passed but was not shown to call the code the report is about.",
  generation_exhausted: "No valid test could be produced within the attempt limit.",
  model_refused: "The model declined to write a test for this report.",
  invalid_report:
    "The test's own result report was missing or contradicted what the runner observed, so it was not trusted.",
  unclassifiable: "The main test did not run to a clear pass or fail.",
};

export function reasonInfo(reason: string | null): string {
  if (!reason) return "";
  return REASONS[reason] ?? humanize(reason);
}

const EVIDENCE_KIND = {
  target: "Failure inside the target code",
  assertion: "Wrong value returned (a failed assertion)",
} as const;

/** Facts for the verdict banner, taken only from what the report already contains. */
export function verdictFacts(report: EvidenceReport) {
  const executed = [...report.attempts].reverse().find((a) => a.executions.length > 0);
  const origin = parseEvidence(report.evidence).origin;
  return {
    runs: executed?.executions.length ?? 0,
    attempts: report.attempts.length,
    evidenceKind: origin ? EVIDENCE_KIND[origin] : null,
    // These two outcomes are only reached when every repeated run gave the same result.
    unanimous: report.outcome === "REPRODUCED" || report.outcome === "NOT_REPRODUCED",
  };
}

/**
 * How long an investigation waited for a worker and how long the work took. The run starts at
 * its first state after CREATED; counting from creation would include hours spent in the queue.
 * Without a timeline (or once it is past CREATED with no entries) it falls back to creation.
 */
export function runTimes(
  report: Pick<EvidenceReport, "created_at" | "completed_at" | "timeline" | "state">,
  now = Date.now(),
): { started: boolean; queuedMs: number; runMs: number } {
  const created = parseTimestamp(report.created_at);
  const end = report.completed_at ? parseTimestamp(report.completed_at) : now;
  const first = report.timeline.find((t) => t.state !== "CREATED");
  const started = first ? parseTimestamp(first.at) : report.state === "CREATED" ? null : created;
  if (started === null) return { started: false, queuedMs: Math.max(0, end - created), runMs: 0 };
  return { started: true, queuedMs: Math.max(0, started - created), runMs: Math.max(0, end - started) };
}

/** Waits shorter than this are normal and not worth a fact of their own. */
export const NOTABLE_QUEUE_MS = 60_000;

export function formatElapsed(ms: number): string {
  const s = Math.floor(ms / 1000);
  if (s >= 3600) return `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m`;
  if (s >= 60) return `${Math.floor(s / 60)}m ${s % 60}s`;
  return `${s}s`;
}
