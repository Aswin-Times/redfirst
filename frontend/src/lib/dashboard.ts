import { formatDate, parseTimestamp } from "@/lib/outcome";
import { isTerminal } from "@/lib/stages";
import { OUTCOMES } from "@/lib/summary";
import type { InvestigationSummary, Outcome } from "@/lib/types";

export interface OutcomeShare {
  outcome: Outcome;
  count: number;
  percent: number;
}

/**
 * Each outcome's count and whole-number percentage. Percentages use the largest-remainder
 * method, so they always add up to exactly 100 (never 99 or 101 from rounding); with no
 * outcomes at all every percentage is 0.
 */
export function outcomeShares(counts: Record<Outcome, number>): OutcomeShare[] {
  const total = OUTCOMES.reduce((n, o) => n + counts[o], 0);
  const rows = OUTCOMES.map((outcome, order) => {
    const raw = total ? (counts[outcome] * 100) / total : 0;
    return { outcome, count: counts[outcome], percent: Math.floor(raw), rest: raw % 1, order };
  });
  let left = total ? 100 - rows.reduce((n, r) => n + r.percent, 0) : 0;
  for (const r of [...rows].sort((a, b) => b.rest - a.rest || a.order - b.order)) {
    if (left <= 0) break;
    if (r.rest > 0) {
      r.percent += 1;
      left -= 1;
    }
  }
  return rows.map(({ outcome, count, percent }) => ({ outcome, count, percent }));
}

const dayKey = (d: Date) =>
  `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;

/** Investigations created per local day for the last `days` days, oldest first, ending today. */
export function dailyCounts(
  items: Pick<InvestigationSummary, "created_at">[],
  days = 14,
  now = Date.now(),
): { date: string; count: number }[] {
  const buckets = new Map<string, number>();
  for (let i = days - 1; i >= 0; i--) {
    const d = new Date(now);
    d.setDate(d.getDate() - i);
    buckets.set(dayKey(d), 0);
  }
  for (const item of items) {
    const key = dayKey(new Date(parseTimestamp(item.created_at)));
    if (buckets.has(key)) buckets.set(key, buckets.get(key)! + 1);
  }
  return [...buckets].map(([date, count]) => ({ date, count }));
}

/** "just now", "30m ago", "3h ago", "2d ago"; a full date after a week. */
export function relativeTime(iso: string, now = Date.now()): string {
  const diff = now - parseTimestamp(iso);
  if (diff < 45_000) return "just now"; // includes small clock skew into the future
  if (diff < 3_600_000) return `${Math.max(1, Math.floor(diff / 60_000))}m ago`;
  if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)}h ago`;
  if (diff < 7 * 86_400_000) return `${Math.floor(diff / 86_400_000)}d ago`;
  return formatDate(iso);
}

/** Investigations that are queued, running or failed, newest first. */
export function needsAttention(items: InvestigationSummary[]): InvestigationSummary[] {
  return items
    .filter((i) => !isTerminal(i.state) || i.state === "FAILED")
    .sort((a, b) => parseTimestamp(b.created_at) - parseTimestamp(a.created_at));
}
