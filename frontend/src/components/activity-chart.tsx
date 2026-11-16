import { cn } from "@/lib/utils";

const shortDate = (key: string) => {
  const [y, m, d] = key.split("-").map(Number);
  return new Date(y, m - 1, d).toLocaleDateString(undefined, { month: "short", day: "numeric" });
};

/** Investigations per day as plain bars: no chart library, readable by screen readers. */
export function ActivityChart({ days }: { days: { date: string; count: number }[] }) {
  const total = days.reduce((n, d) => n + d.count, 0);
  const max = Math.max(0, ...days.map((d) => d.count));
  return (
    <div>
      <div
        role="img"
        aria-label={`Investigations per day, last ${days.length} days: ${total} in total, busiest day ${max}`}
        className="flex h-20 items-end gap-1"
      >
        {days.map((d, i) => (
          <div
            key={d.date}
            data-bar
            title={`${d.date}: ${d.count}`}
            style={{ height: d.count ? `${Math.max(10, (d.count / max) * 100)}%` : "2px" }}
            className={cn(
              "flex-1 rounded-sm",
              d.count === 0 ? "bg-border" : i === days.length - 1 ? "bg-foreground" : "bg-foreground/45",
            )}
          />
        ))}
      </div>
      {days.length > 0 && (
        <div className="mt-1.5 flex justify-between text-xs text-muted-foreground">
          <span>{shortDate(days[0].date)}</span>
          <span>Today</span>
        </div>
      )}
    </div>
  );
}
