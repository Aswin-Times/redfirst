import { describe, expect, it } from "vitest";

import { isAllowedHost, parseAllowedHosts } from "@/lib/hosts";

describe("parseAllowedHosts", () => {
  it("defaults to loopback only", () => {
    expect(parseAllowedHosts(undefined)).toEqual(["localhost", "127.0.0.1"]);
    expect(parseAllowedHosts("")).toEqual(["localhost", "127.0.0.1"]);
  });

  it("accepts the same JSON list the backend uses", () => {
    expect(parseAllowedHosts('["localhost", "Redfirst.Internal"]')).toEqual([
      "localhost",
      "redfirst.internal",
    ]);
  });

  it("also accepts a comma-separated list", () => {
    expect(parseAllowedHosts("localhost, 127.0.0.1 ,example.test")).toEqual([
      "localhost",
      "127.0.0.1",
      "example.test",
    ]);
  });

  it("falls back to loopback when the value is unusable", () => {
    expect(parseAllowedHosts("[not json")).toEqual(["localhost", "127.0.0.1"]);
    expect(parseAllowedHosts("[]")).toEqual(["localhost", "127.0.0.1"]);
  });
});

describe("isAllowedHost", () => {
  const allowed = ["localhost", "127.0.0.1"];

  it.each(["localhost", "localhost:3000", "LOCALHOST:3000", "127.0.0.1", "127.0.0.1:8000"])(
    "accepts %s",
    (host) => expect(isAllowedHost(host, allowed)).toBe(true),
  );

  it.each([
    "attacker.example",
    "attacker.example:3000",
    "localhost.attacker.example",
    "127.0.0.1.attacker.example",
    "evil.com:localhost",
    "",
    null,
  ])("rejects %s", (host) => expect(isAllowedHost(host, allowed)).toBe(false));

  it("honours an extended allow-list", () => {
    expect(isAllowedHost("redfirst.internal:3000", ["redfirst.internal"])).toBe(true);
    expect(isAllowedHost("localhost", ["redfirst.internal"])).toBe(false);
  });
});
