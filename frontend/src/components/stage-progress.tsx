import { Check, Circle, CircleX, Loader, Minus } from "lucide-react";

import { deriveStages, type StageStatus } from "@/lib/stages";
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

export function StageProgress({
  timeline,
  state,
}: {
  timeline: TimelineEntry[];
  state: InvestigationState;
}) {
  const stages = deriveStages(timeline, state);
  return (
    <ol className="grid grid-cols-2 gap-px overflow-hidden rounded-lg border bg-border sm:grid-cols-3 lg:grid-cols-6">
      {stages.map((s, i) => {
        const Icon = ICON[s.status];
        return (
          <li
            key={s.state}
            className="flex items-start gap-2 bg-background px-3 py-2.5"
            aria-current={s.status === "active" ? "step" : undefined}
          >
            <Icon
              aria-hidden
              className={cn(
                "mt-0.5 size-4 shrink-0",
                s.status === "done" && "text-foreground",
                s.status === "active" && "animate-spin text-foreground",
                s.status === "failed" && "text-destructive",
                (s.status === "pending" || s.status === "skipped") && "text-muted-foreground/50",
              )}
            />
            <div className="min-w-0">
              <p
                className={cn(
                  "text-xs font-medium",
                  (s.status === "pending" || s.status === "skipped") && "text-muted-foreground",
                )}
              >
                <span className="text-muted-foreground tabular-nums">{i + 1}. </span>
                {s.label}
              </p>
              <p className="text-xs text-muted-foreground">
                {STATUS_TEXT[s.status]}
                {s.visits > 1 && ` · ${s.visits}×`}
              </p>
            </div>
          </li>
        );
      })}
    </ol>
  );
}
