import { describe, expect, it } from "vitest";

import { checkArchive, formatBytes, repoLabel } from "@/lib/archive";
import { UPLOAD_MAX_BYTES } from "@/lib/report-form";

describe("formatBytes", () => {
  it.each([
    [0, "0 B"], [793, "793 B"], [1024, "1 KB"], [1536, "1.5 KB"],
    [1024 * 1024, "1 MB"], [UPLOAD_MAX_BYTES, "50 MB"], [51 * 1024 * 1024 + 300 * 1024, "51.3 MB"],
  ])("%d -> %s", (n, text) => expect(formatBytes(n)).toBe(text));
});

describe("checkArchive", () => {
  it.each(["repo.zip", "repo.tar", "repo.tar.gz", "repo.tgz", "REPO.ZIP", "My Repo.Tar.GZ"])(
    "accepts %s", (name) => expect(checkArchive({ name, size: 1000 })).toBeNull());

  it.each(["repo.rar", "repo.7z", "repo.gz", "repo", "zip", "repo.zip.exe", "repo.py"])(
    "rejects %s as an unsupported type", (name) => {
      expect(checkArchive({ name, size: 1000 })).toBe(
        `"${name}" is not a supported archive. Use .zip, .tar, .tar.gz or .tgz.`);
    });

  it("rejects an empty file", () => {
    expect(checkArchive({ name: "a.zip", size: 0 })).toBe('"a.zip" is empty.');
  });

  it("accepts exactly the limit and rejects one byte over, saying by how much", () => {
    expect(checkArchive({ name: "a.zip", size: UPLOAD_MAX_BYTES })).toBeNull();
    expect(checkArchive({ name: "big.zip", size: 51 * 1024 * 1024 })).toBe(
      '"big.zip" is 51 MB, over the 50 MB limit.');
  });

  it("checks the type before the size", () => {
    expect(checkArchive({ name: "x.rar", size: 0 })).toMatch(/not a supported archive/);
  });
});

describe("repoLabel", () => {
  const now = new Date(2026, 10, 16, 15, 0).getTime();
  const created = (h: number) => new Date(2026, 10, 16, h, 0).toISOString().replace("Z", "");
  const layout = { layout: "src", python_file_count: 12, packages: [], source_roots: [], manifests: [],
    requirements_files: [], test_dirs: [], conftest_files: [], pytest_config: null };

  it("says when it was uploaded and what is in it, without a hash", () => {
    const label = repoLabel({ created_at: created(12), layout } as never, now);
    expect(label).toBe("Uploaded 3h ago · 12 Python files · src layout");
    expect(label).not.toMatch(/[0-9a-f]{10}/);
  });

  it("uses the singular for one file", () => {
    expect(repoLabel({ created_at: created(15), layout: { ...layout, python_file_count: 1 } } as never, now))
      .toBe("Uploaded just now · 1 Python file · src layout");
  });

  it("copes with a repository that has not been analysed", () => {
    expect(repoLabel({ created_at: created(14), layout: null } as never, now))
      .toBe("Uploaded 1h ago · not analysed yet");
  });
});
