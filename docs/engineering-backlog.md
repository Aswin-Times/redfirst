# Engineering backlog

Updated: 2026-11-18

## Next daily run

1. Make the unfinished-investigation cap robust under concurrent creation requests. The current count-then-insert sequence can exceed the configured limit; add a deterministic concurrency regression test before changing persistence behavior.
2. Make the frontend typecheck self-contained on a fresh checkout by generating Next.js route types as part of the typecheck command. Preserve the existing strict TypeScript check and add CI coverage if appropriate.

## Production readiness

- Run the Docker sandbox suite in CI or another Docker-enabled environment; 18 Docker tests remained skipped locally.
- Exercise migrations, worker claiming, leases, and concurrent transitions against PostgreSQL.
- Add authentication before exposing either server beyond loopback.
- Move result collection outside the untrusted test process to close the documented consistent-report-forgery gap.
- Exercise the Anthropic adapter against the live API and measure generation quality on real bug reports.
- Generate frontend API types from the backend OpenAPI schema instead of maintaining mirrors manually.
- Reduce the non-failing jsdom canvas warning emitted by the axe accessibility tests.

## Completed in the latest run

- Retention now collects JUnit and evidence artifact references and preserves them while still shared.
- Concurrent uploads of identical content use independent temporary files and tolerate competing publication of the same digest.
- The sample archive test now handles Git's CRLF conversion on Windows.
