"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { RefreshCw, SearchCode } from "lucide-react";
import { useState } from "react";

import { EmptyState, ErrorAlert, LoadingRows, PageHeader } from "@/components/feedback";
import { InvestigationsTable } from "@/components/investigations-table";
import { Button, buttonVariants } from "@/components/ui/button";
import { useResource } from "@/hooks/use-resource";
import { api } from "@/lib/api";
import { resultParam } from "@/lib/dashboard";
import { OUTCOME_INFO } from "@/lib/outcome";
import type { Outcome } from "@/lib/types";

const selectClass =
  "h-8 rounded-lg border border-input bg-transparent px-2.5 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 dark:bg-input/30";

export function InvestigationHistory() {
  const [projectId, setProjectId] = useState("");
  const searchParams = useSearchParams();
  const [outcome, setOutcome] = useState<"" | Outcome | "running">(() =>
    resultParam(searchParams.get("result")),
  );
  const projects = useResource(() => api.projects(), []);
  const items = useResource(() => api.investigations(projectId || undefined), [projectId]);

  const visible = (items.data ?? []).filter((i) =>
    outcome === "" ? true : outcome === "running" ? i.outcome === null : i.outcome === outcome,
  );

  return (
    <>
      <PageHeader
        title="Investigations"
        description="Every investigation and its actual result."
        actions={
          <Button variant="outline" size="sm" onClick={() => items.refresh()}>
            <RefreshCw data-icon="inline-start" aria-hidden /> Refresh
          </Button>
        }
      />
      <div className="mb-4 flex flex-wrap gap-3">
        <label className="flex items-center gap-2 text-sm">
          <span className="text-muted-foreground">Project</span>
          <select className={selectClass} value={projectId} onChange={(e) => setProjectId(e.target.value)}>
            <option value="">All projects</option>
            {projects.data?.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        </label>
        <label className="flex items-center gap-2 text-sm">
          <span className="text-muted-foreground">Result</span>
          <select
            className={selectClass}
            value={outcome}
            onChange={(e) => {
              const next = e.target.value as typeof outcome;
              setOutcome(next);
              window.history.replaceState(null, "", next ? `?result=${next}` : window.location.pathname);
            }}
          >
            <option value="">Any</option>
            <option value="running">No outcome yet</option>
            {(Object.keys(OUTCOME_INFO) as Outcome[]).map((o) => (
              <option key={o} value={o}>
                {OUTCOME_INFO[o].label}
              </option>
            ))}
          </select>
        </label>
      </div>
      {items.error && <ErrorAlert error={items.error} title="Could not load investigations" />}
      {items.loading && !items.data && <LoadingRows rows={5} />}
      {items.data &&
        (visible.length === 0 ? (
          <EmptyState
            icon={SearchCode}
            title={items.data.length === 0 ? "No investigations yet" : "Nothing matches these filters"}
            action={
              items.data.length === 0 && (
                <Link href="/investigations/new" className={buttonVariants()}>
                  Start an investigation
                </Link>
              )
            }
          />
        ) : (
          <InvestigationsTable items={visible} projects={projects.data} />
        ))}
    </>
  );
}
