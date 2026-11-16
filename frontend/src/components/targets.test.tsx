import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { InvestigationsTable } from "@/components/investigations-table";
import { TableHead } from "@/components/ui/table";
import type { InvestigationSummary } from "@/lib/types";

vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...rest}>{children}</a>
  ),
}));

afterEach(cleanup);

const inv = (id: string, title: string): InvestigationSummary => ({
  id, project_id: "p", repository_id: "r", title, state: "COMPLETED", outcome: "REPRODUCED",
  outcome_reason: "matching_failure", created_at: "2026-01-01T00:00:00",
  updated_at: "2026-01-01T00:00:00", completed_at: null,
});

describe("tables", () => {
  it("scopes every column header, so a screen reader can tie cells to their column", () => {
    render(<InvestigationsTable items={[inv("a", "one")]} />);
    const heads = screen.getAllByRole("columnheader");
    expect(heads.length).toBeGreaterThan(0);
    for (const th of heads) expect(th.getAttribute("scope")).toBe("col");
  });

  it("lets a header override the default scope", () => {
    render(<table><thead><tr><TableHead scope="row">x</TableHead></tr></thead></table>);
    expect(screen.getByRole("rowheader").getAttribute("scope")).toBe("row");
  });
});

describe("click targets", () => {
  it("makes the whole row the target for its title link, not a 20 px strip of text", () => {
    const { container } = render(<InvestigationsTable items={[inv("a", "one"), inv("b", "two")]} />);
    const rows = container.querySelectorAll("tbody tr");
    expect(rows).toHaveLength(2);
    for (const row of rows) {
      expect(row.className).toContain("relative");
      const link = row.querySelector("a")!;
      expect(link.className).toContain("after:absolute");
      expect(link.className).toContain("after:inset-0");
    }
  });

  it("keeps a visible keyboard focus style on the row link", () => {
    render(<InvestigationsTable items={[inv("a", "one")]} />);
    expect(screen.getByRole("link", { name: "one" }).className).toContain("focus-visible:ring");
  });
});
