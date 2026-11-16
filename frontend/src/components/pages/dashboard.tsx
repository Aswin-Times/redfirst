"use client";

import Link from "next/link";
import { SearchCode } from "lucide-react";

import { ActivityChart } from "@/components/activity-chart";
import { EmptyState, ErrorAlert, PageHeader } from "@/components/feedback";
import { FirstRun } from "@/components/first-run";
import { InvestigationsTable } from "@/components/investigations-table";
import { NeedsAttention } from "@/components/needs-attention";
import { OutcomeBar } from "@/components/outcome-bar";
import { buttonVariants } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useResource } from "@/hooks/use-resource";
import { api } from "@/lib/api";
import { dailyCounts, headline, needsAttention, outcomeShares } from "@/lib/dashboard";
import { summarize } from "@/lib/summary";
import type { InvestigationSummary } from "@/lib/types";

const API_LIMIT = 200;

export function Dashboard() {
  const data = useResource(
    async () => {
      const [projects, investigations] = await Promise.all([api.projects(), api.investigations()]);
      return { projects, investigations };
    },
    [],
  );

  const body = data.data;
  const { counts, active } = summarize(body?.investigations ?? []);
  return (
    <>
      <PageHeader
        title="Dashboard"
        description={
          body && body.projects.length > 0
            ? headline(counts, active, body.investigations.length)
            : "Bug investigations and their verified outcomes."
        }
      />
      {data.error && <ErrorAlert error={data.error} title="Could not load the dashboard" />}
      {data.loading && !body && <DashboardSkeleton />}
      {body && <DashboardBody projects={body.projects} investigations={body.investigations} />}
    </>
  );
}

function DashboardSkeleton() {
  return (
    <div aria-busy="true" aria-label="Loading" className="space-y-6">
      <div className="grid gap-4 lg:grid-cols-3">
        <Skeleton className="h-40 rounded-xl lg:col-span-2" />
        <Skeleton className="h-40 rounded-xl" />
      </div>
      <Skeleton className="h-64 rounded-xl" />
    </div>
  );
}

function DashboardBody({
  projects,
  investigations,
}: {
  projects: Awaited<ReturnType<typeof api.projects>>;
  investigations: InvestigationSummary[];
}) {
  if (projects.length === 0) return <FirstRun />;

  const { counts } = summarize(investigations);
  const attention = needsAttention(investigations);
  return (
    <div className="space-y-6">
      <div className="grid gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle>Outcomes</CardTitle>
            <CardDescription>
              Covers the {investigations.length} most recent investigations
              {investigations.length === API_LIMIT ? " (the API returns at most 200)" : ""}.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <OutcomeBar shares={outcomeShares(counts)} />
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Activity</CardTitle>
            <CardDescription>Investigations started per day</CardDescription>
          </CardHeader>
          <CardContent>
            <ActivityChart days={dailyCounts(investigations)} />
          </CardContent>
        </Card>
      </div>

      <NeedsAttention items={attention} />

      <section>
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-sm font-medium">Recent investigations</h2>
          {investigations.length > 0 && (
            <Link
              href="/investigations"
              className="inline-flex min-h-6 items-center rounded-sm px-1 text-sm text-muted-foreground outline-none hover:underline focus-visible:ring-2 focus-visible:ring-ring/50"
            >
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
