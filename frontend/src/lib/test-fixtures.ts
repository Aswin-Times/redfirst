import type { EvidenceReport } from "@/lib/types";

/** Builders for tests: a complete report with sensible defaults, overridable per case. */
export const makeRun = (i: number, duration_ms = 200) => ({
  run_index: i, exit_code: 1, duration_ms, main_status: "failed", timed_out: false,
  oom_killed: false, exception_type: "KeyError", message: "'username'", output_excerpt: "",
  stdout_ref: null,
});

export const makeAttempt = (number: number, executions: ReturnType<typeof makeRun>[]) => ({
  number, status: "executed", model: "m", prompt: "generate_test:v4", validation_errors: [],
  validation_warnings: [], strategy: null, assumptions: [], test_code: "x", contract: null,
  executions,
});

export function makeReport(over: Partial<EvidenceReport> = {}): EvidenceReport {
  return {
    investigation_id: "i", state: "COMPLETED", outcome: "REPRODUCED",
    outcome_reason: "matching_failure", created_at: "2026-01-01T00:00:00Z",
    completed_at: "2026-01-01T00:00:12Z",
    bug_report: { title: "t", description: "", expected_behavior: null, actual_behavior: null,
      missing_fields: [] },
    repository: { id: "r", source_type: "zip", sha256: null, layout: null },
    relevant_files: [], attempts: [makeAttempt(1, [makeRun(0), makeRun(1), makeRun(2)])],
    final_test: "x",
    evidence: ["KeyError: 'username'", "failure raised inside target code"], error: null,
    timeline: [], limitations: [], next_steps: [], ...over,
  };
}
