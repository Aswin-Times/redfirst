import Link from "next/link";

import { StatusBadge } from "@/components/status-badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { relativeTime } from "@/lib/dashboard";
import { formatDate, humanize } from "@/lib/outcome";
import type { InvestigationSummary, Project } from "@/lib/types";

export function InvestigationsTable({
  items,
  projects,
}: {
  items: InvestigationSummary[];
  projects?: Project[];
}) {
  const projectName = new Map(projects?.map((p) => [p.id, p.name]));
  return (
    <div className="overflow-x-auto rounded-lg border">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Bug</TableHead>
            {projects && <TableHead className="hidden md:table-cell">Project</TableHead>}
            <TableHead>Result</TableHead>
            <TableHead className="hidden sm:table-cell">Reason</TableHead>
            <TableHead className="hidden lg:table-cell">Created</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {items.map((inv) => (
            <TableRow key={inv.id}>
              <TableCell className="max-w-72">
                <Link
                  href={`/investigations/${inv.id}`}
                  className="block truncate font-medium hover:underline"
                >
                  {inv.title}
                </Link>
                <span className="font-mono text-xs text-muted-foreground">{inv.id.slice(0, 8)}</span>
              </TableCell>
              {projects && (
                <TableCell className="hidden text-muted-foreground md:table-cell">
                  {projectName.get(inv.project_id) ?? "–"}
                </TableCell>
              )}
              <TableCell>
                <StatusBadge state={inv.state} outcome={inv.outcome} />
              </TableCell>
              <TableCell className="hidden text-muted-foreground sm:table-cell">
                {inv.outcome_reason ? humanize(inv.outcome_reason) : "–"}
              </TableCell>
              <TableCell className="hidden text-muted-foreground lg:table-cell">
                <time dateTime={inv.created_at} title={formatDate(inv.created_at)}>
                  {relativeTime(inv.created_at)}
                </time>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
