import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

import {
  EMPTY_VALUES, LIMITS, UPLOAD_MAX_BYTES, checklist, counterState, fieldProblems, parseDraft,
  serializeDraft, submitBlocker, toBugReport, type FormValues,
} from "@/lib/report-form";

const values = (over: Partial<FormValues> = {}): FormValues => ({ ...EMPTY_VALUES, ...over });
const backend = (file: string) => readFileSync(resolve(process.cwd(), "..", "backend", file), "utf-8");

describe("limits mirror the backend", () => {
  it("matches every field limit in analysis/report.py", () => {
    const source = backend("redfirst/analysis/report.py");
    for (const [field, limit] of Object.entries(LIMITS)) {
      const m = new RegExp(`${field}: [^\\n]*max_length=([\\d_]+)`).exec(source);
      expect(m, `${field} not found in the backend model`).not.toBeNull();
      expect(Number(m![1].replaceAll("_", "")), field).toBe(limit);
    }
  });

  it("matches the default upload limit in core/config.py", () => {
    const m = /upload_max_bytes: int = (\d+) \* 1024 \* 1024/.exec(backend("redfirst/core/config.py"));
    expect(Number(m![1]) * 1024 * 1024).toBe(UPLOAD_MAX_BYTES);
  });
});

describe("toBugReport", () => {
  it("trims, and turns blank optional fields into null so they are recorded as missing", () => {
    expect(toBugReport(values({ title: "  Crash  ", expected_behavior: "a validation error",
      actual_behavior: "   " }))).toEqual({
      title: "Crash", description: "", expected_behavior: "a validation error",
      actual_behavior: null, reproduction_steps: null, stack_trace: null, environment: null,
    });
  });
});

describe("fieldProblems", () => {
  it("requires a title", () => {
    expect(fieldProblems(values()).title).toBe("Add a title.");
    expect(fieldProblems(values({ title: "   " })).title).toBe("Add a title.");
    expect(fieldProblems(values({ title: "x" })).title).toBeUndefined();
  });

  it("says how far over the limit a field is", () => {
    const over = fieldProblems(values({ title: "x", stack_trace: "y".repeat(LIMITS.stack_trace + 12) }));
    expect(over.stack_trace).toBe("12 characters over the limit of 50,000.");
    expect(fieldProblems(values({ title: "x", environment: "y".repeat(LIMITS.environment + 1) }))
      .environment).toBe("1 character over the limit of 5,000.");
  });

  it("accepts exactly the limit", () => {
    expect(fieldProblems(values({ title: "x".repeat(LIMITS.title) }))).toEqual({});
  });
});

describe("counterState", () => {
  it.each([[0, 100, "hidden"], [79, 100, "hidden"], [80, 100, "near"], [100, 100, "near"],
    [101, 100, "over"]])("%d of %d -> %s", (n, limit, want) => {
    expect(counterState(n, limit)).toBe(want);
  });
});

describe("submitBlocker", () => {
  const ok = { projectId: "p", repositoryId: "r", values: values({ title: "t" }), busy: false };

  it("is null when the form can be submitted", () => {
    expect(submitBlocker(ok)).toBeNull();
  });

  it.each([
    [{ projectId: "" }, "Create or choose a project."],
    [{ repositoryId: "" }, "Choose or upload a repository."],
    [{ values: values({ title: " " }) }, "Add a title."],
    [{ values: values({ title: "t", description: "y".repeat(LIMITS.description + 1) }) },
      "Shorten the description."],
    [{ busy: true }, "Working…"],
  ])("explains the first thing missing: %j", (over, why) => {
    expect(submitBlocker({ ...ok, ...over })).toBe(why);
  });
});

describe("checklist", () => {
  it("states the real consequence of a missing expected behavior", () => {
    const item = checklist(values()).find((c) => c.key === "expected_behavior")!;
    expect(item.provided).toBe(false);
    expect(item.effect).toMatch(/at most Inconclusive/);
  });

  it("marks what was provided and ignores whitespace-only fields", () => {
    const items = checklist(values({ expected_behavior: "x", actual_behavior: "  ", stack_trace: "Traceback" }));
    const by = Object.fromEntries(items.map((c) => [c.key, c.provided]));
    expect(by).toEqual({
      expected_behavior: true, actual_behavior: false, reproduction_steps: false,
      stack_trace: true, environment: false,
    });
  });

  it("gives every item an effect for both states", () => {
    for (const filled of [true, false]) {
      const v = values(filled ? Object.fromEntries(
        ["expected_behavior", "actual_behavior", "reproduction_steps", "stack_trace", "environment"]
          .map((k) => [k, "x"])) : {});
      for (const item of checklist(v)) expect(item.effect.length).toBeGreaterThan(15);
    }
  });
});

describe("drafts", () => {
  it("round-trips the form", () => {
    const v = values({ title: "t", expected_behavior: "e", stack_trace: "s" });
    expect(parseDraft(serializeDraft(v))).toEqual(v);
  });

  it.each([null, "", "not json", "[]", "42", '"str"', '{"title": 5}', "{}"])(
    "ignores unusable draft %j", (raw) => expect(parseDraft(raw)).toBeNull());

  it("keeps the usable fields of a damaged draft and drops the rest", () => {
    expect(parseDraft('{"title":"t","description":7,"extra":"x","environment":"py3"}')).toEqual(
      values({ title: "t", environment: "py3" }));
  });

  it("clips a field longer than its limit instead of failing", () => {
    const draft = parseDraft(JSON.stringify({ title: "x".repeat(LIMITS.title + 50) }));
    expect(draft?.title.length).toBe(LIMITS.title);
  });

  it("does not offer an empty draft", () => {
    expect(parseDraft(serializeDraft(values()))).toBeNull();
  });
});
