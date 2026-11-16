import Link from "next/link";

import { StatusBadge } from "@/components/status-badge";
import { relativeTime } from "@/lib/dashboard";
import type { InvestigationSummary } from "@/lib/types";

/** Queued, running and failed investigations; renders nothing when there are none. */
export function NeedsAttention({ items }: { items: InvestigationSummary[] }) {
  if (items.length === 0) return null;
  return (
    <section aria-labelledby="attention-title">
      <h2 id="attention-title" className="mb-2 text-sm font-medium">
        Needs attention
      </h2>
      <ul className="divide-y rounded-xl border bg-card">
        {items.map((inv) => (
          <li key={inv.id} className="relative flex items-center gap-3 px-3 py-2.5 hover:bg-muted/50">
            <StatusBadge state={inv.state} outcome={inv.outcome} />
            <Link
              href={`/investigations/${inv.id}`}
              className="min-w-0 flex-1 truncate text-sm font-medium after:absolute after:inset-0"
            >
              {inv.title}
            </Link>
            <time className="shrink-0 text-xs text-muted-foreground" title={inv.created_at}>
              {relativeTime(inv.created_at)}
            </time>
          </li>
        ))}
      </ul>
    </section>
  );
}
