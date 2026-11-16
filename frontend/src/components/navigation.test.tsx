import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { NavLinks } from "@/components/nav-links";
import { SkipLink } from "@/components/skip-link";

let pathname = "/";
vi.mock("next/navigation", () => ({ usePathname: () => pathname }));
vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...rest}>{children}</a>
  ),
}));

afterEach(cleanup);

describe("SkipLink", () => {
  it("points at the main content and is the first thing in the document", () => {
    render(<SkipLink />);
    const link = screen.getByRole("link", { name: "Skip to content" });
    expect(link.getAttribute("href")).toBe("#main");
  });

  it("stays out of sight until it is focused", () => {
    render(<SkipLink />);
    const cls = screen.getByRole("link", { name: "Skip to content" }).className;
    expect(cls).toContain("sr-only");
    expect(cls).toContain("focus:not-sr-only");
  });
});

describe("NavLinks", () => {
  it("is a labelled navigation with the three sections", () => {
    render(<NavLinks />);
    const nav = screen.getByRole("navigation", { name: "Main" });
    expect(nav.querySelectorAll("a")).toHaveLength(3);
  });

  it.each([
    ["/", "Dashboard"],
    ["/investigations", "Investigations"],
    ["/investigations/abc", "Investigations"],
    ["/projects", "Projects"],
  ])("marks the current section for %s", (path, current) => {
    pathname = path;
    render(<NavLinks />);
    const marked = screen.getAllByRole("link").filter((l) => l.getAttribute("aria-current") === "page");
    expect(marked.map((l) => l.textContent)).toEqual([current]);
  });

  it("does not mark Investigations while writing a new one", () => {
    pathname = "/investigations/new";
    render(<NavLinks />);
    expect(screen.getAllByRole("link").some((l) => l.getAttribute("aria-current") === "page")).toBe(false);
  });

  it("gives every link a visible keyboard focus style", () => {
    pathname = "/";
    render(<NavLinks />);
    for (const link of screen.getAllByRole("link")) {
      expect(link.className).toContain("focus-visible:ring");
    }
  });
});
