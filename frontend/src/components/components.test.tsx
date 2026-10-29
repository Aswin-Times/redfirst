import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { toBugReport } from "@/components/pages/new-investigation";
import { StageProgress } from "@/components/stage-progress";
import { StatusBadge } from "@/components/status-badge";

afterEach(cleanup);

describe("StatusBadge", () => {
  it("shows the verified outcome when there is one", () => {
    render(<StatusBadge state="COMPLETED" outcome="NOT_REPRODUCED" />);
    expect(screen.getByText("Not reproduced")).toBeTruthy();
  });

  it("shows the pipeline state while running", () => {
    render(<StatusBadge state="EXECUTING_TEST" outcome={null} />);
    expect(screen.getByText("Executing")).toBeTruthy();
  });

  it("shows Queued before a worker claims it", () => {
    render(<StatusBadge state="CREATED" outcome={null} />);
    expect(screen.getByText("Queued")).toBeTruthy();
  });
});

describe("StageProgress", () => {
  it("marks the active step for assistive technology", () => {
    render(
      <StageProgress
        state="EXECUTING_TEST"
        timeline={["CREATED", "ANALYZING_REPORT", "ANALYZING_REPOSITORY", "GENERATING_TEST",
          "VALIDATING_TEST", "EXECUTING_TEST"].map((state) => ({
          state: state as never, at: "2026-01-01T00:00:00Z", message: "",
        }))}
      />,
    );
    const current = document.querySelector('[aria-current="step"]');
    expect(current?.textContent).toContain("Sandbox execution");
    expect(screen.getAllByText("done")).toHaveLength(4);
  });
});

describe("toBugReport", () => {
  it("turns blank optional fields into null so they are recorded as missing", () => {
    const report = toBugReport("  Crash  ", "", {
      expected_behavior: "a validation error",
      actual_behavior: "   ",
      reproduction_steps: "",
      stack_trace: "",
      environment: "",
    });
    expect(report).toEqual({
      title: "Crash",
      description: "",
      expected_behavior: "a validation error",
      actual_behavior: null,
      reproduction_steps: null,
      stack_trace: null,
      environment: null,
    });
  });
});
