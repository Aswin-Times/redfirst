import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { EvidenceSummary } from "@/components/evidence-summary";

afterEach(cleanup);

const TARGET = [
  "KeyError: 'username'",
  "failure raised inside target code",
  "target frame accounts/registration.py:register",
  "pytest exit code observed by the runner: 1",
];

describe("EvidenceSummary", () => {
  it("lays a failure inside target code out by meaning", () => {
    render(<EvidenceSummary lines={TARGET} terminal />);
    expect(screen.getByText("KeyError")).toBeTruthy();
    expect(screen.getByText("'username'")).toBeTruthy();
    expect(screen.getByText("Raised inside the target code")).toBeTruthy();
    const where = screen.getByRole("list");
    expect(within(where).getByText("accounts/registration.py")).toBeTruthy();
    expect(within(where).getByText("in register()")).toBeTruthy();
    expect(within(where).getByText("target code")).toBeTruthy();
    expect(screen.getByText(/read from the container by the runner/)).toBeTruthy();
  });

  it("keeps every original line available as raw evidence", () => {
    const { container } = render(<EvidenceSummary lines={TARGET} terminal />);
    const raw = container.querySelector("details pre");
    for (const line of TARGET) expect(raw?.textContent).toContain(line);
    expect(screen.getByText("Raw evidence (4 lines)")).toBeTruthy();
  });

  it("shows a line it does not recognise instead of dropping it", () => {
    render(<EvidenceSummary lines={["a brand new kind of evidence"]} terminal />);
    expect(screen.getAllByText("a brand new kind of evidence").length).toBeGreaterThan(0);
    expect(screen.queryByText("Failure observed")).toBeNull();
  });

  it("points a wrong-value failure at the generated test", () => {
    render(<EvidenceSummary terminal lines={[
      "AssertionError: assert 4 == 5",
      "assertion on target code's result failed in the main test",
      "assertion in the generated test at test_reproduces_bug",
    ]} />);
    expect(screen.getByText(/failed assertion on the value the target code returned/)).toBeTruthy();
    expect(screen.getByText("test_redfirst.py")).toBeTruthy();
    expect(screen.getByText("generated test")).toBeTruthy();
  });

  it("explains an empty result differently while running and when finished", () => {
    render(<EvidenceSummary lines={[]} terminal={false} />);
    expect(screen.getByText(/appears once a test has run/)).toBeTruthy();
    cleanup();
    render(<EvidenceSummary lines={[]} terminal />);
    expect(screen.getByText(/no execution evidence/)).toBeTruthy();
  });
});
