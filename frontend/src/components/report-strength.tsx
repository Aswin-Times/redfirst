import { Check, Minus } from "lucide-react";

import { checklist, type FormValues } from "@/lib/report-form";
import { cn } from "@/lib/utils";

/**
 * What the report gives REDFIRST to work with. Each line states a real consequence for how the
 * result can be decided; there is deliberately no score, because none would be honest.
 */
export function ReportStrength({ values }: { values: FormValues }) {
  return (
    <aside aria-labelledby="strength-title" className="rounded-xl border bg-card p-4">
      <h3 id="strength-title" className="text-sm font-medium">
        What REDFIRST will use
      </h3>
      <ul className="mt-3 space-y-3">
        {checklist(values).map((item) => {
          const warn = !item.provided && item.key === "expected_behavior";
          const Icon = item.provided ? Check : Minus;
          return (
            <li key={item.key} data-provided={item.provided} className="flex gap-2.5">
              <Icon
                aria-hidden
                className={cn(
                  "mt-0.5 size-4 shrink-0",
                  item.provided ? "text-success" : warn ? "text-warning" : "text-muted-foreground/60",
                )}
              />
              <div className="min-w-0">
                <p className="text-sm font-medium">
                  {item.label}
                  <span className="sr-only">{item.provided ? "provided" : "not provided"}</span>
                </p>
                <p className={cn("text-xs text-pretty", warn ? "text-warning" : "text-muted-foreground")}>
                  {item.effect}
                </p>
              </div>
            </li>
          );
        })}
      </ul>
    </aside>
  );
}
