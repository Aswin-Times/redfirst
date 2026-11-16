import Link from "next/link";

import { OUTCOME_INFO } from "@/lib/outcome";
import type { OutcomeShare } from "@/lib/dashboard";
import type { Outcome } from "@/lib/types";
import { cn } from "@/lib/utils";

const COLOR: Record<Outcome, string> = {
  REPRODUCED: "bg-destructive",
  NOT_REPRODUCED: "bg-success",
  INCONCLUSIVE: "bg-warning",
  EXECUTION_ERROR: "bg-muted-foreground/50",
};

const href = (outcome: Outcome) => `/investigations?result=${outcome}`;

/** The outcome mix as one segmented bar, with a legend that links to the filtered list. */
export function OutcomeBar({ shares }: { shares: OutcomeShare[] }) {
  const present = shares.filter((s) => s.count > 0);
  if (present.length === 0) {
    return <p className="text-sm text-muted-foreground">No finished investigations yet.</p>;
  }
  const summary = present
    .map((s) => `${s.count} ${OUTCOME_INFO[s.outcome].label.toLowerCase()} (${s.percent}%)`)
    .join(", ");
  return (
    <div>
      <div
        role="img"
        aria-label={`Outcomes: ${summary}`}
        className="flex h-3 gap-0.5 overflow-hidden rounded-full bg-muted"
      >
        {/* Decorative: the legend below holds the links. Interactive elements may not sit inside
            an element with role="img". */}
        {present.map((s) => (
          <div
            key={s.outcome}
            style={{ flexGrow: s.count }}
            className={cn("min-w-2 basis-0", COLOR[s.outcome])}
          />
        ))}
      </div>
      <ul aria-label="Outcome legend" className="mt-4 grid grid-cols-1 gap-x-6 gap-y-2 text-sm min-[26rem]:grid-cols-2">
        {shares.map((s) => {
          const inner = (
            <>
              <span aria-hidden className={cn("size-2.5 shrink-0 rounded-full", COLOR[s.outcome])} />
              <span className="min-w-0 truncate">{OUTCOME_INFO[s.outcome].label}</span>
              <span className="ml-auto font-mono text-xs tabular-nums">{s.count}</span>
              <span className="w-9 text-right text-xs text-muted-foreground tabular-nums">
                {s.percent}%
              </span>
            </>
          );
          return (
            <li key={s.outcome}>
              {s.count > 0 ? (
                <Link href={href(s.outcome)} className="flex items-center gap-2 rounded-md py-0.5 hover:bg-muted">
                  {inner}
                </Link>
              ) : (
                <span className="flex items-center gap-2 py-0.5 text-muted-foreground opacity-60">
                  {inner}
                </span>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
