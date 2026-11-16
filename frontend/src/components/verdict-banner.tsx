"use client";

import { Ban, Crosshair, Hourglass, Layers, Loader, Repeat2, ServerCrash, Timer, type LucideIcon } from "lucide-react";
import type { ReactNode } from "react";

import { OUTCOME_STYLE } from "@/components/status-badge";
import { useNow } from "@/hooks/use-now";
import { OUTCOME_INFO, STATE_LABEL, humanize } from "@/lib/outcome";
import { isTerminal } from "@/lib/stages";
import type { EvidenceReport, Outcome } from "@/lib/types";
import { NOTABLE_QUEUE_MS, formatElapsed, reasonInfo, runTimes, verdictFacts } from "@/lib/verdict";
import { cn } from "@/lib/utils";

/** Box and icon colours per outcome; the meaning matches the status badge. */
const TONE: Record<Outcome, string> = {
  REPRODUCED: "border-destructive/30 bg-destructive/5",
  NOT_REPRODUCED: "border-success/30 bg-success/5",
  INCONCLUSIVE: "border-warning/30 bg-warning/5",
  EXECUTION_ERROR: "border-border bg-muted/40",
};

/** What a person must keep in mind about each outcome before acting on it. */
const CAVEAT: Partial<Record<Outcome, string>> = {
  REPRODUCED:
    "Read the generated test before relying on this. It shows behavior matching the report; it does not explain the cause.",
  NOT_REPRODUCED:
    "This does not prove the bug is absent, only that it did not appear under the tested conditions.",
  INCONCLUSIVE: "No conclusion either way. The next steps below say what could change that.",
};

interface View {
  icon: LucideIcon;
  tone: string;
  chip: string;
  spin?: boolean;
  live?: boolean;
  title: string;
  reason?: string;
  sentence: ReactNode;
  caveat?: ReactNode;
}

function describe(report: EvidenceReport): View {
  const { outcome, state } = report;
  if (outcome && outcome !== "EXECUTION_ERROR") {
    const { icon, className } = OUTCOME_STYLE[outcome];
    return {
      icon, tone: TONE[outcome], chip: className.replace("border-transparent", ""),
      title: OUTCOME_INFO[outcome].label,
      reason: report.outcome_reason ? humanize(report.outcome_reason) : undefined,
      sentence: reasonInfo(report.outcome_reason) || OUTCOME_INFO[outcome].description,
      caveat: CAVEAT[outcome],
    };
  }
  if (state === "FAILED" || outcome === "EXECUTION_ERROR") {
    const e = report.error;
    return {
      icon: ServerCrash, tone: "border-destructive/30 bg-destructive/5",
      chip: "bg-destructive/10 text-destructive", title: OUTCOME_INFO.EXECUTION_ERROR.label,
      sentence: e?.detail ?? OUTCOME_INFO.EXECUTION_ERROR.description,
      caveat: (
        <>
          {e?.type && <span className="font-mono text-xs text-foreground">{e.type}</span>}
          {e?.type && " · "}
          REDFIRST itself failed; nothing is concluded about the bug.
          {e?.retryable && " This failure may be temporary; try again later."}
        </>
      ),
    };
  }
  if (state === "CANCELLED") {
    return {
      icon: Ban, tone: "border-border bg-muted/40", chip: "bg-muted text-muted-foreground",
      title: "Cancelled", sentence: "This investigation was cancelled before it finished.",
    };
  }
  return {
    icon: Loader, tone: "border-border bg-muted/40", chip: "bg-muted text-foreground", spin: true,
    live: true, title: "Investigating",
    sentence:
      state === "CREATED"
        ? "Queued, waiting for a worker to pick this up."
        : `${STATE_LABEL[state]}…`,
  };
}

function announcement(view: View): string {
  const sentence = typeof view.sentence === "string" ? view.sentence : "";
  return view.live
    ? `${view.title}: ${sentence}`
    : `${view.title}${view.reason ? `, ${view.reason.toLowerCase()}` : ""}. ${sentence}`;
}

function Fact({ icon: Icon, children }: { icon: LucideIcon; children: ReactNode }) {
  return (
    <li className="flex items-center gap-1.5">
      <Icon className="size-3.5 shrink-0" aria-hidden />
      <span className="tabular-nums">{children}</span>
    </li>
  );
}

export function VerdictBanner({ report }: { report: EvidenceReport }) {
  const view = describe(report);
  const now = useNow(!isTerminal(report.state));
  const facts = verdictFacts(report);
  const times = runTimes(report, now);
  const Icon = view.icon;
  const plural = (n: number, noun: string) => `${n} ${noun}${n === 1 ? "" : "s"}`;

  return (
    <section aria-labelledby="verdict-title" className={cn("rounded-xl border p-4 sm:p-5", view.tone)}>
      {/* The only live region here. Its text changes when the stage or the result changes, never
          with the timer, so screen readers hear progress and the final result but not a tick
          every second. */}
      <div role="status" aria-live="polite" className="sr-only">
        {announcement(view)}
      </div>
      <div className="flex items-start gap-3 sm:gap-4">
        <span className={cn("grid size-10 shrink-0 place-items-center rounded-full sm:size-12", view.chip)}>
          <Icon className={cn("size-5 sm:size-6", view.spin && "animate-spin")} aria-hidden />
        </span>
        <div className="min-w-0 flex-1 space-y-1">
          <div className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5">
            <h2 id="verdict-title" className="text-2xl font-semibold tracking-tight">
              {view.title}
            </h2>
            {view.reason && <span className="text-sm text-muted-foreground">{view.reason}</span>}
          </div>
          <p className="text-sm text-pretty">{view.sentence}</p>
          {view.caveat && <p className="text-sm text-pretty text-muted-foreground">{view.caveat}</p>}
        </div>
      </div>
      <ul
        aria-label="Key facts"
        className="mt-4 flex flex-wrap gap-x-5 gap-y-1.5 border-t border-current/10 pt-3 text-sm text-muted-foreground"
      >
        {facts.runs > 0 && (
          <Fact icon={Repeat2}>
            {facts.unanimous && facts.runs > 1
              ? `${facts.runs} of ${facts.runs} runs agreed`
              : plural(facts.runs, "run")}
          </Fact>
        )}
        {facts.attempts > 0 && <Fact icon={Layers}>{plural(facts.attempts, "attempt")}</Fact>}
        {facts.evidenceKind && <Fact icon={Crosshair}>{facts.evidenceKind}</Fact>}
        <Fact icon={Timer}>
          {!times.started ? "Queued for " : view.live ? "Running for " : "Took "}
          {formatElapsed(times.started ? times.runMs : times.queuedMs)}
        </Fact>
        {times.started && times.queuedMs >= NOTABLE_QUEUE_MS && (
          <Fact icon={Hourglass}>Waited {formatElapsed(times.queuedMs)} in the queue</Fact>
        )}
      </ul>
    </section>
  );
}
