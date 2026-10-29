// Mirrors backend/redfirst/api/schemas.py and verification/report.py. Keep in sync.

export type InvestigationState =
  | "CREATED"
  | "ANALYZING_REPORT"
  | "ANALYZING_REPOSITORY"
  | "GENERATING_TEST"
  | "VALIDATING_TEST"
  | "EXECUTING_TEST"
  | "VERIFYING_RESULT"
  | "COMPLETED"
  | "FAILED"
  | "CANCELLED";

export type Outcome = "REPRODUCED" | "NOT_REPRODUCED" | "INCONCLUSIVE" | "EXECUTION_ERROR";

export interface Project {
  id: string;
  name: string;
  created_at: string;
}

export interface RepoLayout {
  layout: string;
  source_roots: string[];
  packages: string[];
  manifests: string[];
  requirements_files: string[];
  test_dirs: string[];
  conftest_files: string[];
  pytest_config: string | null;
  python_file_count: number;
}

export interface Repository {
  id: string;
  project_id: string;
  source_type: string;
  sha256: string | null;
  layout: RepoLayout | null;
  created_at: string;
}

export interface InvestigationSummary {
  id: string;
  project_id: string;
  repository_id: string;
  title: string;
  state: InvestigationState;
  outcome: Outcome | null;
  outcome_reason: string | null;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
}

export interface BugReportInput {
  title: string;
  description: string;
  expected_behavior: string | null;
  actual_behavior: string | null;
  reproduction_steps: string | null;
  stack_trace: string | null;
  environment: string | null;
}

export interface ExecutionSummary {
  run_index: number;
  exit_code: number | null;
  duration_ms: number | null;
  main_status: string | null;
  timed_out: boolean;
  oom_killed: boolean;
  exception_type: string | null;
  message: string;
  output_excerpt: string;
  stdout_ref: string | null;
}

export interface AttemptSummary {
  number: number;
  status: string;
  model: string | null;
  prompt: string | null;
  validation_errors: string[];
  validation_warnings: string[];
  strategy: string | null;
  assumptions: string[];
  test_code: string | null;
  contract: Record<string, unknown> | null;
  executions: ExecutionSummary[];
}

export interface RelevantFile {
  file: string;
  score: number;
  reasons: string[];
  symbols: string[];
  sent_to_model: boolean;
}

export interface TimelineEntry {
  at: string;
  state: InvestigationState;
  message: string;
}

export interface EvidenceReport {
  investigation_id: string;
  state: InvestigationState;
  outcome: Outcome | null;
  outcome_reason: string | null;
  created_at: string;
  completed_at: string | null;
  bug_report: {
    title: string;
    description: string;
    expected_behavior: string | null;
    actual_behavior: string | null;
    missing_fields: string[];
  };
  repository: { id: string; source_type: string; sha256: string | null; layout: string | null };
  relevant_files: RelevantFile[];
  attempts: AttemptSummary[];
  final_test: string | null;
  evidence: string[];
  error: { type?: string; detail?: string; retryable?: boolean } | null;
  timeline: TimelineEntry[];
  limitations: string[];
  next_steps: string[];
}

export interface StateEvent {
  state: InvestigationState;
  message: string;
  data: Record<string, unknown> | null;
  at: string;
}
