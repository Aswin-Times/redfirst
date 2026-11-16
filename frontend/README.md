# REDFIRST frontend

Next.js 16 (App Router, Cache Components), TypeScript, Tailwind CSS 4, shadcn/ui (Base UI) and
lucide icons. All data comes from the FastAPI backend; nothing on screen is invented.

```bash
pnpm install
pnpm dev          # http://localhost:3000 (loopback only), proxies /api/* to REDFIRST_BACKEND_URL
pnpm typecheck
pnpm lint
pnpm test         # Vitest + Testing Library
pnpm build
```

`REDFIRST_BACKEND_URL` defaults to `http://127.0.0.1:8000`. Put overrides in `.env.local`
(git-ignored). The backend address is only used by the server-side rewrite in
`next.config.ts`; the browser only ever talks to this app.

`dev` and `start` listen on `127.0.0.1` only. The backend has no authentication and this app
proxies every `/api/*` request to it, so do not remove `--hostname 127.0.0.1` without adding
authentication first.

## Structure

```
src/app/                    routes: /, /investigations, /investigations/new,
                            /investigations/[id], /projects
src/components/pages/       client components holding each page's data and state
src/components/             shared UI (verdict banner, evidence summary, stage stepper, export
                            menu, outcome bar, activity chart, theme toggle, logo, code/log views)
src/components/ui/          shadcn/ui primitives (generated; edit sparingly)
src/hooks/                  useResource (fetch + refresh), useInvestigationEvents (SSE)
src/lib/                    API client, types mirroring the backend, stage/outcome logic
```

### Brand and theme

Red is reserved: it is the colour of the logo mark and of what red means in the product (a
confirmed bug, an error). Everything else is ink on warm neutrals, so a red badge always means
something. Light, System and Dark are chosen with the header toggle (`lib/theme.ts`): the choice
is kept in `localStorage` and applied as a `dark` class on `<html>`; a small inline script in
`layout.tsx` applies it before first paint so there is no flash. Check any new colour token for
4.5:1 contrast in both themes.

### The dashboard

`lib/dashboard.ts` holds the pure parts (outcome percentages that add up to 100, 14-day buckets by
local day, relative times, the headline sentence, the `?result=` filter value) and is unit
tested. Charts are plain divs with text alternatives; there is no chart library. Counts cover the
API's 200 most recent investigations, and the page says so.

### Accessibility

`src/a11y.test.tsx` renders every page and each investigation state with a mocked API and fails
on any axe-core violation (a dev-only dependency). jsdom has no layout, so colour contrast is
switched off there and is measured against the running app instead (4.5:1 in both themes, see
Brand and theme). Things worth keeping:

- One live region per concern. The verdict banner's hidden region changes with the stage and the
  result, never with the timer; `useAnnounce()` is for outcomes that are otherwise only visual.
- No interactive element inside `role="img"`, and no single-character keyboard shortcuts
  (WCAG 2.1.4). Ctrl/Cmd+Enter submits the new-investigation form.
- Targets are at least 24 px; table rows use a stretched link; column headers are `scope="col"`.
- Page titles come from the route; investigations use `investigationTitle()` so tabs read
  "Reproduced: <bug> · REDFIRST". The layout's title template skips a page in its own segment.
- Real screen readers have not been used on this app; automated checks cannot replace that.

### The new-investigation page

`lib/report-form.ts` holds the form's pure logic: field limits (mirrored from
`backend/redfirst/analysis/report.py`; `report-form.test.ts` reads that file and fails if they
drift), validation messages, the reason the Start button is disabled, the "What REDFIRST will
use" checklist and tolerant draft parsing. Every checklist line states a real consequence of how
results are decided; do not add a score. Drafts live in `localStorage` (guarded, like the theme).

"Try a sample bug" uses `public/samples/accounts-demo.zip`, a stored zip of the planted-bug
fixture. Rebuild it with `python frontend/scripts/make-sample.py` from the repository root; a
test checks that it holds exactly the fixture's files and that the sample report describes the
bug that is really in the code. Clicking the button creates (or reuses) a "Sample project" in the
database; it never calls the model, only Start does.

### The investigation page

The verdict leads: `VerdictBanner` shows the outcome, its reason in plain words, a caveat that
matters for that outcome (a reproduction must still be read by a person; "not reproduced" never
proves the bug is absent) and key facts taken only from the report (runs that agreed,
attempts, kind of evidence, time taken). While the investigation runs it shows progress with
a live timer instead.

`lib/evidence.ts` parses the verdict's evidence strings, which are the API's only evidence
format, into the failure, where it happened (repository-relative paths) and the exit code the
runner observed. Lines it does not recognise are kept and shown, and the original lines stay one
click away under "Raw evidence", so a change to the backend's wording makes the page plainer but
never hides evidence. Moving this into the API as structured data would be the cleaner fix.

The API sends UTC timestamps without a zone suffix; always parse them with `parseTimestamp`
(`lib/outcome.ts`), never `new Date(iso)`, or times are wrong by the viewer's UTC offset.

Data is fetched in the browser with inline loading states. The investigation workspace
subscribes to `/api/investigations/{id}/events` (Server-Sent Events) and refetches the report
on every persisted state change.

## Notes

- `src/lib/types.ts` is hand-written to mirror the backend schemas; keep it in sync.
- `jsdom` is pinned to 26 because newer releases need Node 20.19+ / 22.12+.
- `@rolldown/binding-win32-x64-msvc` is an optional dependency: pnpm did not install Vitest's
  native Windows binding on its own on the development machine. Adding or removing any package
  can prune it again (Vitest then fails with "Cannot find native binding"); `pnpm install --force`
  restores it.
