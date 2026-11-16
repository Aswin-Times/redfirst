import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { Breadcrumbs } from "@/components/breadcrumbs";
import { useDocumentTitle } from "@/hooks/use-document-title";
import { investigationTitle } from "@/lib/titles";
import { makeReport } from "@/lib/test-fixtures";

vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...rest}>{children}</a>
  ),
}));

afterEach(cleanup);

describe("Breadcrumbs", () => {
  const items = [{ label: "Investigations", href: "/investigations" }, { label: "register crashes" }];

  it("is a labelled navigation listing the path", () => {
    render(<Breadcrumbs items={items} />);
    const nav = screen.getByRole("navigation", { name: "Breadcrumb" });
    expect(within(nav).getAllByRole("listitem")).toHaveLength(2);
  });

  it("links the ancestors and marks the current page without a link", () => {
    render(<Breadcrumbs items={items} />);
    expect(screen.getByRole("link", { name: "Investigations" }).getAttribute("href")).toBe("/investigations");
    expect(screen.getByRole("link", { name: "Investigations" }).className).toContain("min-h-6");
    expect(screen.queryByRole("link", { name: "register crashes" })).toBeNull();
    expect(screen.getByText("register crashes").getAttribute("aria-current")).toBe("page");
  });

  it("keeps a very long title on one line but readable in full", () => {
    const long = "A very long bug title ".repeat(10).trim();
    render(<Breadcrumbs items={[{ label: "Investigations", href: "/investigations" }, { label: long }]} />);
    const current = screen.getByText(long);
    expect(current.className).toContain("truncate");
    expect(current.getAttribute("title")).toBe(long);
  });
});

describe("investigationTitle", () => {
  it.each([
    [{}, "Reproduced: t"],
    [{ outcome: "NOT_REPRODUCED" as const }, "Not reproduced: t"],
    [{ outcome: "INCONCLUSIVE" as const }, "Inconclusive: t"],
    [{ outcome: null, state: "EXECUTING_TEST" as const }, "Running: t"],
    [{ outcome: null, state: "CREATED" as const }, "Queued: t"],
    [{ outcome: null, state: "FAILED" as const }, "Failed: t"],
    [{ outcome: null, state: "CANCELLED" as const }, "Cancelled: t"],
  ])("%j -> %s", (over, title) => {
    expect(investigationTitle(makeReport(over))).toBe(title);
  });
});

describe("useDocumentTitle", () => {
  function Page({ title }: { title: string }) {
    useDocumentTitle(title);
    return null;
  }

  it("sets the tab title with the product name", () => {
    render(<Page title="Reproduced: register crashes" />);
    expect(document.title).toBe("Reproduced: register crashes · REDFIRST");
  });

  it("follows the title as it changes", () => {
    const { rerender } = render(<Page title="Running: t" />);
    rerender(<Page title="Reproduced: t" />);
    expect(document.title).toBe("Reproduced: t · REDFIRST");
  });
});
