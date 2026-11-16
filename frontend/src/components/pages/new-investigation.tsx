"use client";

import { FlaskConical, FolderPlus } from "lucide-react";
import { useRouter } from "next/navigation";
import {
  useEffect, useRef, useState, type FormEvent, type KeyboardEvent, type ReactNode,
} from "react";

import { ArchiveDropzone } from "@/components/archive-dropzone";
import { Breadcrumbs } from "@/components/breadcrumbs";
import { ErrorAlert, LoadingRows, PageHeader } from "@/components/feedback";
import { ReportStrength } from "@/components/report-strength";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { useResource } from "@/hooks/use-resource";
import { api } from "@/lib/api";
import { repoLabel } from "@/lib/archive";
import {
  DRAFT_KEY, EMPTY_VALUES, LIMITS, counterState, fieldProblems, parseDraft, serializeDraft,
  submitBlocker, toBugReport, type FieldKey, type FormValues,
} from "@/lib/report-form";
import { SAMPLE, loadSampleArchive } from "@/lib/sample";
import type { Project } from "@/lib/types";
import { cn } from "@/lib/utils";

const DRAFT_SAVE_DELAY_MS = 400;
const DETAIL_KEYS: FieldKey[] = ["description", "reproduction_steps", "stack_trace", "environment"];

const selectClass =
  "h-8 w-full rounded-lg border border-input bg-transparent px-2.5 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 disabled:opacity-50 dark:bg-input/30";

const hasContent = (values: FormValues) => Object.values(values).some((v) => v.trim());

// Every storage access is guarded: it can throw in private windows or with blocked site data.
function readDraft(): FormValues | null {
  try {
    return parseDraft(localStorage.getItem(DRAFT_KEY));
  } catch {
    return null;
  }
}

function writeDraft(values: FormValues): void {
  try {
    if (hasContent(values)) localStorage.setItem(DRAFT_KEY, serializeDraft(values));
    else localStorage.removeItem(DRAFT_KEY);
  } catch {
    // Storage is blocked: the form still works, it just cannot be restored later.
  }
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

  const [draft] = useState(() => (typeof window === "undefined" ? null : readDraft()));
  const [values, setValues] = useState<FormValues>(draft ?? EMPTY_VALUES);
  const [restored, setRestored] = useState(draft !== null);
  const [detailOpen, setDetailOpen] = useState(
    draft !== null && DETAIL_KEYS.some((k) => draft[k].trim() !== ""),
  );
  const [titleTouched, setTitleTouched] = useState(false);
  const [showCreate, setShowCreate] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<Error>();
  const [sampleBusy, setSampleBusy] = useState(false);
  const [sampleError, setSampleError] = useState<Error>();
  const skipSave = useRef(false);
  const errorRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const timer = setTimeout(() => {
      if (!skipSave.current) writeDraft(values);
    }, DRAFT_SAVE_DELAY_MS);
    return () => clearTimeout(timer);
  }, [values]);

  useEffect(() => {
    if (submitError) errorRef.current?.focus();
  }, [submitError]);

  const problems = fieldProblems(values);
  const blocker = submitBlocker({ projectId, repositoryId, values, busy: submitting });

  const set = (key: FieldKey, value: string) => setValues((prev) => ({ ...prev, [key]: value }));

  function discardDraft() {
    setValues(EMPTY_VALUES);
    setRestored(false);
    setDetailOpen(false);
    writeDraft(EMPTY_VALUES);
  }

  async function submit() {
    if (blocker) return;
    setSubmitting(true);
    setSubmitError(undefined);
    try {
      const inv = await api.createInvestigation(projectId, repositoryId, toBugReport(values));
      skipSave.current = true;
      writeDraft(EMPTY_VALUES);
      router.push(`/investigations/${inv.id}`);
    } catch (err) {
      setSubmitError(err as Error);
      setSubmitting(false);
    }
  }

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    void submit();
  }

  function onKeyDown(e: KeyboardEvent) {
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      void submit();
    }
  }

  async function projectCreated(project: Project) {
    await projects.refresh();
    setProjectId(project.id);
    setShowCreate(false);
  }

  /** Create (or reuse) the sample project, give it the sample repository, fill in the report. */
  async function trySample() {
    setSampleBusy(true);
    setSampleError(undefined);
    try {
      const project =
        projects.data?.find((p) => p.name === SAMPLE.projectName) ??
        (await api.createProject(SAMPLE.projectName));
      const existing = await api.repositories(project.id);
      const repo =
        existing.at(-1) ?? (await api.uploadRepository(project.id, await loadSampleArchive()));
      await projects.refresh();
      setProjectId(project.id);
      setRepositoryId(repo.id);
      setValues(SAMPLE.values);
      setDetailOpen(true);
      setRestored(false);
    } catch (e) {
      setSampleError(e as Error);
    } finally {
      setSampleBusy(false);
    }
  }

  if (projects.error) return <ErrorAlert error={projects.error} title="Could not load projects" />;
  if (projects.loading && !projects.data) return <LoadingRows rows={6} />;

  const noProjects = projects.data?.length === 0;
  const textProps = (key: FieldKey) => ({
    id: key,
    value: values[key],
    onChange: (e: { target: { value: string } }) => set(key, e.target.value),
    "aria-invalid": problems[key] && key !== "title" ? true : undefined,
    "aria-describedby": `${key}-help`,
  });

  return (
    <>
      <Breadcrumbs
        items={[{ label: "Investigations", href: "/investigations" }, { label: "New investigation" }]}
      />
      <PageHeader
        title="New investigation"
        description="Describe the bug and choose the code. REDFIRST will try to reproduce it with a test."
        actions={
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={trySample}
            disabled={sampleBusy || hasContent(values)}
            title={hasContent(values) ? "Clear the form to load the sample" : undefined}
          >
            <FlaskConical data-icon="inline-start" aria-hidden />
            {sampleBusy ? "Setting up the sample…" : "Try a sample bug"}
          </Button>
        }
      />
      {sampleError && (
        <div className="mb-4">
          <ErrorAlert error={sampleError} title="Could not set up the sample" />
        </div>
      )}
      {restored && (
        <p className="mb-4 flex items-center gap-2 rounded-lg border bg-muted/40 px-3 py-2 text-sm">
          Draft restored from your last visit.
          <Button type="button" variant="link" size="sm" className="h-auto p-0" onClick={discardDraft}>
            Discard
          </Button>
        </p>
      )}
      <form onSubmit={onSubmit} onKeyDown={onKeyDown} className="grid gap-6 lg:grid-cols-[1fr_20rem]">
        <div className="grid content-start gap-6">
          <Section title="Code">
            {noProjects || showCreate ? (
              <ProjectCreate
                first={noProjects}
                onCreated={projectCreated}
                onCancel={noProjects ? undefined : () => setShowCreate(false)}
              />
            ) : (
              <div className="grid gap-4 sm:grid-cols-2">
                <div className="grid gap-1.5">
                  <Label htmlFor="project">Project</Label>
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
                  <Button
                    type="button"
                    variant="link"
                    size="sm"
                    className="h-auto justify-start p-0 text-xs"
                    onClick={() => setShowCreate(true)}
                  >
                    <FolderPlus data-icon="inline-start" aria-hidden /> New project
                  </Button>
                </div>
                <div className="grid content-start gap-1.5">
                  <Label htmlFor="repository">Repository</Label>
                  <select
                    id="repository"
                    className={selectClass}
                    value={repositoryId}
                    disabled={!repos.data?.length}
                    onChange={(e) => setRepositoryId(e.target.value)}
                  >
                    {!repos.data?.length && <option value="">No repositories yet</option>}
                    {repos.data?.map((r) => (
                      <option key={r.id} value={r.id}>
                        {repoLabel(r)}
                      </option>
                    ))}
                  </select>
                </div>
              </div>
            )}
            {repos.error && <ErrorAlert error={repos.error} title="Could not load repositories" />}
            <ArchiveDropzone
              projectId={projectId}
              disabled={!projectId}
              onUploaded={async (repo) => {
                await repos.refresh();
                setRepositoryId(repo.id);
              }}
            />
          </Section>

          <Section title="The bug">
            <Field
              id="title" label="Title" required example="e.g. Registration crashes when the username is empty"
              error={titleTouched ? problems.title : undefined} counter={values.title.length} limit={LIMITS.title}
            >
              <Input
                {...textProps("title")}
                aria-invalid={titleTouched && problems.title ? true : undefined}
                onBlur={() => setTitleTouched(true)}
                autoComplete="off"
              />
            </Field>
            <Field
              id="expected_behavior" label="Expected behavior" tag="recommended"
              example="e.g. register() raises ValueError when the username is missing."
              error={problems.expected_behavior} counter={values.expected_behavior.length}
              limit={LIMITS.expected_behavior}
            >
              <Textarea rows={3} {...textProps("expected_behavior")} />
            </Field>
            <Field
              id="actual_behavior" label="Actual behavior" tag="recommended"
              example="e.g. It raises KeyError: 'username' instead."
              error={problems.actual_behavior} counter={values.actual_behavior.length}
              limit={LIMITS.actual_behavior}
            >
              <Textarea rows={3} {...textProps("actual_behavior")} />
            </Field>
          </Section>

          <details
            open={detailOpen}
            onToggle={(e) => setDetailOpen((e.currentTarget as HTMLDetailsElement).open)}
            className="rounded-xl border bg-card"
          >
            <summary className="flex cursor-pointer items-baseline gap-2 p-4 select-none sm:px-5">
              <h2 className="text-sm font-semibold">More detail</h2>
              <span className="text-xs text-muted-foreground">optional, but it helps</span>
            </summary>
            <div className="grid gap-4 px-4 pb-4 sm:px-5 sm:pb-5">
              <Field
                id="description" label="Description" tag="optional"
                example="Anything else that helps someone understand the bug."
                error={problems.description} counter={values.description.length} limit={LIMITS.description}
              >
                <Textarea rows={3} {...textProps("description")} />
              </Field>
              <Field
                id="reproduction_steps" label="Reproduction steps" tag="optional"
                example="Inputs and steps, if you know them."
                error={problems.reproduction_steps} counter={values.reproduction_steps.length}
                limit={LIMITS.reproduction_steps}
              >
                <Textarea rows={3} {...textProps("reproduction_steps")} />
              </Field>
              <Field
                id="stack_trace" label="Stack trace" tag="optional" example="Paste it as-is."
                error={problems.stack_trace} counter={values.stack_trace.length} limit={LIMITS.stack_trace}
              >
                <Textarea rows={5} className="font-mono text-xs" {...textProps("stack_trace")} />
              </Field>
              <Field
                id="environment" label="Environment" tag="optional"
                example="Python version, OS, package versions."
                error={problems.environment} counter={values.environment.length} limit={LIMITS.environment}
              >
                <Textarea rows={2} {...textProps("environment")} />
              </Field>
            </div>
          </details>
        </div>

        <div className="grid content-start gap-4 lg:sticky lg:top-20">
          <ReportStrength values={values} />
          {submitError && (
            <div ref={errorRef} tabIndex={-1} className="outline-none">
              <ErrorAlert error={submitError} title="Could not start the investigation" />
            </div>
          )}
          <div className="grid gap-1.5">
            <Button type="submit" disabled={Boolean(blocker)} aria-describedby="submit-hint">
              {submitting ? "Starting…" : "Start investigation"}
            </Button>
            <p id="submit-hint" aria-live="polite" className="min-h-4 text-xs text-muted-foreground">
              {blocker}
            </p>
            <p className="text-xs text-muted-foreground">Ctrl or ⌘ + Enter also starts it.</p>
          </div>
        </div>
      </form>
    </>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="grid gap-4 rounded-xl border bg-card p-4 sm:p-5">
      <h2 className="text-sm font-semibold">{title}</h2>
      {children}
    </section>
  );
}

function Field({
  id, label, tag, required, example, error, counter, limit, children,
}: {
  id: string;
  label: string;
  tag?: string;
  required?: boolean;
  example: string;
  error?: string;
  counter: number;
  limit: number;
  children: ReactNode;
}) {
  const state = counterState(counter, limit);
  return (
    <div className="grid gap-1.5">
      <Label htmlFor={id}>
        {label}
        {required && (
          <span className="text-destructive" aria-hidden>
            *
          </span>
        )}
        {tag && <span className="font-normal text-muted-foreground">({tag})</span>}
      </Label>
      {children}
      <div id={`${id}-help`} className="flex items-start justify-between gap-3 text-xs">
        <p className={cn(error ? "text-destructive" : "text-muted-foreground")}>{error ?? example}</p>
        {state !== "hidden" && (
          <span className={cn("shrink-0 tabular-nums", state === "over" ? "text-destructive" : "text-muted-foreground")}>
            {counter.toLocaleString("en-US")} / {limit.toLocaleString("en-US")}
          </span>
        )}
      </div>
    </div>
  );
}

/** Create a project without leaving the page. Not a <form>: it sits inside the report form. */
function ProjectCreate({
  first,
  onCreated,
  onCancel,
}: {
  first: boolean;
  onCreated: (project: Project) => Promise<void>;
  onCancel?: () => void;
}) {
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<Error>();

  async function create() {
    if (!name.trim() || busy) return;
    setBusy(true);
    setError(undefined);
    try {
      await onCreated(await api.createProject(name.trim()));
    } catch (e) {
      setError(e as Error);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="grid gap-2">
      {first && (
        <p className="text-sm text-muted-foreground">
          A project groups the repositories and bugs you investigate together. Name your first one:
        </p>
      )}
      <div className="grid gap-1.5">
        <Label htmlFor="project-name">Project name</Label>
        <div className="flex gap-2">
          <Input
            id="project-name"
            value={name}
            maxLength={200}
            onChange={(e) => setName(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.ctrlKey && !e.metaKey) {
                e.preventDefault();
                void create();
              }
            }}
            placeholder="e.g. Billing service"
          />
          <Button type="button" onClick={create} disabled={!name.trim() || busy}>
            {busy ? "Creating…" : "Create project"}
          </Button>
          {onCancel && (
            <Button type="button" variant="ghost" onClick={onCancel}>
              Cancel
            </Button>
          )}
        </div>
      </div>
      {error && <ErrorAlert error={error} title="Could not create the project" />}
    </div>
  );
}
