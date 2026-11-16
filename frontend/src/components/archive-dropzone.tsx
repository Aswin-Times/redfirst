"use client";

import { FileArchive, Loader, Upload } from "lucide-react";
import { useRef, useState, type DragEvent } from "react";

import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import { checkArchive } from "@/lib/archive";
import type { Repository } from "@/lib/types";
import { cn } from "@/lib/utils";

/** What the backend found in the archive, e.g. "2 Python files · flat layout". */
function summary(repo: Repository): string {
  const l = repo.layout;
  if (!l) return "not analysed yet";
  return `${l.python_file_count} Python file${l.python_file_count === 1 ? "" : "s"} · ${l.layout} layout`;
}

/** Drag-and-drop (or browse) upload of a repository archive, checked in the browser first. */
export function ArchiveDropzone({
  projectId,
  onUploaded,
  disabled = false,
}: {
  projectId: string;
  onUploaded: (repo: Repository) => void;
  disabled?: boolean;
}) {
  const input = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [uploading, setUploading] = useState<string>();
  const [error, setError] = useState<string>();
  const [added, setAdded] = useState<{ name: string; repo: Repository }>();
  const blocked = disabled || uploading !== undefined;

  async function handle(files: FileList | File[] | null | undefined) {
    if (blocked || !files || files.length === 0) return;
    if (files.length > 1) {
      setError("Drop one archive at a time.");
      return;
    }
    const file = files[0];
    const problem = checkArchive(file);
    setAdded(undefined);
    if (problem) {
      setError(problem);
      return;
    }
    setError(undefined);
    setUploading(file.name);
    try {
      const repo = await api.uploadRepository(projectId, file);
      setAdded({ name: file.name, repo });
      onUploaded(repo);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setUploading(undefined);
      if (input.current) input.current.value = "";
    }
  }

  function over(e: DragEvent) {
    e.preventDefault();
    if (!blocked) setDragging(true);
  }

  return (
    <div className="space-y-2">
      <div
        data-testid="dropzone"
        data-dragging={dragging}
        onDragEnter={over}
        onDragOver={over}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          void handle(e.dataTransfer?.files);
        }}
        className={cn(
          "flex flex-col items-center gap-1.5 rounded-lg border border-dashed px-4 py-5 text-center transition-colors",
          dragging && "border-foreground bg-muted",
          blocked && "opacity-60",
        )}
      >
        {uploading ? (
          <>
            <Loader className="size-5 animate-spin text-muted-foreground" aria-hidden />
            <p className="text-sm">Uploading and checking {uploading}…</p>
          </>
        ) : (
          <>
            <Upload className="size-5 text-muted-foreground" aria-hidden />
            <p className="text-sm">
              Drop a repository archive here, or{" "}
              <Button
                type="button"
                variant="link"
                size="sm"
                className="h-auto p-0"
                disabled={blocked}
                onClick={() => input.current?.click()}
              >
                browse
              </Button>
            </p>
            <p className="text-xs text-muted-foreground">.zip, .tar or .tar.gz, up to 50 MB</p>
          </>
        )}
        <input
          ref={input}
          type="file"
          accept=".zip,.tar,.tar.gz,.tgz"
          className="sr-only"
          tabIndex={-1}
          aria-label="Repository archive"
          disabled={blocked}
          onChange={(e) => void handle(e.target.files)}
        />
      </div>
      {added && !error && (
        <p className="flex items-start gap-1.5 text-xs text-muted-foreground">
          <FileArchive className="mt-0.5 size-3.5 shrink-0" aria-hidden />
          <span>Added {added.name} · {summary(added.repo)}</span>
        </p>
      )}
      {error && (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}
    </div>
  );
}
