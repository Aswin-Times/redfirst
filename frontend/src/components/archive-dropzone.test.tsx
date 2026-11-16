import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ArchiveDropzone } from "@/components/archive-dropzone";
import { api } from "@/lib/api";
import { UPLOAD_MAX_BYTES } from "@/lib/report-form";
import type { Repository } from "@/lib/types";

vi.mock("@/lib/api", () => ({ api: { uploadRepository: vi.fn() } }));

const upload = vi.mocked(api.uploadRepository);
const repo = {
  id: "r1", project_id: "p1", source_type: "archive", sha256: "abcdef0123456789",
  layout: { layout: "flat", python_file_count: 2, packages: ["accounts"], source_roots: ["."],
    manifests: [], requirements_files: [], test_dirs: [], conftest_files: [], pytest_config: null },
  created_at: "2026-01-01T00:00:00",
} as Repository;

const file = (name: string, size = 1000) => {
  const f = new File(["x"], name);
  Object.defineProperty(f, "size", { value: size });
  return f;
};
const input = () => screen.getByLabelText("Repository archive") as HTMLInputElement;
const choose = (f: File) => fireEvent.change(input(), { target: { files: [f] } });

beforeEach(() => upload.mockReset());
afterEach(cleanup);

describe("ArchiveDropzone", () => {
  it("uploads a valid archive for the project and reports the repository", async () => {
    upload.mockResolvedValue(repo);
    const onUploaded = vi.fn();
    render(<ArchiveDropzone projectId="p1" onUploaded={onUploaded} />);
    const f = file("code.zip");
    choose(f);
    await waitFor(() => expect(onUploaded).toHaveBeenCalledWith(repo));
    expect(upload).toHaveBeenCalledWith("p1", f);
    expect(screen.getByText(/added/i).textContent).toContain("2 Python files");
  });

  it("accepts a file dropped on the zone", async () => {
    upload.mockResolvedValue(repo);
    const onUploaded = vi.fn();
    render(<ArchiveDropzone projectId="p1" onUploaded={onUploaded} />);
    const f = file("dropped.tar.gz");
    fireEvent.drop(screen.getByTestId("dropzone"), { dataTransfer: { files: [f] } });
    await waitFor(() => expect(onUploaded).toHaveBeenCalled());
    expect(upload).toHaveBeenCalledWith("p1", f);
  });

  it("rejects an unsupported type before sending anything", () => {
    render(<ArchiveDropzone projectId="p1" onUploaded={vi.fn()} />);
    choose(file("code.rar"));
    expect(screen.getByRole("alert").textContent).toMatch(/not a supported archive/);
    expect(upload).not.toHaveBeenCalled();
  });

  it("rejects an oversize file before sending anything", () => {
    render(<ArchiveDropzone projectId="p1" onUploaded={vi.fn()} />);
    choose(file("big.zip", UPLOAD_MAX_BYTES + 1));
    expect(screen.getByRole("alert").textContent).toMatch(/over the 50 MB limit/);
    expect(upload).not.toHaveBeenCalled();
  });

  it("asks for one archive at a time", () => {
    render(<ArchiveDropzone projectId="p1" onUploaded={vi.fn()} />);
    fireEvent.drop(screen.getByTestId("dropzone"), {
      dataTransfer: { files: [file("a.zip"), file("b.zip")] },
    });
    expect(screen.getByRole("alert").textContent).toMatch(/one archive at a time/i);
    expect(upload).not.toHaveBeenCalled();
  });

  it("shows the server's reason when it refuses the archive", async () => {
    upload.mockImplementation(async () => {
      throw new Error("not a supported archive (zip, tar, tar.gz)");
    });
    const onUploaded = vi.fn();
    render(<ArchiveDropzone projectId="p1" onUploaded={onUploaded} />);
    choose(file("code.zip"));
    await waitFor(() => expect(screen.getByRole("alert").textContent).toMatch(/not a supported archive/));
    expect(onUploaded).not.toHaveBeenCalled();
  });

  it("shows progress while uploading and ignores a second drop meanwhile", async () => {
    let finish: (r: Repository) => void = () => {};
    upload.mockReturnValue(new Promise<Repository>((r) => (finish = r)));
    render(<ArchiveDropzone projectId="p1" onUploaded={vi.fn()} />);
    choose(file("code.zip"));
    await waitFor(() => expect(screen.getByText(/uploading and checking code.zip/i)).toBeTruthy());
    fireEvent.drop(screen.getByTestId("dropzone"), { dataTransfer: { files: [file("two.zip")] } });
    expect(upload).toHaveBeenCalledTimes(1);
    finish(repo);
    await waitFor(() => expect(screen.queryByText(/uploading and checking/i)).toBeNull());
  });

  it("highlights while a file is dragged over it", () => {
    render(<ArchiveDropzone projectId="p1" onUploaded={vi.fn()} />);
    const zone = screen.getByTestId("dropzone");
    fireEvent.dragEnter(zone);
    expect(zone.getAttribute("data-dragging")).toBe("true");
    fireEvent.dragLeave(zone);
    expect(zone.getAttribute("data-dragging")).toBe("false");
  });

  it("does nothing when disabled", () => {
    render(<ArchiveDropzone projectId="p1" onUploaded={vi.fn()} disabled />);
    fireEvent.drop(screen.getByTestId("dropzone"), { dataTransfer: { files: [file("a.zip")] } });
    expect(upload).not.toHaveBeenCalled();
    expect((screen.getByRole("button", { name: /browse/i }) as HTMLButtonElement).disabled).toBe(true);
  });
});
