import type {
  BugReportInput,
  EvidenceReport,
  InvestigationSummary,
  Project,
  Repository,
} from "@/lib/types";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

/** Turn a FastAPI error body into one readable sentence. */
export function errorMessage(status: number, body: unknown): string {
  const detail = (body as { detail?: unknown } | null)?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((d: { loc?: unknown[]; msg?: string }) => {
        const field = (d.loc ?? []).filter((p) => p !== "body").join(".");
        return field ? `${field}: ${d.msg}` : (d.msg ?? "invalid input");
      })
      .join("; ");
  }
  if (status === 0) return "The REDFIRST API is not reachable.";
  if (status >= 500) return `The server failed to handle the request (HTTP ${status}).`;
  return `Request failed (HTTP ${status}).`;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, { cache: "no-store", ...init });
  } catch {
    throw new ApiError(0, errorMessage(0, null));
  }
  const text = await res.text();
  let body: unknown = null;
  try {
    body = text ? JSON.parse(text) : null;
  } catch {
    body = null;
  }
  if (!res.ok) throw new ApiError(res.status, errorMessage(res.status, body));
  return body as T;
}

const json = (method: string, data: unknown): RequestInit => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(data),
});

export const api = {
  projects: () => request<Project[]>("/api/projects"),
  createProject: (name: string) => request<Project>("/api/projects", json("POST", { name })),
  repositories: (projectId: string) =>
    request<Repository[]>(`/api/projects/${projectId}/repositories`),
  uploadRepository: (projectId: string, file: File) => {
    const form = new FormData();
    form.append("archive", file);
    return request<Repository>(`/api/projects/${projectId}/repositories`, {
      method: "POST",
      body: form,
    });
  },
  investigations: (projectId?: string) =>
    request<InvestigationSummary[]>(
      `/api/investigations?limit=200${projectId ? `&project_id=${projectId}` : ""}`,
    ),
  createInvestigation: (projectId: string, repositoryId: string, report: BugReportInput) =>
    request<InvestigationSummary>(
      `/api/projects/${projectId}/investigations`,
      json("POST", { repository_id: repositoryId, bug_report: report }),
    ),
  investigation: (id: string) => request<EvidenceReport>(`/api/investigations/${id}`),
  cancel: (id: string) =>
    request<InvestigationSummary>(`/api/investigations/${id}/cancel`, { method: "POST" }),
};

export const exportUrls = (id: string) => ({
  test: `/api/investigations/${id}/export/test`,
  json: `/api/investigations/${id}/export/report?format=json`,
  markdown: `/api/investigations/${id}/export/report?format=md`,
});
