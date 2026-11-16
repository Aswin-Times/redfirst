import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { AnnouncerProvider, useAnnounce } from "@/components/announcer";

afterEach(cleanup);

function Say({ message }: { message: string }) {
  const announce = useAnnounce();
  return <button onClick={() => announce(message)}>say</button>;
}

const say = () => fireEvent.click(screen.getByRole("button", { name: "say" }));

describe("Announcer", () => {
  it("renders one polite, visually hidden status region", () => {
    render(<AnnouncerProvider><Say message="x" /></AnnouncerProvider>);
    const region = screen.getByRole("status");
    expect(region.getAttribute("aria-live")).toBe("polite");
    expect(region.className).toContain("sr-only");
    expect(region.textContent).toBe("");
  });

  it("puts an announcement into the region", () => {
    render(<AnnouncerProvider><Say message="Investigation cancelled" /></AnnouncerProvider>);
    say();
    expect(screen.getByRole("status").textContent?.trim()).toBe("Investigation cancelled");
  });

  it("changes the text even when the same message is announced twice, so it is read again", () => {
    render(<AnnouncerProvider><Say message="Repository added" /></AnnouncerProvider>);
    say();
    const first = screen.getByRole("status").textContent;
    say();
    const second = screen.getByRole("status").textContent;
    expect(second).not.toBe(first);
    expect(second?.trim()).toBe("Repository added");
  });

  it("is a harmless no-op outside a provider", () => {
    render(<Say message="anything" />);
    expect(() => say()).not.toThrow();
  });
});
