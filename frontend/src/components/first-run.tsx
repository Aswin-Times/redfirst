import Link from "next/link";

import { buttonVariants } from "@/components/ui/button";

const STEPS = [
  {
    title: "Create a project",
    text: "A project groups the repositories and bug reports you investigate together.",
    href: "/projects",
    cta: "Create a project",
  },
  {
    title: "Upload a repository",
    text: "A zip or tar archive of your Python code. It is opened safely and run offline in a sandbox.",
    href: "/projects",
    cta: "Upload code",
  },
  {
    title: "Describe a bug",
    text: "The more you say about expected and actual behavior, the stronger the result can be.",
    href: "/investigations/new",
    cta: "New investigation",
  },
];

/** Shown on the dashboard until the first project exists. */
export function FirstRun() {
  return (
    <section aria-labelledby="first-run-title" className="rounded-xl border bg-card p-5 sm:p-7">
      <h2 id="first-run-title" className="text-lg font-semibold tracking-tight">
        Reproduce your first bug
      </h2>
      <p className="mt-1 max-w-xl text-sm text-muted-foreground">
        REDFIRST turns a bug report into a failing test, runs it, and tells you what that does and
        does not prove. Three steps to get started:
      </p>
      <ol className="mt-6 grid gap-5 sm:grid-cols-3">
        {STEPS.map((s, i) => (
          <li key={s.title} className="flex flex-col gap-2">
            <span className="grid size-7 place-items-center rounded-full border font-mono text-xs tabular-nums">
              {i + 1}
            </span>
            <h3 className="text-sm font-medium">{s.title}</h3>
            <p className="flex-1 text-sm text-muted-foreground">{s.text}</p>
            <Link
              href={s.href}
              className={buttonVariants({ variant: i === 0 ? "default" : "outline", size: "sm" })}
            >
              {s.cta}
            </Link>
          </li>
        ))}
      </ol>
    </section>
  );
}
