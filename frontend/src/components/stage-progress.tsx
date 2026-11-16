import { Check, Circle, CircleX, Loader, Minus } from "lucide-react";

import { deriveStages, isTerminal, type StageStatus } from "@/lib/stages";
import type { InvestigationState, TimelineEntry } from "@/lib/types";
import { cn } from "@/lib/utils";

const ICON: Record<StageStatus, typeof Check> = {
  done: Check,
  active: Loader,
  failed: CircleX,
  pending: Circle,
  skipped: Minus,
};

const STATUS_TEXT: Record<StageStatus, string> = {
  done: "done",
  active: "in progress",
  failed: "failed here",
  pending: "not started",
  skipped: "not reached",
};

const DOT: Record<StageStatus, string> = {
  done: "border-foreground bg-foreground text-background",
  active: "border-foreground text-foreground",
  failed: "border-destructive bg-destructive/10 text-destructive",
  pending: "border-border text-muted-foreground/50",
  skipped: "border-border text-muted-foreground/50",
};

const REACHED: StageStatus[] = ["done", "active", "failed"];

/** The six pipeline stages as a stepper: horizontal with connectors from `sm`, a list below. */
export function StageProgress({
  timeline,
  state,
}: {
  timeline: TimelineEntry[];
  state: InvestigationState;
}) {
  const stages = deriveStages(timeline, state);
  return (
    <ol aria-label="Pipeline stages" className="flex flex-col gap-2.5 sm:flex-row sm:gap-0">
      {stages.map((s, i) => {
        const Icon = ICON[s.status];
        const dim = s.status === "pending" || s.status === "skipped";
        return (
          <li
            key={s.state}
            aria-current={s.status === "active" ? "step" : undefined}
            className="relative flex items-center gap-2.5 sm:flex-1 sm:flex-col sm:gap-1.5 sm:text-center"
          >
            {i > 0 && (
              <span
                aria-hidden
                className={cn(
                  "absolute top-3 right-1/2 hidden h-px w-full sm:block",
                  REACHED.includes(s.status) ? "bg-foreground/60" : "bg-border",
                )}
              />
            )}
            <span
              className={cn(
                "relative z-10 grid size-6 shrink-0 place-items-center rounded-full border bg-background",
                DOT[s.status],
              )}
            >
              <Icon
                aria-hidden
                className={cn("size-3.5", s.status === "active" && "animate-spin")}
              />
            </span>
            <span className="min-w-0">
              <span className={cn("block text-xs font-medium", dim && "text-muted-foreground")}>
                {s.label}
                {s.visits > 1 && (
                  <span className="font-normal text-muted-foreground"> · {s.visits}×</span>
                )}
              </span>
              <span
                className={cn(
                  "block text-xs text-muted-foreground",
                  s.status === "done" && "sr-only",
                  s.status === "failed" && "text-destructive",
                )}
              >
                {STATUS_TEXT[s.status]}
              </span>
            </span>
          </li>
        );
      })}
    </ol>
  );
}

/**
 * The stepper while the investigation runs; afterwards a one-line summary that opens the
 * stepper (already open when something failed, because the failing stage is the point).
 */
export function Pipeline({
  timeline,
  state,
}: {
  timeline: TimelineEntry[];
  state: InvestigationState;
}) {
  if (!isTerminal(state)) return <StageProgress timeline={timeline} state={state} />;
  const stages = deriveStages(timeline, state);
  const failed = stages.find((s) => s.status === "failed");
  const done = stages.filter((s) => s.status === "done").length;
  const summary = failed
    ? `Pipeline: failed at ${failed.label.toLowerCase()}`
    : state === "CANCELLED"
      ? `Pipeline: cancelled after ${done} of ${stages.length} stages`
      : `Pipeline: ${done} of ${stages.length} stages completed`;
  return (
    <details open={state !== "COMPLETED"} className="rounded-lg border px-3 py-2">
      <summary className="cursor-pointer text-sm text-muted-foreground select-none hover:text-foreground">
        {summary}
      </summary>
      <div className="pt-3 pb-1">
        <StageProgress timeline={timeline} state={state} />
      </div>
    </details>
  );
}
