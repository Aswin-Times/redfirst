import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { NewInvestigation } from "@/components/pages/new-investigation";
import { api } from "@/lib/api";
import { DRAFT_KEY, LIMITS } from "@/lib/report-form";
import { SAMPLE } from "@/lib/sample";
import type { Project, Repository } from "@/lib/types";

const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));
vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...rest}>{children}</a>
  ),
}));
vi.mock("@/lib/api", () => ({
  api: {
    projects: vi.fn(), repositories: vi.fn(), createProject: vi.fn(),
    uploadRepository: vi.fn(), createInvestigation: vi.fn(),
  },
}));

const mocked = vi.mocked(api);
const project = (id = "p1", name = "Demo"): Project => ({ id, name, created_at: "2026-01-01T00:00:00" });
const repo = (id = "r1", projectId = "p1"): Repository => ({
  id, project_id: projectId, source_type: "archive", sha256: "abcdef0123456789",
  layout: { layout: "flat", python_file_count: 2, packages: ["accounts"], source_roots: ["."],
    manifests: [], requirements_files: [], test_dirs: [], conftest_files: [], pytest_config: null },
  created_at: new Date().toISOString().replace("Z", ""),
});

const field = (name: RegExp) => screen.getByLabelText(name) as HTMLInputElement | HTMLTextAreaElement;
const type = (name: RegExp, value: string) => fireEvent.change(field(name), { target: { value } });
const start = () => screen.getByRole("button", { name: /start investigation/i }) as HTMLButtonElement;

beforeEach(() => {
  for (const fn of Object.values(mocked)) fn.mockReset();
  push.mockReset();
  localStorage.clear();
  mocked.projects.mockResolvedValue([project()]);
  mocked.repositories.mockResolvedValue([repo()]);
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

async function ready() {
  render(<NewInvestigation />);
  await screen.findByLabelText(/^Title/);
  await waitFor(() => expect((field(/^Repository$/) as unknown as HTMLSelectElement).value).toBe("r1"));
}

describe("layout", () => {
  it("shows the code, the essentials and the optional detail in that order", async () => {
    await ready();
    const headings = screen.getAllByRole("heading", { level: 2 }).map((h) => h.textContent);
    expect(headings).toEqual(["Code", "The bug", "More detail"]);
    expect(field(/^Expected behavior/)).toBeTruthy();
    expect(field(/^Actual behavior/)).toBeTruthy();
  });

  it("keeps the optional detail collapsed until it is wanted", async () => {
    const { container } = render(<NewInvestigation />);
    await screen.findByLabelText(/^Title/);
    expect((container.querySelector("details") as HTMLDetailsElement).open).toBe(false);
  });

  it("gives each field an example", async () => {
    await ready();
    expect(screen.getByText(/e\.g\. Registration crashes/)).toBeTruthy();
    expect(screen.getByText(/e\.g\. register\(\) raises ValueError/)).toBeTruthy();
  });
});

describe("report strength", () => {
  it("starts by warning that no expected behavior caps the result, and clears it when given", async () => {
    await ready();
    const panel = screen.getByRole("complementary", { name: "What REDFIRST will use" });
    expect(within(panel).getByText(/at most Inconclusive/)).toBeTruthy();
    type(/^Expected behavior/, "It should raise ValueError");
    expect(within(panel).queryByText(/at most Inconclusive/)).toBeNull();
  });
});

describe("submit button", () => {
  it("says what is missing and enables once the form can be sent", async () => {
    await ready();
    expect(start().disabled).toBe(true);
    expect(screen.getByText("Add a title.", { selector: "#submit-hint" })).toBeTruthy();
    type(/^Title/, "Crash on empty username");
    expect(start().disabled).toBe(false);
    expect(document.querySelector("#submit-hint")?.textContent).toBe("");
  });

  it("blocks and explains an over-long field", async () => {
    await ready();
    type(/^Title/, "t");
    type(/^Description/, "y".repeat(LIMITS.description + 3));
    expect(start().disabled).toBe(true);
    expect(document.querySelector("#submit-hint")?.textContent).toBe("Shorten the description.");
    expect(screen.getByText("3 characters over the limit of 20,000.")).toBeTruthy();
    expect(field(/^Description/).getAttribute("aria-invalid")).toBe("true");
  });

  it("shows a counter only when a field is close to its limit", async () => {
    await ready();
    expect(screen.queryByText(/\/ 300/)).toBeNull();
    type(/^Title/, "x".repeat(250));
    expect(screen.getByText("250 / 300")).toBeTruthy();
  });
});

describe("submitting", () => {
  it("sends the trimmed report and opens the investigation", async () => {
    mocked.createInvestigation.mockResolvedValue({ id: "inv1" } as never);
    await ready();
    type(/^Title/, "  Crash  ");
    type(/^Expected behavior/, "a validation error");
    fireEvent.click(start());
    await waitFor(() => expect(push).toHaveBeenCalledWith("/investigations/inv1"));
    expect(mocked.createInvestigation).toHaveBeenCalledWith("p1", "r1", {
      title: "Crash", description: "", expected_behavior: "a validation error",
      actual_behavior: null, reproduction_steps: null, stack_trace: null, environment: null,
    });
  });

  it("submits with Ctrl+Enter from any field", async () => {
    mocked.createInvestigation.mockResolvedValue({ id: "inv2" } as never);
    await ready();
    type(/^Title/, "Crash");
    fireEvent.keyDown(field(/^Actual behavior/), { key: "Enter", ctrlKey: true });
    await waitFor(() => expect(push).toHaveBeenCalledWith("/investigations/inv2"));
  });

  it("does not submit with Ctrl+Enter while something is missing", async () => {
    await ready();
    fireEvent.keyDown(field(/^Actual behavior/), { key: "Enter", ctrlKey: true });
    expect(mocked.createInvestigation).not.toHaveBeenCalled();
  });

  it("keeps what was typed and shows the reason when the server refuses", async () => {
    mocked.createInvestigation.mockRejectedValue(new Error("too many unfinished investigations"));
    await ready();
    type(/^Title/, "Crash");
    fireEvent.click(start());
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toMatch(/too many unfinished investigations/);
    expect(field(/^Title/).value).toBe("Crash");
    expect(start().disabled).toBe(false);
    expect(push).not.toHaveBeenCalled();
  });
});

describe("drafts", () => {
  it("saves what is typed", async () => {
    await ready();
    type(/^Title/, "My draft title");
    await waitFor(() => expect(localStorage.getItem(DRAFT_KEY)).toContain("My draft title"), { timeout: 2000 });
  });

  it("restores a draft with a notice, and can discard it", async () => {
    localStorage.setItem(DRAFT_KEY, JSON.stringify({ title: "Saved earlier", stack_trace: "Traceback" }));
    await ready();
    expect(field(/^Title/).value).toBe("Saved earlier");
    expect(screen.getByText(/draft restored/i)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /discard/i }));
    expect(field(/^Title/).value).toBe("");
    expect(localStorage.getItem(DRAFT_KEY)).toBeNull();
    expect(screen.queryByText(/draft restored/i)).toBeNull();
  });

  it("opens the optional detail when the draft has some", async () => {
    localStorage.setItem(DRAFT_KEY, JSON.stringify({ title: "t", stack_trace: "Traceback" }));
    const { container } = render(<NewInvestigation />);
    await screen.findByLabelText(/^Title/);
    expect((container.querySelector("details") as HTMLDetailsElement).open).toBe(true);
  });

  it("forgets the draft after a successful submit", async () => {
    mocked.createInvestigation.mockResolvedValue({ id: "inv3" } as never);
    localStorage.setItem(DRAFT_KEY, JSON.stringify({ title: "Saved earlier" }));
    await ready();
    fireEvent.click(start());
    await waitFor(() => expect(push).toHaveBeenCalled());
    expect(localStorage.getItem(DRAFT_KEY)).toBeNull();
  });

  it("works when storage is blocked", async () => {
    const original = Storage.prototype.getItem;
    Storage.prototype.getItem = () => {
      throw new Error("blocked");
    };
    try {
      await ready();
      type(/^Title/, "still works");
      expect(field(/^Title/).value).toBe("still works");
    } finally {
      Storage.prototype.getItem = original;
    }
  });
});

describe("without a project", () => {
  beforeEach(() => mocked.projects.mockResolvedValue([]));

  it("offers to create one on the page instead of sending you away", async () => {
    mocked.createProject.mockImplementation(async () => {
      mocked.projects.mockResolvedValue([project("p9", "Mine")]);
      mocked.repositories.mockResolvedValue([]);
      return project("p9", "Mine");
    });
    render(<NewInvestigation />);
    await screen.findByLabelText(/project name/i);
    fireEvent.change(screen.getByLabelText(/project name/i), { target: { value: "Mine" } });
    fireEvent.click(screen.getByRole("button", { name: /create project/i }));
    await waitFor(() => expect(mocked.createProject).toHaveBeenCalledWith("Mine"));
    await waitFor(() => expect((field(/^Project$/) as unknown as HTMLSelectElement).value).toBe("p9"));
  });
});

describe("the sample", () => {
  const zip = () => vi.fn(async () => new Response(new Uint8Array([80, 75, 3, 4]), { status: 200 }));

  it("creates the sample project, uploads the archive and fills in the report", async () => {
    mocked.projects.mockResolvedValue([]);
    mocked.createProject.mockImplementation(async () => {
      mocked.projects.mockResolvedValue([project("ps", SAMPLE.projectName)]);
      return project("ps", SAMPLE.projectName);
    });
    mocked.repositories.mockResolvedValue([]);
    mocked.uploadRepository.mockImplementation(async () => {
      mocked.repositories.mockResolvedValue([repo("rs", "ps")]);
      return repo("rs", "ps");
    });
    vi.stubGlobal("fetch", zip());
    const { container } = render(<NewInvestigation />);
    fireEvent.click(await screen.findByRole("button", { name: /try a sample bug/i }));
    await waitFor(() => expect(field(/^Title/).value).toBe(SAMPLE.values.title));
    expect(mocked.createProject).toHaveBeenCalledWith(SAMPLE.projectName);
    const [projectId, file] = mocked.uploadRepository.mock.calls[0];
    expect(projectId).toBe("ps");
    expect((file as File).name).toBe(SAMPLE.archiveName);
    expect(field(/^Expected behavior/).value).toBe(SAMPLE.values.expected_behavior);
    expect(field(/^Stack trace/).value).toBe(SAMPLE.values.stack_trace);
    expect((container.querySelector("details") as HTMLDetailsElement).open).toBe(true);
    await waitFor(() => expect((field(/^Repository$/) as unknown as HTMLSelectElement).value).toBe("rs"));
  });

  it("reuses an existing sample project and repository instead of adding more", async () => {
    mocked.projects.mockResolvedValue([project("ps", SAMPLE.projectName)]);
    mocked.repositories.mockResolvedValue([repo("rs", "ps")]);
    render(<NewInvestigation />);
    fireEvent.click(await screen.findByRole("button", { name: /try a sample bug/i }));
    await waitFor(() => expect(field(/^Title/).value).toBe(SAMPLE.values.title));
    expect(mocked.createProject).not.toHaveBeenCalled();
    expect(mocked.uploadRepository).not.toHaveBeenCalled();
  });

  it("says so when the sample cannot be set up", async () => {
    mocked.projects.mockResolvedValue([]);
    mocked.createProject.mockRejectedValue(new Error("The REDFIRST API is not reachable."));
    render(<NewInvestigation />);
    fireEvent.click(await screen.findByRole("button", { name: /try a sample bug/i }));
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toMatch(/not reachable/);
    expect(field(/^Title/).value).toBe("");
  });
});
