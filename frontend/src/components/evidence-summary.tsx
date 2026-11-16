import { LogView } from "@/components/code-view";
import { Badge } from "@/components/ui/badge";
import { parseEvidence, type PathKind } from "@/lib/evidence";
import { cn } from "@/lib/utils";

const KIND_LABEL: Record<PathKind, string> = {
  target: "target code",
  test: "generated test",
  library: "library",
  code: "repository",
};

const ORIGIN_TEXT = {
  target: "Raised inside the target code",
  assertion: "A failed assertion on the value the target code returned",
} as const;

function Label({ children }: { children: string }) {
  return <h4 className="mb-1.5 text-xs font-medium tracking-wide text-muted-foreground uppercase">{children}</h4>;
}

/**
 * The verdict's evidence laid out by meaning. The full original lines stay available under
 * "Raw evidence", and any line the parser does not recognise is shown rather than dropped.
 */
export function EvidenceSummary({ lines, terminal }: { lines: string[]; terminal: boolean }) {
  if (lines.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        {terminal
          ? "No test was verified, so there is no execution evidence."
          : "Evidence appears once a test has run and been verified."}
      </p>
    );
  }
  const p = parseEvidence(lines);
  return (
    <div className="space-y-5">
      {p.failure && (
        <section>
          <Label>Failure observed</Label>
          <div className="rounded-lg border bg-muted/30 p-3">
            <p className="font-mono text-sm font-semibold break-words">{p.failure.type}</p>
            <p className="mt-1 font-mono text-xs break-words whitespace-pre-wrap">
              {p.failure.message || "(no message)"}
            </p>
            {p.origin && <p className="mt-2 text-xs text-muted-foreground">{ORIGIN_TEXT[p.origin]}</p>}
          </div>
        </section>
      )}

      {p.locations.length > 0 && (
        <section>
          <Label>Where it happened</Label>
          <ul className="divide-y rounded-lg border">
            {p.locations.map((l, i) => (
              <li key={i} className="flex flex-wrap items-baseline gap-x-2 gap-y-1 px-3 py-2">
                <span className="font-mono text-xs break-all">{l.path}</span>
                <span className="font-mono text-xs text-muted-foreground">in {l.function}()</span>
                <Badge
                  variant={l.kind === "target" ? "destructive" : "secondary"}
                  className={cn("ml-auto", l.kind === "library" && "opacity-70")}
                >
                  {KIND_LABEL[l.kind]}
                </Badge>
              </li>
            ))}
          </ul>
        </section>
      )}

      {p.exitCode !== null && (
        <p className="text-xs text-muted-foreground">
          pytest exited with code <span className="font-mono text-foreground">{p.exitCode}</span>,
          read from the container by the runner rather than reported by the test.
        </p>
      )}

      {p.notes.length > 0 && (
        <section>
          <Label>Details</Label>
          <ul className="list-disc space-y-1 pl-5 font-mono text-xs">
            {p.notes.map((n, i) => (
              <li key={i} className="break-all">
                {n}
              </li>
            ))}
          </ul>
        </section>
      )}

      <details>
        <summary className="cursor-pointer text-xs text-muted-foreground select-none hover:text-foreground">
          Raw evidence ({lines.length} {lines.length === 1 ? "line" : "lines"})
        </summary>
        <div className="mt-2">
          <LogView text={lines.join("\n")} />
        </div>
      </details>
    </div>
  );
}
