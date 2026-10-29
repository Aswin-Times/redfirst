"use client";

import Link from "next/link";
import { FolderGit2, SearchCode } from "lucide-react";

import { EmptyState, ErrorAlert, LoadingRows, PageHeader } from "@/components/feedback";
import { InvestigationsTable } from "@/components/investigations-table";
import { buttonVariants } from "@/components/ui/button";
import { useResource } from "@/hooks/use-resource";
import { api } from "@/lib/api";
import { OUTCOME_INFO } from "@/lib/outcome";
import { OUTCOMES, summarize } from "@/lib/summary";
import type { InvestigationSummary } from "@/lib/types";

export function Dashboard() {
  const data = useResource(
    async () => {
      const [projects, investigations] = await Promise.all([api.projects(), api.investigations()]);
      return { projects, investigations };
    },
    [],
  );

  return (
    <>
      <PageHeader
        title="Dashboard"
        description="Recent bug investigations and their verified outcomes."
      />
      {data.error && <ErrorAlert error={data.error} title="Could not load the dashboard" />}
      {data.loading && !data.data && <LoadingRows rows={4} />}
      {data.data && <DashboardBody {...data.data} />}
    </>
  );
}

function DashboardBody({
  projects,
  investigations,
}: {
  projects: Awaited<ReturnType<typeof api.projects>>;
  investigations: InvestigationSummary[];
}) {
  if (projects.length === 0) {
    return (
      <EmptyState
        icon={FolderGit2}
        title="No projects yet"
        action={
          <Link href="/projects" className={buttonVariants()}>
            Create a project
          </Link>
        }
      >
        Create a project and upload a Python repository archive to start investigating bugs.
      </EmptyState>
    );
  }

  const { counts, active } = summarize(investigations);
  return (
    <div className="space-y-6">
      <dl className="grid grid-cols-2 gap-px overflow-hidden rounded-lg border bg-border sm:grid-cols-3 lg:grid-cols-6">
        <Stat label="Projects" value={projects.length} />
        <Stat label="In progress" value={active} />
        {OUTCOMES.map((o) => (
          <Stat key={o} label={OUTCOME_INFO[o].label} value={counts[o]} />
        ))}
      </dl>
      <p className="-mt-4 text-xs text-muted-foreground">
        Counts cover the {investigations.length} most recent investigations
        {investigations.length === 200 ? " (the API returns at most 200)" : ""}.
      </p>

      <section>
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-sm font-medium">Recent investigations</h2>
          {investigations.length > 0 && (
            <Link href="/investigations" className="text-sm text-muted-foreground hover:underline">
              View all
            </Link>
          )}
        </div>
        {investigations.length === 0 ? (
          <EmptyState
            icon={SearchCode}
            title="No investigations yet"
            action={
              <Link href="/investigations/new" className={buttonVariants()}>
                Start an investigation
              </Link>
            }
          >
            Describe a bug and choose a repository; REDFIRST will try to reproduce it.
          </EmptyState>
        ) : (
          <InvestigationsTable items={investigations.slice(0, 8)} projects={projects} />
        )}
      </section>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <div className="bg-background px-4 py-3">
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="mt-1 text-2xl font-semibold tabular-nums">{value}</dd>
    </div>
  );
}
