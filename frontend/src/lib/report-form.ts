import type { BugReportInput } from "@/lib/types";

/**
 * Field limits of the bug report form. They mirror BugReportInput in
 * backend/redfirst/analysis/report.py (the server stays authoritative); a test reads that file
 * and fails if the numbers drift apart.
 */
export const LIMITS = {
  title: 300,
  description: 20_000,
  expected_behavior: 10_000,
  actual_behavior: 10_000,
  reproduction_steps: 10_000,
  stack_trace: 50_000,
  environment: 5_000,
} as const;

/** The backend's default upload limit (REDFIRST_UPLOAD_MAX_BYTES). */
export const UPLOAD_MAX_BYTES = 50 * 1024 * 1024;

export type FieldKey = keyof typeof LIMITS;
export type FormValues = Record<FieldKey, string>;

export const EMPTY_VALUES: FormValues = {
  title: "", description: "", expected_behavior: "", actual_behavior: "",
  reproduction_steps: "", stack_trace: "", environment: "",
};

const FIELD_NAME: Record<FieldKey, string> = {
  title: "title", description: "description", expected_behavior: "expected behavior",
  actual_behavior: "actual behavior", reproduction_steps: "reproduction steps",
  stack_trace: "stack trace", environment: "environment",
};

const FIELDS = Object.keys(LIMITS) as FieldKey[];

/** Trim, and turn blank optional fields into null so the backend records them as missing. */
export function toBugReport(values: FormValues): BugReportInput {
  const optional = (key: FieldKey) => values[key].trim() || null;
  return {
    title: values.title.trim(),
    description: values.description.trim(),
    expected_behavior: optional("expected_behavior"),
    actual_behavior: optional("actual_behavior"),
    reproduction_steps: optional("reproduction_steps"),
    stack_trace: optional("stack_trace"),
    environment: optional("environment"),
  };
}

/** One message per field that is invalid right now. */
export function fieldProblems(values: FormValues): Partial<Record<FieldKey, string>> {
  const problems: Partial<Record<FieldKey, string>> = {};
  if (!values.title.trim()) problems.title = "Add a title.";
  for (const key of FIELDS) {
    const over = values[key].length - LIMITS[key];
    if (over > 0) {
      problems[key] =
        `${over.toLocaleString("en-US")} character${over === 1 ? "" : "s"} over the limit of ${LIMITS[key].toLocaleString("en-US")}.`;
    }
  }
  return problems;
}

/** Counters stay out of the way until a field is within 20% of its limit. */
export function counterState(length: number, limit: number): "hidden" | "near" | "over" {
  if (length > limit) return "over";
  return length >= limit * 0.8 ? "near" : "hidden";
}

/** Why the form cannot be submitted yet, in words; null when it can. */
export function submitBlocker(state: {
  projectId: string;
  repositoryId: string;
  values: FormValues;
  busy: boolean;
}): string | null {
  if (state.busy) return "Working…";
  if (!state.projectId) return "Create or choose a project.";
  if (!state.repositoryId) return "Choose or upload a repository.";
  const problems = fieldProblems(state.values);
  if (problems.title === "Add a title.") return "Add a title.";
  const over = FIELDS.find((k) => problems[k]);
  return over ? `Shorten the ${FIELD_NAME[over]}.` : null;
}

export interface ChecklistItem {
  key: Exclude<FieldKey, "title" | "description">;
  label: string;
  provided: boolean;
  effect: string;
}

const CHECKS: {
  key: ChecklistItem["key"];
  label: string;
  have: string;
  lack: string;
}[] = [
  {
    key: "expected_behavior",
    label: "Expected behavior",
    have: "Says what should happen, so a failing test can be checked against it.",
    lack: "Without it the result can be at most Inconclusive.",
  },
  {
    key: "actual_behavior",
    label: "Actual behavior",
    have: "Says what goes wrong, so the failure the test shows can be matched to it.",
    lack: "Recorded as missing, not guessed; the test has less to match against.",
  },
  {
    key: "reproduction_steps",
    label: "Reproduction steps",
    have: "Exact inputs and steps can shape the test.",
    lack: "Optional. Exact inputs make the test more precise.",
  },
  {
    key: "stack_trace",
    label: "Stack trace",
    have: "The trace can point REDFIRST at the failing code.",
    lack: "Optional. A trace helps find the right files.",
  },
  {
    key: "environment",
    label: "Environment",
    have: "Versions and platform are recorded with the result.",
    lack: "Optional. Python and package versions help when behavior differs by setup.",
  },
];

/** What the report gives REDFIRST to work with; each effect is a fact about how results are decided. */
export function checklist(values: FormValues): ChecklistItem[] {
  return CHECKS.map((c) => {
    const provided = Boolean(values[c.key].trim());
    return { key: c.key, label: c.label, provided, effect: provided ? c.have : c.lack };
  });
}

export const DRAFT_KEY = "redfirst-draft-investigation";

export const serializeDraft = (values: FormValues): string => JSON.stringify(values);

/** A saved draft, or null when there is nothing usable. Damaged drafts keep their good fields. */
export function parseDraft(raw: string | null | undefined): FormValues | null {
  if (!raw) return null;
  let data: unknown;
  try {
    data = JSON.parse(raw);
  } catch {
    return null;
  }
  if (typeof data !== "object" || data === null || Array.isArray(data)) return null;
  const record = data as Record<string, unknown>;
  const values = { ...EMPTY_VALUES };
  for (const key of FIELDS) {
    const v = record[key];
    if (typeof v === "string") values[key] = v.slice(0, LIMITS[key]);
  }
  return FIELDS.some((k) => values[k].trim()) ? values : null;
}
