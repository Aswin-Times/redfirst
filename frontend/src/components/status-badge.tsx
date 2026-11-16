import {
  Ban,
  Bug,
  CircleCheck,
  CircleDashed,
  CircleHelp,
  Loader,
  ServerCrash,
  type LucideIcon,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { OUTCOME_INFO, STATE_LABEL } from "@/lib/outcome";
import type { InvestigationState, Outcome } from "@/lib/types";
import { cn } from "@/lib/utils";

export const OUTCOME_STYLE: Record<Outcome, { icon: LucideIcon; className: string }> = {
  // Reproduced means the bug is confirmed, so it gets the alarm colour.
  REPRODUCED: { icon: Bug, className: "bg-destructive/10 text-destructive" },
  NOT_REPRODUCED: { icon: CircleCheck, className: "bg-success/10 text-success" },
  INCONCLUSIVE: { icon: CircleHelp, className: "bg-warning/10 text-warning" },
  EXECUTION_ERROR: { icon: ServerCrash, className: "border-border text-muted-foreground" },
};

/** Shows the verified outcome when there is one, otherwise the pipeline state. */
export function StatusBadge({
  state,
  outcome,
  className,
}: {
  state: InvestigationState;
  outcome: Outcome | null;
  className?: string;
}) {
  if (outcome) {
    const { icon: Icon, className: style } = OUTCOME_STYLE[outcome];
    return (
      <Badge variant="outline" className={cn("border-transparent", style, className)}>
        <Icon data-icon="inline-start" aria-hidden />
        {OUTCOME_INFO[outcome].label}
      </Badge>
    );
  }
  const Icon = state === "CANCELLED" ? Ban : state === "CREATED" ? CircleDashed : Loader;
  const running = state !== "CANCELLED" && state !== "CREATED" && state !== "FAILED";
  return (
    <Badge variant="secondary" className={className}>
      <Icon data-icon="inline-start" aria-hidden className={cn(running && "animate-spin")} />
      {STATE_LABEL[state]}
    </Badge>
  );
}
