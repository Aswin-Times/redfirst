"use client";

import { Upload } from "lucide-react";
import { useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import type { Repository } from "@/lib/types";

/** Upload a .zip / .tar.gz. The backend validates it with the same safe extractor the worker uses. */
export function RepositoryUpload({
  projectId,
  onUploaded,
}: {
  projectId: string;
  onUploaded: (repo: Repository) => void;
}) {
  const input = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();

  async function upload(file: File) {
    setBusy(true);
    setError(undefined);
    try {
      onUploaded(await api.uploadRepository(projectId, file));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
      if (input.current) input.current.value = "";
    }
  }

  return (
    <div className="space-y-1">
      <input
        ref={input}
        type="file"
        accept=".zip,.tar,.tar.gz,.tgz"
        className="sr-only"
        aria-label="Repository archive"
        onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])}
      />
      <Button variant="outline" size="sm" disabled={busy} onClick={() => input.current?.click()}>
        <Upload data-icon="inline-start" aria-hidden />
        {busy ? "Uploading and checking…" : "Upload archive"}
      </Button>
      {error && (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}
    </div>
  );
}

export function describeRepository(repo: Repository): string {
  const l = repo.layout;
  const parts = [`${repo.sha256?.slice(0, 10) ?? repo.id.slice(0, 8)}`];
  if (l) {
    parts.push(`${l.layout} layout`, `${l.python_file_count} Python files`);
    if (l.packages.length) parts.push(`packages: ${l.packages.join(", ")}`);
  }
  return parts.join(" · ");
}
