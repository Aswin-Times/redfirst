import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AnnouncerProvider } from "@/components/announcer";
import { AppHeader } from "@/components/app-header";
import { ArchiveDropzone } from "@/components/archive-dropzone";
import { Breadcrumbs } from "@/components/breadcrumbs";
import { CancelInvestigation } from "@/components/cancel-investigation";
import { Dashboard } from "@/components/pages/dashboard";
import { InvestigationHistory } from "@/components/pages/investigation-history";
import { InvestigationWorkspace } from "@/components/pages/investigation-workspace";
import { NewInvestigation } from "@/components/pages/new-investigation";
import { Projects } from "@/components/pages/projects";
import { ReportStrength } from "@/components/report-strength";
import { SkipLink } from "@/components/skip-link";
import { VerdictBanner } from "@/components/verdict-banner";
import { api } from "@/lib/api";
import { EMPTY_VALUES } from "@/lib/report-form";
import { makeAttempt, makeReport, makeRun } from "@/lib/test-fixtures";
import type { InvestigationSummary, Outcome, Repository } from "@/lib/types";
import { violations } from "@/test/a11y";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
  usePathname: () => "/investigations",
  useSearchParams: () => new URLSearchParams(),
  useParams: () => ({ id: "inv1" }),
}));
vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...rest}>{children}</a>
  ),
}));
vi.mock("@/hooks/use-investigation-events", () => ({ useInvestigationEvents: () => "open" }));
vi.mock("@/lib/api", () => ({
  api: {
    projects: vi.fn(), repositories: vi.fn(), investigations: vi.fn(), investigation: vi.fn(),
    createProject: vi.fn(), uploadRepository: vi.fn(), createInvestigation: vi.fn(), cancel: vi.fn(),
  },
  exportUrls: (id: string) => ({ test: `/t/${id}`, json: `/j/${id}`, markdown: `/m/${id}` }),
}));

const mocked = vi.mocked(api);
const NOW = new Date().toISOString().replace("Z", "");
const OUTCOMES: (Outcome | null)[] = ["REPRODUCED", "NOT_REPRODUCED", "INCONCLUSIVE", "EXECUTION_ERROR", null];

const repo = {
  id: "r1", project_id: "p1", source_type: "archive", sha256: "abcdef0123456789", created_at: NOW,
  layout: { layout: "flat", python_file_count: 2, packages: ["accounts"], source_roots: ["."],
    manifests: [], requirements_files: [], test_dirs: [], conftest_files: [], pytest_config: null },
} as Repository;

const investigations: InvestigationSummary[] = OUTCOMES.map((outcome, i) => ({
  id: `id-${i}`, project_id: "p1", repository_id: "r1", title: `Bug number ${i}`,
  state: outcome ? "COMPLETED" : "EXECUTING_TEST", outcome, outcome_reason: null,
  created_at: NOW, updated_at: NOW, completed_at: null,
}));

beforeEach(() => {
  for (const fn of Object.values(mocked)) fn.mockReset();
  mocked.projects.mockResolvedValue([{ id: "p1", name: "Demo", created_at: NOW }]);
  mocked.repositories.mockResolvedValue([repo]);
  mocked.investigations.mockResolvedValue(investigations);
});
afterEach(cleanup);

async function clean(container: HTMLElement) {
  expect(await violations(container)).toEqual([]);
}

describe("pages have no accessibility violations", () => {
  it("dashboard", async () => {
    const { container } = render(<Dashboard />);
    await screen.findByText(/Recent investigations/);
    await clean(container);
  });

  it("dashboard before the first project", async () => {
    mocked.projects.mockResolvedValue([]);
    const { container } = render(<Dashboard />);
    await screen.findByText(/Reproduce your first bug/);
    await clean(container);
  });

  it("investigations list", async () => {
    const { container } = render(<InvestigationHistory />);
    await screen.findByText("Bug number 0");
    await clean(container);
  });

  it("investigations list with nothing matching", async () => {
    const { container } = render(<InvestigationHistory />);
    await screen.findByText("Bug number 0");
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "zzz" } });
    await clean(container);
  });

  it("new investigation, with the detail section open and an over-long field", async () => {
    const { container } = render(<AnnouncerProvider><NewInvestigation /></AnnouncerProvider>);
    await screen.findByLabelText(/^Title/);
    container.querySelector("details")!.open = true;
    fireEvent.change(screen.getByLabelText(/^Description/), { target: { value: "y".repeat(20_005) } });
    fireEvent.blur(screen.getByLabelText(/^Title/));
    await clean(container);
  });

  it("new investigation before any project", async () => {
    mocked.projects.mockResolvedValue([]);
    const { container } = render(<NewInvestigation />);
    await screen.findByLabelText(/project name/i);
    await clean(container);
  });

  it("projects", async () => {
    const { container } = render(<Projects />);
    await screen.findByText("Demo");
    await clean(container);
  });
});

describe("investigation page in every state", () => {
  const states: [string, Parameters<typeof makeReport>[0]][] = [
    ["reproduced", {}],
    ["not reproduced", { outcome: "NOT_REPRODUCED", outcome_reason: "no_failure_observed", evidence: ["test passed under the tested conditions"] }],
    ["inconclusive", { outcome: "INCONCLUSIVE", outcome_reason: "control_failed", evidence: [] }],
    ["running", { state: "EXECUTING_TEST", outcome: null, outcome_reason: null, completed_at: null, evidence: [] }],
    ["queued", { state: "CREATED", outcome: null, outcome_reason: null, completed_at: null, attempts: [], evidence: [] }],
    ["failed", { state: "FAILED", outcome: null, outcome_reason: null, error: { type: "SandboxUnavailable", detail: "docker is not reachable", retryable: true } }],
    ["cancelled", { state: "CANCELLED", outcome: null, outcome_reason: null }],
  ];

  it.each(states)("%s", async (_name, over) => {
    const report = makeReport({
      attempts: [makeAttempt(1, [makeRun(0), makeRun(1)])],
      next_steps: ["Run the exported test locally."], limitations: ["Not provided in the report: stack_trace."],
      relevant_files: [{ file: "accounts/registration.py", score: 3, reasons: ["symbol matches"], symbols: [], sent_to_model: true }],
      ...over,
    });
    mocked.investigation.mockResolvedValue(report);
    const { container } = render(<AnnouncerProvider><InvestigationWorkspace /></AnnouncerProvider>);
    await screen.findByRole("heading", { level: 2 });
    await clean(container);
  });
});

describe("shared pieces", () => {
  it("header, navigation, theme toggle and skip link", async () => {
    const { container } = render(<><SkipLink /><AppHeader /></>);
    await clean(container);
  });

  it("breadcrumbs", async () => {
    const { container } = render(
      <Breadcrumbs items={[{ label: "Investigations", href: "/investigations" }, { label: "A bug" }]} />);
    await clean(container);
  });

  it("verdict banner for every outcome", async () => {
    for (const over of [{}, { outcome: "NOT_REPRODUCED" as const }, { outcome: "INCONCLUSIVE" as const }]) {
      const { container, unmount } = render(<VerdictBanner report={makeReport(over)} />);
      await clean(container);
      unmount();
    }
  });

  it("report strength panel", async () => {
    const { container } = render(<ReportStrength values={EMPTY_VALUES} />);
    await clean(container);
  });

  it("archive drop zone, including its error state", async () => {
    const { container } = render(<ArchiveDropzone projectId="p1" onUploaded={vi.fn()} />);
    fireEvent.change(screen.getByLabelText("Repository archive"), {
      target: { files: [new File(["x"], "bad.rar")] },
    });
    await screen.findByRole("alert");
    await clean(container);
  });

  it("the open cancel confirmation dialog", async () => {
    render(<CancelInvestigation onConfirm={vi.fn()} busy={false} />);
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    await screen.findByRole("alertdialog");
    await waitFor(async () => expect(await violations(document.body)).toEqual([]));
  });
});
