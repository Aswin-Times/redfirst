import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { InvestigationHistory } from "@/components/pages/investigation-history";
import { api } from "@/lib/api";
import type { InvestigationSummary, Outcome } from "@/lib/types";

vi.mock("next/navigation", () => ({ useSearchParams: () => new URLSearchParams(window.location.search) }));
vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...rest}>{children}</a>
  ),
}));
vi.mock("@/lib/api", () => ({ api: { projects: vi.fn(), investigations: vi.fn() } }));

const mocked = vi.mocked(api);
const OUTCOMES: (Outcome | null)[] = ["REPRODUCED", "NOT_REPRODUCED", "INCONCLUSIVE", null];

function make(n: number): InvestigationSummary[] {
  return Array.from({ length: n }, (_, k) => {
    const i = k + 1;
    const outcome = OUTCOMES[i % OUTCOMES.length];
    return {
      id: `id-${String(i).padStart(3, "0")}`, project_id: "p1", repository_id: "r", title: `Bug ${i}`,
      state: outcome ? "COMPLETED" : "EXECUTING_TEST", outcome, outcome_reason: null,
      created_at: `2026-01-${String(i).padStart(2, "0")}T00:00:00`,
      updated_at: "2026-01-01T00:00:00", completed_at: null,
    } as InvestigationSummary;
  });
}

const rows = (container: HTMLElement) =>
  [...container.querySelectorAll("tbody tr")].map((r) => r.querySelector("a")!.textContent);
const search = () => screen.getByRole("searchbox", { name: "Search investigations" }) as HTMLInputElement;
const select = (name: string) => screen.getByLabelText(name) as HTMLSelectElement;

async function ready(n = 30, url = "/investigations") {
  window.history.replaceState(null, "", url);
  mocked.projects.mockResolvedValue([{ id: "p1", name: "Demo", created_at: "2026-01-01T00:00:00" }]);
  mocked.investigations.mockResolvedValue(make(n));
  const view = render(<InvestigationHistory />);
  await screen.findByRole("searchbox", { name: "Search investigations" });
  await waitFor(() => expect(view.container.querySelectorAll("tbody tr").length).toBeGreaterThan(0));
  return view;
}

beforeEach(() => {
  mocked.projects.mockReset();
  mocked.investigations.mockReset();
});
afterEach(cleanup);

describe("controls", () => {
  it("has a labelled search landmark with search, project, result and sort", async () => {
    await ready();
    const landmark = screen.getByRole("search");
    expect(within(landmark).getByRole("searchbox", { name: "Search investigations" })).toBeTruthy();
    for (const name of ["Project", "Result", "Sort"]) expect(within(landmark).getByLabelText(name)).toBeTruthy();
  });
});

describe("paging", () => {
  it("shows 25 at first and says how many there are", async () => {
    const { container } = await ready(30);
    expect(rows(container)).toHaveLength(25);
    expect(screen.getByText("Showing 25 of 30")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Show 5 more" })).toBeTruthy();
  });

  it("shows the rest on request and moves focus to the first new row", async () => {
    const { container } = await ready(30);
    fireEvent.click(screen.getByRole("button", { name: "Show 5 more" }));
    await waitFor(() => expect(rows(container)).toHaveLength(30));
    expect(screen.getByText("30 investigations")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /show .* more/i })).toBeNull();
    await waitFor(() => expect(document.activeElement?.textContent).toBe("Bug 5"));
  });

  it("offers no button when everything fits", async () => {
    await ready(10);
    expect(screen.getByText("10 investigations")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /show .* more/i })).toBeNull();
  });
});

describe("search", () => {
  it("filters by title, updates the count and the URL", async () => {
    const { container } = await ready(30);
    fireEvent.change(search(), { target: { value: "bug 2" } });
    // Bug 2, Bug 20..Bug 29
    expect(rows(container)).toHaveLength(11);
    expect(screen.getByText("11 investigations matching · 30 in total")).toBeTruthy();
    expect(window.location.search).toBe("?q=bug+2");
  });

  it("finds an investigation by the start of its id", async () => {
    const { container } = await ready(30);
    fireEvent.change(search(), { target: { value: "id-007" } });
    expect(rows(container)).toEqual(["Bug 7"]);
  });

  it("says so, with a way out, when nothing matches", async () => {
    await ready(30);
    fireEvent.change(search(), { target: { value: "zzz" } });
    expect(screen.getByText("Nothing matches these filters")).toBeTruthy();
    fireEvent.click(screen.getAllByRole("button", { name: "Clear filters" })[0]);
    expect(search().value).toBe("");
    expect(window.location.search).toBe("");
  });
});

describe("sort and filters", () => {
  it("sorts newest first by default and can reverse it", async () => {
    const { container } = await ready(30);
    expect(rows(container)[0]).toBe("Bug 30");
    fireEvent.change(select("Sort"), { target: { value: "oldest" } });
    expect(rows(container)[0]).toBe("Bug 1");
    expect(window.location.search).toBe("?sort=oldest");
  });

  it("filters by result", async () => {
    const { container } = await ready(30);
    fireEvent.change(select("Result"), { target: { value: "REPRODUCED" } });
    expect(rows(container).every((t) => OUTCOMES[Number(t!.slice(4)) % 4] === "REPRODUCED")).toBe(true);
    expect(window.location.search).toBe("?result=REPRODUCED");
  });

  it("asks the API for one project's investigations", async () => {
    await ready(30);
    mocked.investigations.mockClear();
    fireEvent.change(select("Project"), { target: { value: "p1" } });
    await waitFor(() => expect(mocked.investigations).toHaveBeenCalledWith("p1"));
    expect(window.location.search).toBe("?project=p1");
  });

  it("starts from the filters in the URL", async () => {
    const { container } = await ready(30, "/investigations?q=bug&result=REPRODUCED&sort=oldest");
    expect(search().value).toBe("bug");
    expect(select("Result").value).toBe("REPRODUCED");
    expect(select("Sort").value).toBe("oldest");
    const titles = rows(container).map((t) => Number(t!.slice(4)));
    expect(titles).toEqual([...titles].sort((a, b) => a - b));
  });

  it("clears everything at once", async () => {
    await ready(30, "/investigations?q=bug&sort=oldest&result=REPRODUCED");
    fireEvent.click(screen.getByRole("button", { name: "Clear filters" }));
    expect(search().value).toBe("");
    expect(select("Result").value).toBe("");
    expect(select("Sort").value).toBe("newest");
    expect(window.location.search).toBe("");
  });

  it("only shows Clear filters while a filter is active", async () => {
    await ready(30);
    expect(screen.queryByRole("button", { name: "Clear filters" })).toBeNull();
    fireEvent.change(search(), { target: { value: "bug 1" } });
    expect(screen.getByRole("button", { name: "Clear filters" })).toBeTruthy();
  });
});
