"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { RefreshCw, SearchCode } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { useAnnounce } from "@/components/announcer";
import { EmptyState, ErrorAlert, LoadingRows, PageHeader } from "@/components/feedback";
import { InvestigationsTable } from "@/components/investigations-table";
import { Button, buttonVariants } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useResource } from "@/hooks/use-resource";
import { api } from "@/lib/api";
import {
  DEFAULT_STATE, PAGE_SIZE, applyView, parseListParams, toQuery, type ListState, type SortKey,
} from "@/lib/list-view";
import { OUTCOME_INFO } from "@/lib/outcome";
import type { Outcome } from "@/lib/types";

const selectClass =
  "h-8 rounded-lg border border-input bg-transparent px-2.5 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 dark:bg-input/30";

const SORT_LABEL: Record<SortKey, string> = {
  newest: "Newest first",
  oldest: "Oldest first",
  result: "By result",
};

const plural = (n: number) => `${n} investigation${n === 1 ? "" : "s"}`;

function countText(filtered: number, shown: number, all: number): string {
  const tail = filtered !== all ? ` matching · ${all} in total` : "";
  return filtered > shown ? `Showing ${shown} of ${filtered}${tail}` : `${plural(filtered)}${tail}`;
}

export function InvestigationHistory() {
  const searchParams = useSearchParams();
  const announce = useAnnounce();
  // The filters live in the URL, so a filtered view can be shared and survives a reload.
  const [state, setState] = useState<ListState>(() => parseListParams(searchParams));
  const [limit, setLimit] = useState(PAGE_SIZE);
  const interacted = useRef(false);
  const focusRow = useRef<number | null>(null);
  const table = useRef<HTMLDivElement>(null);

  const projects = useResource(() => api.projects(), []);
  const items = useResource(() => api.investigations(state.project || undefined), [state.project]);

  function update(patch: Partial<ListState>) {
    const next = { ...state, ...patch };
    interacted.current = true;
    setState(next);
    setLimit(PAGE_SIZE);
    window.history.replaceState(null, "", `${window.location.pathname}${toQuery(next)}`);
  }

  const all = items.data ?? [];
  const visible = applyView(all, state);
  const shown = visible.slice(0, limit);
  const remaining = visible.length - shown.length;
  const filtersActive = toQuery(state) !== "";
  const summary = countText(visible.length, shown.length, all.length);

  // Revealed rows: put keyboard focus on the first new one, or it would be lost with the button.
  useEffect(() => {
    if (focusRow.current === null) return;
    table.current?.querySelector<HTMLAnchorElement>(`tbody tr:nth-child(${focusRow.current + 1}) a`)?.focus();
    focusRow.current = null;
  }, [limit]);

  // Say how many results there are after the user stops typing, not on every keystroke.
  useEffect(() => {
    if (!interacted.current || !items.data) return;
    const timer = setTimeout(() => announce(summary), 700);
    return () => clearTimeout(timer);
  }, [summary, items.data, announce]);

  function showMore() {
    focusRow.current = shown.length;
    setLimit(limit + PAGE_SIZE);
  }

  const clear = () => update(DEFAULT_STATE);

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
      <form
        role="search"
        aria-label="Filter investigations"
        onSubmit={(e) => e.preventDefault()}
        className="mb-4 flex flex-wrap items-center gap-3"
      >
        <Input
          type="search"
          aria-label="Search investigations"
          placeholder="Search by title or ID"
          value={state.q}
          onChange={(e) => update({ q: e.target.value })}
          className="w-full sm:w-64"
        />
        <div className="flex items-center gap-2 text-sm">
          <Label htmlFor="filter-project" className="text-muted-foreground">
            Project
          </Label>
          <select
            id="filter-project"
            className={selectClass}
            value={state.project}
            onChange={(e) => update({ project: e.target.value })}
          >
            <option value="">All projects</option>
            {projects.data?.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        </div>
        <div className="flex items-center gap-2 text-sm">
          <Label htmlFor="filter-result" className="text-muted-foreground">
            Result
          </Label>
          <select
            id="filter-result"
            className={selectClass}
            value={state.result}
            onChange={(e) => update({ result: e.target.value as ListState["result"] })}
          >
            <option value="">Any</option>
            <option value="running">No outcome yet</option>
            {(Object.keys(OUTCOME_INFO) as Outcome[]).map((o) => (
              <option key={o} value={o}>
                {OUTCOME_INFO[o].label}
              </option>
            ))}
          </select>
        </div>
        <div className="flex items-center gap-2 text-sm">
          <Label htmlFor="filter-sort" className="text-muted-foreground">
            Sort
          </Label>
          <select
            id="filter-sort"
            className={selectClass}
            value={state.sort}
            onChange={(e) => update({ sort: e.target.value as SortKey })}
          >
            {(Object.keys(SORT_LABEL) as SortKey[]).map((s) => (
              <option key={s} value={s}>
                {SORT_LABEL[s]}
              </option>
            ))}
          </select>
        </div>
        {filtersActive && (
          <Button type="button" variant="ghost" size="sm" onClick={clear}>
            Clear filters
          </Button>
        )}
      </form>

      {items.error && <ErrorAlert error={items.error} title="Could not load investigations" />}
      {items.loading && !items.data && <LoadingRows rows={5} />}
      {items.data &&
        (visible.length === 0 ? (
          <EmptyState
            icon={SearchCode}
            title={all.length === 0 ? "No investigations yet" : "Nothing matches these filters"}
            action={
              all.length === 0 ? (
                <Link href="/investigations/new" className={buttonVariants()}>
                  Start an investigation
                </Link>
              ) : (
                <Button type="button" variant="outline" onClick={clear}>
                  Clear filters
                </Button>
              )
            }
          />
        ) : (
          <div className="space-y-3">
            <p className="text-sm text-muted-foreground">{summary}</p>
            <div ref={table}>
              <InvestigationsTable items={shown} projects={projects.data} />
            </div>
            {remaining > 0 && (
              <div className="flex justify-center">
                <Button type="button" variant="outline" onClick={showMore}>
                  Show {Math.min(PAGE_SIZE, remaining)} more
                </Button>
              </div>
            )}
          </div>
        ))}
    </>
  );
}
