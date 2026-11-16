import { describe, expect, it } from "vitest";

import { displayPath, parseEvidence } from "@/lib/evidence";

// The strings below are exactly what backend/redfirst/verification/rules.py produces.
const REPRODUCED_IN_TARGET = [
  "KeyError: 'username'",
  "failure raised inside target code",
  "target frame accounts/registration.py:register",
  "target frame accounts/validators.py:check",
  "pytest exit code observed by the runner: 1",
];

const REPRODUCED_WRONG_VALUE = [
  "AssertionError: assert 4 == 5",
  "assertion on target code's result failed in the main test",
  "assertion in the generated test at test_reproduces_bug",
  "pytest exit code observed by the runner: 1",
];

describe("parseEvidence", () => {
  it("splits a failure inside target code into its parts", () => {
    const p = parseEvidence(REPRODUCED_IN_TARGET);
    expect(p.failure).toEqual({ type: "KeyError", message: "'username'" });
    expect(p.origin).toBe("target");
    expect(p.locations).toEqual([
      { path: "accounts/registration.py", function: "register", kind: "target" },
      { path: "accounts/validators.py", function: "check", kind: "target" },
    ]);
    expect(p.exitCode).toBe(1);
    expect(p.notes).toEqual([]);
  });

  it("recognises a wrong-value assertion and points at the generated test", () => {
    const p = parseEvidence(REPRODUCED_WRONG_VALUE);
    expect(p.failure?.type).toBe("AssertionError");
    expect(p.origin).toBe("assertion");
    expect(p.locations).toEqual([
      { path: "test_redfirst.py", function: "test_reproduces_bug", kind: "test" },
    ]);
  });

  it("keeps a message that itself contains colons and newlines", () => {
    const p = parseEvidence(["ValueError: bad value: 'a:b'\nsecond line", "pytest exit code observed by the runner: 1"]);
    expect(p.failure).toEqual({ type: "ValueError", message: "bad value: 'a:b'\nsecond line" });
  });

  it.each([
    ["main test status: skipped"],
    ["control test status: failed"],
    ["test passed under the tested conditions"],
    ["failure before the test body ran: ImportError: no module named x"],
    ["got ValueError: boom"],
    ["no traceback frame in a target file inside the repository"],
    ["run outcomes differed: ['REPRODUCED', 'INCONCLUSIVE']"],
  ])("does not mistake %j for a failure", (line) => {
    const p = parseEvidence([line]);
    expect(p.failure).toBeNull();
    expect(p.notes).toEqual([line]);
  });

  it("keeps every unrecognised line, in order, so nothing is hidden", () => {
    const p = parseEvidence(["something new", "KeyError: 'x'", "another new thing"]);
    // Only the first line can be the failure; later lines stay visible.
    expect(p.failure).toBeNull();
    expect(p.notes).toEqual(["something new", "KeyError: 'x'", "another new thing"]);
  });

  it("reads the older 'frame <absolute path>:<function>' format used by stored reports", () => {
    const p = parseEvidence([
      "KeyError: 'username'",
      "failure raised inside target code",
      String.raw`frame C:\Users\me\.venv\Lib\site-packages\_pytest\python.py:pytest_pyfunc_call`,
      String.raw`frame C:\work\run-1\gen\test_redfirst.py:test_reproduces_bug`,
      String.raw`frame C:\work\run-1\repo\accounts\registration.py:register`,
    ]);
    expect(p.locations).toEqual([
      { path: "site-packages/_pytest/python.py", function: "pytest_pyfunc_call", kind: "library" },
      { path: "test_redfirst.py", function: "test_reproduces_bug", kind: "test" },
      { path: "accounts/registration.py", function: "register", kind: "code" },
    ]);
  });

  it("returns an empty result for no evidence", () => {
    expect(parseEvidence([])).toEqual({
      failure: null, origin: null, locations: [], exitCode: null, notes: [],
    });
  });
});

describe("displayPath", () => {
  it.each([
    ["accounts/registration.py", "accounts/registration.py"],
    [String.raw`C:\work\run-1\repo\accounts\registration.py`, "accounts/registration.py"],
    ["/tmp/work/run-1/repo/accounts/registration.py", "accounts/registration.py"],
    ["/repo/app/users.py", "app/users.py"],
    [String.raw`C:\Users\me\.venv\Lib\site-packages\_pytest\python.py`, "site-packages/_pytest/python.py"],
    ["/usr/lib/python3.12/site-packages/pytest/main.py", "site-packages/pytest/main.py"],
    ["/gen/test_redfirst.py", "test_redfirst.py"],
  ])("%s -> %s", (raw, shown) => {
    expect(displayPath(raw).path).toBe(shown);
  });

  it("classifies what the path is", () => {
    expect(displayPath("/gen/test_redfirst.py").kind).toBe("test");
    expect(displayPath("/x/site-packages/a.py").kind).toBe("library");
    expect(displayPath("/work/repo/a.py").kind).toBe("code");
    expect(displayPath("accounts/a.py").kind).toBe("code");
  });
});
