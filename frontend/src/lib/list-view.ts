import { resultParam } from "@/lib/dashboard";
import { parseTimestamp } from "@/lib/outcome";
import { OUTCOMES } from "@/lib/summary";
import type { InvestigationSummary, Outcome } from "@/lib/types";

export const PAGE_SIZE = 25;
const MAX_QUERY = 100;

export type SortKey = "newest" | "oldest" | "result";

export interface ListState {
  project: string;
  result: "" | Outcome | "running";
  q: string;
  sort: SortKey;
}

export const DEFAULT_STATE: ListState = { project: "", result: "", q: "", sort: "newest" };

const SORTS: SortKey[] = ["newest", "oldest", "result"];

/** The list's filters as kept in the URL, so a filtered view can be shared and survives a reload. */
export function parseListParams(params: URLSearchParams): ListState {
  const sort = params.get("sort") as SortKey;
  return {
    project: params.get("project") ?? "",
    result: resultParam(params.get("result")),
    q: (params.get("q") ?? "").trim().slice(0, MAX_QUERY),
    sort: SORTS.includes(sort) ? sort : DEFAULT_STATE.sort,
  };
}

/** The query string for a state; empty when everything is at its default. */
export function toQuery(state: ListState): string {
  const params = new URLSearchParams();
  if (state.project) params.set("project", state.project);
  if (state.result) params.set("result", state.result);
  if (state.q.trim()) params.set("q", state.q.trim());
  if (state.sort !== DEFAULT_STATE.sort) params.set("sort", state.sort);
  const text = params.toString();
  return text ? `?${text}` : "";
}

/** Title contains the text (any case), or the id starts with it (people paste ids). */
export function matchesQuery(item: Pick<InvestigationSummary, "title" | "id">, q: string): boolean {
  const needle = q.trim().toLowerCase();
  if (!needle) return true;
  return item.title.toLowerCase().includes(needle) || item.id.toLowerCase().startsWith(needle);
}

const created = (i: InvestigationSummary) => parseTimestamp(i.created_at);

const resultRank = (i: InvestigationSummary) => (i.outcome ? OUTCOMES.indexOf(i.outcome) : OUTCOMES.length);

export function sortItems(items: InvestigationSummary[], sort: SortKey): InvestigationSummary[] {
  const copy = [...items];
  if (sort === "oldest") return copy.sort((a, b) => created(a) - created(b));
  if (sort === "result") {
    return copy.sort((a, b) => resultRank(a) - resultRank(b) || created(b) - created(a));
  }
  return copy.sort((a, b) => created(b) - created(a));
}

/** Filter by result and search text, then sort. (The project filter is applied by the API.) */
export function applyView(items: InvestigationSummary[], state: ListState): InvestigationSummary[] {
  const visible = items.filter((i) => {
    if (state.result === "running" && i.outcome !== null) return false;
    if (state.result && state.result !== "running" && i.outcome !== state.result) return false;
    return matchesQuery(i, state.q);
  });
  return sortItems(visible, state.sort);
}
