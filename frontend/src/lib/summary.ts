import { OUTCOME_INFO } from "@/lib/outcome";
import { isTerminal } from "@/lib/stages";
import type { InvestigationSummary, Outcome } from "@/lib/types";

export const OUTCOMES = Object.keys(OUTCOME_INFO) as Outcome[];

/** Count real outcomes; investigations still running have none yet and are counted apart. */
export function summarize(items: InvestigationSummary[]) {
  const counts = Object.fromEntries(OUTCOMES.map((o) => [o, 0])) as Record<Outcome, number>;
  let active = 0;
  for (const inv of items) {
    if (inv.outcome) counts[inv.outcome] += 1;
    else if (!isTerminal(inv.state)) active += 1;
  }
  return { counts, active };
}
