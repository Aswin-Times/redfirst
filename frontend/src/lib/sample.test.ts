import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it, vi } from "vitest";

import { fieldProblems } from "@/lib/report-form";
import { SAMPLE, loadSampleArchive } from "@/lib/sample";

const root = resolve(process.cwd(), "..");
// Git may check out the fixture with CRLF on Windows; the stored zip entries use LF.
const fixture = readFileSync(resolve(root, "fixtures/repos/exception_bug/accounts/registration.py"), "utf-8")
  .replaceAll("\r\n", "\n");
const archive = readFileSync(resolve(process.cwd(), "public/samples/accounts-demo.zip"));

describe("the sample archive", () => {
  it("is a zip holding exactly the planted-bug fixture's files", () => {
    expect(archive.subarray(0, 2).toString()).toBe("PK");
    const text = archive.toString("latin1");
    expect(text).toContain("accounts-demo/accounts/registration.py");
    expect(text).toContain("accounts-demo/accounts/__init__.py");
    expect(archive.includes(fixture)).toBe(true); // stored, so the file appears verbatim
  });

  it("is tiny", () => {
    expect(archive.length).toBeLessThan(5_000);
  });
});

describe("the sample bug report", () => {
  it("is a valid report with every field filled in", () => {
    expect(fieldProblems(SAMPLE.values)).toEqual({});
    for (const [key, value] of Object.entries(SAMPLE.values)) {
      expect(value.trim().length, key).toBeGreaterThan(0);
    }
  });

  it("describes the bug that is really in the archive", () => {
    const lines = fixture.split("\n");
    const buggy = lines.findIndex((l) => l.includes('username = data["username"]')) + 1;
    expect(buggy).toBeGreaterThan(0);
    expect(SAMPLE.values.stack_trace).toContain(`line ${buggy}, in register`);
    expect(SAMPLE.values.stack_trace).toContain("KeyError: 'username'");
    expect(SAMPLE.values.actual_behavior).toContain("KeyError");
    expect(SAMPLE.values.expected_behavior).toContain("ValueError");
  });
});

describe("loadSampleArchive", () => {
  it("fetches the archive and names the file", async () => {
    const fetcher = vi.fn(async () => new Response(new Uint8Array([80, 75, 3, 4]), { status: 200 }));
    const file = await loadSampleArchive(fetcher as unknown as typeof fetch);
    expect(fetcher).toHaveBeenCalledWith(SAMPLE.archiveUrl);
    expect(file.name).toBe("accounts-demo.zip");
    expect(file.size).toBe(4);
  });

  it("fails with a readable message when the archive cannot be fetched", async () => {
    const fetcher = async () => new Response("nope", { status: 404 });
    await expect(loadSampleArchive(fetcher as unknown as typeof fetch)).rejects.toThrow(
      /sample archive/i,
    );
  });
});
