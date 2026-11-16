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
src/components/             shared UI (verdict banner, evidence summary, stage stepper,
                            export menu, status badge, code/log views)
src/components/ui/          shadcn/ui primitives (generated; edit sparingly)
src/hooks/                  useResource (fetch + refresh), useInvestigationEvents (SSE)
src/lib/                    API client, types mirroring the backend, stage/outcome logic
```

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
  native Windows binding on its own on the development machine.
