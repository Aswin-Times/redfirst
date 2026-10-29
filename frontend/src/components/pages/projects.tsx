"use client";

import { FolderGit2, Package } from "lucide-react";
import { useState, type FormEvent } from "react";

import { EmptyState, ErrorAlert, LoadingRows, PageHeader } from "@/components/feedback";
import { RepositoryUpload, describeRepository } from "@/components/repository-upload";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useResource } from "@/hooks/use-resource";
import { api } from "@/lib/api";
import { formatDate } from "@/lib/outcome";
import type { Project } from "@/lib/types";

export function Projects() {
  const projects = useResource(() => api.projects(), []);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [formError, setFormError] = useState<string>();

  async function create(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setFormError(undefined);
    try {
      await api.createProject(name.trim());
      setName("");
      await projects.refresh();
    } catch (err) {
      setFormError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <PageHeader
        title="Projects"
        description="Projects group repository archives and the investigations run against them."
      />
      <form onSubmit={create} className="mb-6 flex flex-wrap items-end gap-2">
        <div className="grid gap-1.5">
          <Label htmlFor="project-name">New project</Label>
          <Input
            id="project-name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g. billing-service"
            maxLength={200}
            className="w-64"
            required
          />
        </div>
        <Button type="submit" disabled={busy || !name.trim()}>
          {busy ? "Creating…" : "Create project"}
        </Button>
        {formError && (
          <p role="alert" className="w-full text-sm text-destructive">
            {formError}
          </p>
        )}
      </form>

      {projects.error && <ErrorAlert error={projects.error} title="Could not load projects" />}
      {projects.loading && !projects.data && <LoadingRows />}
      {projects.data?.length === 0 && (
        <EmptyState icon={FolderGit2} title="No projects yet">
          Create your first project above.
        </EmptyState>
      )}
      <div className="grid gap-4">
        {projects.data?.map((p) => <ProjectCard key={p.id} project={p} />)}
      </div>
    </>
  );
}

function ProjectCard({ project }: { project: Project }) {
  const repos = useResource(() => api.repositories(project.id), [project.id]);
  return (
    <Card>
      <CardHeader className="flex flex-row flex-wrap items-center justify-between gap-2">
        <div>
          <CardTitle>{project.name}</CardTitle>
          <p className="text-xs text-muted-foreground">Created {formatDate(project.created_at)}</p>
        </div>
        <RepositoryUpload projectId={project.id} onUploaded={() => repos.refresh()} />
      </CardHeader>
      <CardContent>
        {repos.error && <ErrorAlert error={repos.error} title="Could not load repositories" />}
        {repos.loading && !repos.data && <LoadingRows rows={1} />}
        {repos.data?.length === 0 && (
          <p className="text-sm text-muted-foreground">
            No repositories yet. Upload a .zip or .tar.gz of a Python project.
          </p>
        )}
        <ul className="divide-y">
          {repos.data?.map((r) => (
            <li key={r.id} className="flex items-center gap-2 py-2 text-sm">
              <Package className="size-4 shrink-0 text-muted-foreground" aria-hidden />
              <span className="font-mono text-xs">{describeRepository(r)}</span>
              <span className="ml-auto text-xs text-muted-foreground">{formatDate(r.created_at)}</span>
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}
