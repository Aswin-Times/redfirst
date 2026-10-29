"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, type FormEvent, type ReactNode } from "react";

import { ErrorAlert, LoadingRows, PageHeader } from "@/components/feedback";
import { RepositoryUpload, describeRepository } from "@/components/repository-upload";
import { Button, buttonVariants } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { useResource } from "@/hooks/use-resource";
import { api } from "@/lib/api";
import type { BugReportInput } from "@/lib/types";

const selectClass =
  "h-8 w-full rounded-lg border border-input bg-transparent px-2.5 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 disabled:opacity-50 dark:bg-input/30";

type OptionalField = Exclude<keyof BugReportInput, "title" | "description">;

const OPTIONAL_FIELDS: { key: OptionalField; label: string; hint: string; mono?: boolean }[] = [
  { key: "expected_behavior", label: "Expected behavior", hint: "What should happen." },
  { key: "actual_behavior", label: "Actual behavior", hint: "What happens instead." },
  { key: "reproduction_steps", label: "Reproduction steps", hint: "Inputs and steps, if known." },
  { key: "stack_trace", label: "Error message or stack trace", hint: "Paste as-is.", mono: true },
  { key: "environment", label: "Environment", hint: "Python version, OS, package versions." },
];

/** Blank optional fields become null so the backend records them as missing. */
export function toBugReport(title: string, description: string, fields: Record<OptionalField, string>) {
  const report: BugReportInput = {
    title: title.trim(),
    description: description.trim(),
    expected_behavior: null,
    actual_behavior: null,
    reproduction_steps: null,
    stack_trace: null,
    environment: null,
  };
  for (const { key } of OPTIONAL_FIELDS) report[key] = fields[key].trim() || null;
  return report;
}

export function NewInvestigation() {
  const router = useRouter();
  const projects = useResource(() => api.projects(), []);
  // Empty selections fall back to defaults derived from the data (first project, newest repo).
  const [selectedProject, setProjectId] = useState("");
  const projectId = selectedProject || projects.data?.[0]?.id || "";
  const repos = useResource(
    () => (projectId ? api.repositories(projectId) : Promise.resolve([])),
    [projectId],
  );
  const [selectedRepository, setRepositoryId] = useState("");
  const repositoryId = repos.data?.some((r) => r.id === selectedRepository)
    ? selectedRepository
    : (repos.data?.at(-1)?.id ?? "");
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [fields, setFields] = useState<Record<OptionalField, string>>({
    expected_behavior: "",
    actual_behavior: "",
    reproduction_steps: "",
    stack_trace: "",
    environment: "",
  });
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<Error>();

  const missing = OPTIONAL_FIELDS.filter((f) => !fields[f.key].trim()).map((f) => f.label);
  const canSubmit = Boolean(projectId && repositoryId && title.trim()) && !submitting;

  async function submit(e: FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    setSubmitError(undefined);
    try {
      const inv = await api.createInvestigation(
        projectId,
        repositoryId,
        toBugReport(title, description, fields),
      );
      router.push(`/investigations/${inv.id}`);
    } catch (err) {
      setSubmitError(err as Error);
      setSubmitting(false);
    }
  }

  if (projects.error) return <ErrorAlert error={projects.error} title="Could not load projects" />;
  if (projects.loading && !projects.data) return <LoadingRows rows={6} />;
  if (projects.data?.length === 0) {
    return (
      <>
        <PageHeader title="New investigation" />
        <p className="text-sm text-muted-foreground">
          You need a project with a repository first.{" "}
          <Link href="/projects" className={buttonVariants({ variant: "link" })}>
            Create a project
          </Link>
        </p>
      </>
    );
  }

  return (
    <>
      <PageHeader
        title="New investigation"
        description="Describe the bug and choose the code. REDFIRST will try to reproduce it with a test."
      />
      <form onSubmit={submit} className="grid gap-6 lg:grid-cols-[1fr_20rem]">
        <Card>
          <CardHeader>
            <CardTitle>Bug report</CardTitle>
          </CardHeader>
          <CardContent className="grid gap-4">
            <Field id="title" label="Title" required>
              <Input
                id="title"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                maxLength={300}
                required
                placeholder="Registration crashes when the username is empty"
              />
            </Field>
            <Field id="description" label="Description">
              <Textarea
                id="description"
                rows={3}
                value={description}
                onChange={(e) => setDescription(e.target.value)}
              />
            </Field>
            {OPTIONAL_FIELDS.map((f) => (
              <Field key={f.key} id={f.key} label={f.label} hint={f.hint}>
                <Textarea
                  id={f.key}
                  rows={f.mono ? 5 : 2}
                  className={f.mono ? "font-mono text-xs" : undefined}
                  value={fields[f.key]}
                  onChange={(e) => setFields((prev) => ({ ...prev, [f.key]: e.target.value }))}
                />
              </Field>
            ))}
          </CardContent>
        </Card>

        <div className="grid content-start gap-4">
          <Card>
            <CardHeader>
              <CardTitle>Code</CardTitle>
            </CardHeader>
            <CardContent className="grid gap-4">
              <Field id="project" label="Project" required>
                <select
                  id="project"
                  className={selectClass}
                  value={projectId}
                  onChange={(e) => setProjectId(e.target.value)}
                >
                  {projects.data?.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name}
                    </option>
                  ))}
                </select>
              </Field>
              <Field id="repository" label="Repository" required>
                <select
                  id="repository"
                  className={selectClass}
                  value={repositoryId}
                  disabled={!repos.data?.length}
                  onChange={(e) => setRepositoryId(e.target.value)}
                >
                  {!repos.data?.length && <option value="">No repositories in this project</option>}
                  {repos.data?.map((r) => (
                    <option key={r.id} value={r.id}>
                      {describeRepository(r)}
                    </option>
                  ))}
                </select>
              </Field>
              {repos.error && <ErrorAlert error={repos.error} title="Could not load repositories" />}
              {projectId && (
                <RepositoryUpload
                  projectId={projectId}
                  onUploaded={async (repo) => {
                    await repos.refresh();
                    setRepositoryId(repo.id);
                  }}
                />
              )}
            </CardContent>
          </Card>

          {missing.length > 0 && (
            <p className="text-xs text-muted-foreground">
              Not provided: {missing.join(", ")}. These are recorded as missing, not guessed.
              {missing.includes("Expected behavior") &&
                " Without an expected behavior the result can be at most Inconclusive."}
            </p>
          )}
          {submitError && <ErrorAlert error={submitError} title="Could not start the investigation" />}
          <Button type="submit" disabled={!canSubmit}>
            {submitting ? "Starting…" : "Start investigation"}
          </Button>
        </div>
      </form>
    </>
  );
}

function Field({
  id,
  label,
  hint,
  required,
  children,
}: {
  id: string;
  label: string;
  hint?: string;
  required?: boolean;
  children: ReactNode;
}) {
  return (
    <div className="grid gap-1.5">
      <Label htmlFor={id}>
        {label}
        {required ? (
          <span className="text-destructive" aria-hidden>
            *
          </span>
        ) : (
          <span className="font-normal text-muted-foreground">(optional)</span>
        )}
      </Label>
      {children}
      {hint && <p className="text-xs text-muted-foreground">{hint}</p>}
    </div>
  );
}
