"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { CircleAlert, Clock, Download, FileCode2, Info, Square } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";

import { CodeView, LogView } from "@/components/code-view";
import { ErrorAlert, LoadingRows, PageHeader } from "@/components/feedback";
import { StageProgress } from "@/components/stage-progress";
import { StatusBadge } from "@/components/status-badge";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useInvestigationEvents } from "@/hooks/use-investigation-events";
import { useResource } from "@/hooks/use-resource";
import { api, exportUrls } from "@/lib/api";
import { OUTCOME_INFO, STATE_LABEL, formatDate, formatDuration, humanize } from "@/lib/outcome";
import { isTerminal } from "@/lib/stages";
import type { AttemptSummary, EvidenceReport } from "@/lib/types";

const WORKER_HINT_AFTER_MS = 8_000;

export function InvestigationWorkspace() {
  const { id } = useParams<{ id: string }>();
  const report = useResource(() => api.investigation(id), [id]);
  const data = report.data;
  const live = Boolean(data) && !isTerminal(data!.state);
  const stream = useInvestigationEvents(id, live, () => void report.refresh());

  if (report.error && !data) {
    return (
      <>
        <PageHeader title="Investigation" />
        <ErrorAlert error={report.error} title="Could not load this investigation" />
        <Link href="/investigations" className={buttonVariants({ variant: "link" })}>
          Back to investigations
        </Link>
      </>
    );
  }
  if (!data) return <LoadingRows rows={6} />;

  return (
    <>
      <PageHeader
        title={data.bug_report.title}
        description={
          <span className="flex flex-wrap items-center gap-x-3 gap-y-1">
            <span className="font-mono text-xs">{data.investigation_id}</span>
            <span>Created {formatDate(data.created_at)}</span>
            {live && (
              <span className="text-xs">
                {stream === "open" ? "Live updates on" : "Connecting to live updates…"}
              </span>
            )}
          </span>
        }
        actions={<Actions data={data} onChanged={() => report.refresh()} />}
      />
      <div className="space-y-6">
        <StageProgress timeline={data.timeline} state={data.state} />
        <WaitingForWorker data={data} />
        <OutcomePanel data={data} />
        <Tabs defaultValue="evidence">
          <TabsList className="h-auto max-w-full flex-wrap justify-start">
            <TabsTrigger value="evidence">Evidence</TabsTrigger>
            <TabsTrigger value="test">Test</TabsTrigger>
            <TabsTrigger value="attempts">Attempts &amp; logs ({data.attempts.length})</TabsTrigger>
            <TabsTrigger value="report">Bug report</TabsTrigger>
            <TabsTrigger value="timeline">Timeline</TabsTrigger>
          </TabsList>
          <TabsContent value="evidence" className="pt-2">
            <EvidenceTab data={data} />
          </TabsContent>
          <TabsContent value="test" className="pt-2">
            <TestTab data={data} />
          </TabsContent>
          <TabsContent value="attempts" className="pt-2">
            <AttemptsTab attempts={data.attempts} />
          </TabsContent>
          <TabsContent value="report" className="pt-2">
            <ReportTab data={data} />
          </TabsContent>
          <TabsContent value="timeline" className="pt-2">
            <TimelineTab data={data} />
          </TabsContent>
        </Tabs>
      </div>
    </>
  );
}

function Actions({ data, onChanged }: { data: EvidenceReport; onChanged: () => void }) {
  const [cancelling, setCancelling] = useState(false);
  const [error, setError] = useState<string>();
  const urls = exportUrls(data.investigation_id);

  async function cancel() {
    setCancelling(true);
    setError(undefined);
    try {
      await api.cancel(data.investigation_id);
      onChanged();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setCancelling(false);
    }
  }

  return (
    <div className="flex flex-col items-end gap-1">
      <div className="flex flex-wrap items-center gap-2">
        <StatusBadge state={data.state} outcome={data.outcome} />
        {!isTerminal(data.state) && (
          <Button variant="outline" size="sm" onClick={cancel} disabled={cancelling}>
            <Square data-icon="inline-start" aria-hidden />
            {cancelling ? "Cancelling…" : "Cancel"}
          </Button>
        )}
        {data.final_test && (
          <a href={urls.test} className={buttonVariants({ variant: "outline", size: "sm" })}>
            <FileCode2 data-icon="inline-start" aria-hidden /> Test
          </a>
        )}
        <a href={urls.markdown} className={buttonVariants({ variant: "outline", size: "sm" })}>
          <Download data-icon="inline-start" aria-hidden /> Report (.md)
        </a>
        <a href={urls.json} className={buttonVariants({ variant: "ghost", size: "sm" })}>
          JSON
        </a>
      </div>
      {error && (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}
    </div>
  );
}

/** Investigations stay CREATED until a worker claims them; say so instead of looking stuck. */
function WaitingForWorker({ data }: { data: EvidenceReport }) {
  const [waitedLong, setWaitedLong] = useState(false);
  const queued = data.state === "CREATED";
  useEffect(() => {
    if (!queued) return;
    const age = Date.now() - new Date(data.created_at).getTime();
    const t = setTimeout(() => setWaitedLong(true), Math.max(0, WORKER_HINT_AFTER_MS - age));
    return () => clearTimeout(t);
  }, [queued, data.created_at]);
  if (!queued || !waitedLong) return null;
  return (
    <Alert>
      <Clock aria-hidden />
      <AlertTitle>Waiting for a worker</AlertTitle>
      <AlertDescription>
        No worker has picked this investigation up yet. Start one with{" "}
        <code className="font-mono text-xs">uv run python -m redfirst.worker</code> in{" "}
        <code className="font-mono text-xs">backend/</code>.
      </AlertDescription>
    </Alert>
  );
}

function OutcomePanel({ data }: { data: EvidenceReport }) {
  if (data.outcome && data.outcome !== "EXECUTION_ERROR") {
    return (
      <Alert>
        <Info aria-hidden />
        <AlertTitle>
          {OUTCOME_INFO[data.outcome].label}
          {data.outcome_reason && ` · ${humanize(data.outcome_reason)}`}
        </AlertTitle>
        <AlertDescription>{OUTCOME_INFO[data.outcome].description}</AlertDescription>
      </Alert>
    );
  }
  if (data.state === "FAILED") {
    return (
      <Alert variant="destructive">
        <CircleAlert aria-hidden />
        <AlertTitle>{OUTCOME_INFO.EXECUTION_ERROR.label}</AlertTitle>
        <AlertDescription>
          {data.error?.type && <span className="font-mono">{data.error.type}: </span>}
          {data.error?.detail ?? OUTCOME_INFO.EXECUTION_ERROR.description}
          {data.error?.retryable && " This failure may be temporary; try again later."}
        </AlertDescription>
      </Alert>
    );
  }
  if (data.state === "CANCELLED") {
    return (
      <Alert>
        <Square aria-hidden />
        <AlertTitle>Cancelled</AlertTitle>
        <AlertDescription>This investigation was cancelled before it finished.</AlertDescription>
      </Alert>
    );
  }
  return null;
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="space-y-2">
      <h3 className="text-sm font-medium">{title}</h3>
      {children}
    </section>
  );
}

function BulletList({ items, empty, mono }: { items: string[]; empty: string; mono?: boolean }) {
  if (!items.length) return <p className="text-sm text-muted-foreground">{empty}</p>;
  return (
    <ul className={`list-disc space-y-1 pl-5 text-sm ${mono ? "font-mono text-xs" : ""}`}>
      {items.map((x, i) => (
        <li key={i} className={mono ? "break-all" : "break-words"}>
          {x}
        </li>
      ))}
    </ul>
  );
}

function EvidenceTab({ data }: { data: EvidenceReport }) {
  return (
    <div className="grid gap-6 lg:grid-cols-2 [&>*]:min-w-0">
      <div className="space-y-6">
        <Section title="Verification evidence">
          <BulletList
            items={data.evidence}
            mono
            empty={
              isTerminal(data.state)
                ? "No test was verified, so there is no execution evidence."
                : "Evidence appears once a test has run and been verified."
            }
          />
        </Section>
        <Section title="Limitations">
          <BulletList items={data.limitations} empty="None recorded." />
        </Section>
        <Section title="Next steps">
          <BulletList
            items={data.next_steps}
            empty={isTerminal(data.state) ? "None." : "Available when the investigation finishes."}
          />
        </Section>
      </div>
      <Section title="Relevant code">
        {data.relevant_files.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            {data.state === "CREATED" || data.state === "ANALYZING_REPORT"
              ? "Repository analysis has not run yet."
              : "No file matched the report."}
          </p>
        ) : (
          <ul className="divide-y rounded-lg border">
            {data.relevant_files.map((f) => (
              <li key={f.file} className="space-y-1 px-3 py-2">
                <div className="flex items-center gap-2">
                  <span className="truncate font-mono text-xs">{f.file}</span>
                  <span className="ml-auto text-xs text-muted-foreground tabular-nums">
                    score {f.score}
                  </span>
                  {f.sent_to_model && <Badge variant="secondary">sent to model</Badge>}
                </div>
                <p className="text-xs text-muted-foreground">{f.reasons.join("; ")}</p>
              </li>
            ))}
          </ul>
        )}
      </Section>
    </div>
  );
}

function TestTab({ data }: { data: EvidenceReport }) {
  const executed = [...data.attempts].reverse().find((a) => a.executions.length > 0);
  const latest = data.attempts.at(-1);
  const shown = executed ?? latest;
  if (!shown?.test_code) {
    return (
      <p className="text-sm text-muted-foreground">
        {isTerminal(data.state) ? "No test was generated." : "No test has been generated yet."}
      </p>
    );
  }
  const note = executed
    ? `Executed test from attempt ${executed.number}`
    : `Attempt ${shown.number}: ${humanize(shown.status)} — not executed`;
  return (
    <div className="space-y-4">
      <CodeView code={shown.test_code} label={note} />
      <div className="grid gap-4 md:grid-cols-2">
        <Section title="Strategy (model's description, not verified)">
          <p className="text-sm">{shown.strategy ?? "–"}</p>
        </Section>
        <Section title="Model assumptions">
          <BulletList items={shown.assumptions} empty="None stated." />
        </Section>
      </div>
      {shown.contract && (
        <Section title="Verification contract">
          <LogView text={JSON.stringify(shown.contract, null, 2)} />
        </Section>
      )}
    </div>
  );
}

function AttemptsTab({ attempts }: { attempts: AttemptSummary[] }) {
  if (!attempts.length) return <p className="text-sm text-muted-foreground">No attempts yet.</p>;
  return (
    <div className="space-y-4">
      {attempts.map((a) => (
        <Card key={a.number}>
          <CardHeader className="flex flex-row flex-wrap items-center gap-2">
            <CardTitle>Attempt {a.number}</CardTitle>
            <Badge variant={a.status === "rejected" || a.status === "llm_error" ? "destructive" : "secondary"}>
              {humanize(a.status)}
            </Badge>
            {a.model && (
              <span className="ml-auto font-mono text-xs text-muted-foreground">
                {a.model} · {a.prompt}
              </span>
            )}
          </CardHeader>
          <CardContent className="space-y-4">
            {a.validation_errors.length > 0 && (
              <Section title="Rejected because">
                <BulletList items={a.validation_errors} mono empty="" />
              </Section>
            )}
            {a.validation_warnings.length > 0 && (
              <Section title="Warnings">
                <BulletList items={a.validation_warnings} empty="" />
              </Section>
            )}
            {a.executions.length > 0 ? (
              <>
                <div className="overflow-x-auto rounded-lg border">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Run</TableHead>
                        <TableHead>Main test</TableHead>
                        <TableHead>Exit</TableHead>
                        <TableHead>Duration</TableHead>
                        <TableHead>Limits</TableHead>
                        <TableHead>Error</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {a.executions.map((e) => (
                        <TableRow key={e.run_index}>
                          <TableCell className="tabular-nums">{e.run_index + 1}</TableCell>
                          <TableCell>{e.main_status ?? "–"}</TableCell>
                          <TableCell className="font-mono tabular-nums">{e.exit_code ?? "–"}</TableCell>
                          <TableCell className="tabular-nums">{formatDuration(e.duration_ms)}</TableCell>
                          <TableCell>
                            {e.timed_out ? "timed out" : e.oom_killed ? "out of memory" : "–"}
                          </TableCell>
                          <TableCell className="max-w-80 truncate font-mono text-xs" title={e.message}>
                            {e.exception_type ? `${e.exception_type}: ${e.message}` : e.message || "–"}
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
                {a.executions.map((e) => (
                  <details key={e.run_index} className="group">
                    <summary className="cursor-pointer text-sm text-muted-foreground hover:text-foreground">
                      Output of run {e.run_index + 1}
                    </summary>
                    <div className="mt-2">
                      <LogView text={e.output_excerpt} />
                    </div>
                  </details>
                ))}
              </>
            ) : (
              <p className="text-sm text-muted-foreground">Not executed.</p>
            )}
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

function ReportTab({ data }: { data: EvidenceReport }) {
  const r = data.bug_report;
  const rows: [string, string | null][] = [
    ["Description", r.description || null],
    ["Expected behavior", r.expected_behavior],
    ["Actual behavior", r.actual_behavior],
  ];
  return (
    <div className="space-y-4">
      <dl className="grid gap-3">
        {rows.map(([label, value]) => (
          <div key={label}>
            <dt className="text-xs text-muted-foreground">{label}</dt>
            <dd className="text-sm whitespace-pre-wrap">
              {value ?? <span className="text-muted-foreground italic">Not provided</span>}
            </dd>
          </div>
        ))}
      </dl>
      <Section title="Missing from the report">
        <BulletList items={r.missing_fields.map(humanize)} empty="Nothing recorded as missing." />
      </Section>
      <Section title="Repository">
        <p className="font-mono text-xs">
          {data.repository.sha256 ?? data.repository.id} · {data.repository.layout ?? "unknown"} layout
        </p>
      </Section>
    </div>
  );
}

function TimelineTab({ data }: { data: EvidenceReport }) {
  return (
    <ol className="space-y-2">
      {data.timeline.map((t, i) => (
        <li key={i} className="flex gap-3 text-sm">
          <time className="w-40 shrink-0 text-xs text-muted-foreground tabular-nums" dateTime={t.at}>
            {new Date(t.at).toLocaleTimeString()}
          </time>
          <span className="w-44 shrink-0 font-medium">{STATE_LABEL[t.state]}</span>
          <span className="text-muted-foreground">{t.message}</span>
        </li>
      ))}
    </ol>
  );
}
