import { describe, expect, it } from "vitest";

import {
  DEFAULT_STATE, PAGE_SIZE, applyView, matchesQuery, parseListParams, sortItems, toQuery,
} from "@/lib/list-view";
import type { InvestigationSummary, Outcome } from "@/lib/types";

const inv = (
  id: string, title: string, created: string, outcome: Outcome | null = "REPRODUCED",
): InvestigationSummary => ({
  id, project_id: "p", repository_id: "r", title, state: outcome ? "COMPLETED" : "EXECUTING_TEST",
  outcome, outcome_reason: null, created_at: created, updated_at: created, completed_at: null,
});

const params = (q: string) => parseListParams(new URLSearchParams(q));

describe("parseListParams", () => {
  it("defaults to everything, newest first", () => {
    expect(params("")).toEqual(DEFAULT_STATE);
    expect(DEFAULT_STATE).toEqual({ project: "", result: "", q: "", sort: "newest" });
  });

  it("reads every filter", () => {
    expect(params("project=p1&result=REPRODUCED&q=crash&sort=oldest")).toEqual({
      project: "p1", result: "REPRODUCED", q: "crash", sort: "oldest",
    });
    expect(params("result=running").result).toBe("running");
  });

  it("ignores values it does not understand", () => {
    expect(params("result=bogus&sort=sideways").result).toBe("");
    expect(params("result=bogus&sort=sideways").sort).toBe("newest");
  });

  it("trims the search and bounds its length", () => {
    expect(params("q=%20%20crash%20%20").q).toBe("crash");
    expect(params(`q=${"x".repeat(500)}`).q).toHaveLength(100);
  });
});

describe("toQuery", () => {
  it("is empty for the defaults, so the plain URL stays clean", () => {
    expect(toQuery(DEFAULT_STATE)).toBe("");
  });

  it("includes only what differs from the defaults", () => {
    expect(toQuery({ ...DEFAULT_STATE, result: "INCONCLUSIVE" })).toBe("?result=INCONCLUSIVE");
    expect(toQuery({ project: "p1", result: "", q: "a b", sort: "result" })).toBe(
      "?project=p1&q=a+b&sort=result");
  });

  it("round-trips through parseListParams", () => {
    const state = { project: "p1", result: "NOT_REPRODUCED" as const, q: "x & y", sort: "oldest" as const };
    expect(params(toQuery(state))).toEqual(state);
  });
});

describe("matchesQuery", () => {
  const item = inv("abcdef12-0000", "Register crashes without username", "2026-01-01T00:00:00");

  it.each([
    ["", true], ["register", true], ["CRASHES", true], ["without user", true],
    ["abcdef12", true], ["  crash  ", true], ["nothing like it", false], ["0000x", false],
  ])("%j -> %s", (q, want) => expect(matchesQuery(item, q)).toBe(want));
});

describe("sortItems", () => {
  const items = [
    inv("a", "old", "2026-01-01T00:00:00", "INCONCLUSIVE"),
    inv("b", "new", "2026-01-03T00:00:00", "REPRODUCED"),
    inv("c", "mid", "2026-01-02T00:00:00", null),
    inv("d", "mid2", "2026-01-02T12:00:00", "REPRODUCED"),
  ];
  const ids = (s: "newest" | "oldest" | "result") => sortItems(items, s).map((i) => i.id);

  it("newest and oldest by creation time", () => {
    expect(ids("newest")).toEqual(["b", "d", "c", "a"].sort((x, y) =>
      items.find((i) => i.id === y)!.created_at.localeCompare(items.find((i) => i.id === x)!.created_at)));
    expect(ids("oldest")).toEqual(["a", "c", "d", "b"]);
  });

  it("groups by result (reproduced first, still running last), newest first inside a group", () => {
    expect(ids("result")).toEqual(["b", "d", "a", "c"]);
  });

  it("does not change the input", () => {
    const before = items.map((i) => i.id);
    sortItems(items, "result");
    expect(items.map((i) => i.id)).toEqual(before);
  });

  it("reads the API's zone-less timestamps as UTC when comparing", () => {
    const x = inv("x", "t", "2026-01-01T10:00:00");
    const y = inv("y", "t", "2026-01-01T09:00:00+00:00");
    expect(sortItems([y, x], "newest").map((i) => i.id)).toEqual(["x", "y"]);
  });
});

describe("applyView", () => {
  const items = [
    inv("1", "Login crashes", "2026-01-01T00:00:00", "REPRODUCED"),
    inv("2", "Login slow", "2026-01-02T00:00:00", "NOT_REPRODUCED"),
    inv("3", "Export crashes", "2026-01-03T00:00:00", null),
  ];

  it("combines result, search and sort", () => {
    expect(applyView(items, { ...DEFAULT_STATE, q: "crashes" }).map((i) => i.id)).toEqual(["3", "1"]);
    expect(applyView(items, { ...DEFAULT_STATE, result: "running" }).map((i) => i.id)).toEqual(["3"]);
    expect(applyView(items, { ...DEFAULT_STATE, result: "REPRODUCED", q: "login" }).map((i) => i.id))
      .toEqual(["1"]);
    expect(applyView(items, { ...DEFAULT_STATE, q: "zzz" })).toEqual([]);
  });

  it("pages in steps of 25", () => {
    expect(PAGE_SIZE).toBe(25);
  });
});
