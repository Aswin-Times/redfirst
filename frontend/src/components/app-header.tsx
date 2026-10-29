import Link from "next/link";
import { Plus } from "lucide-react";
import { Suspense } from "react";

import { NavLinks } from "@/components/nav-links";
import { buttonVariants } from "@/components/ui/button";

export function AppHeader() {
  return (
    <header className="border-b">
      <div className="mx-auto flex h-14 w-full max-w-6xl items-center gap-3 px-4 sm:gap-6 sm:px-6">
        <Link
          href="/"
          aria-label="REDFIRST dashboard"
          className="font-mono text-sm font-semibold tracking-tight"
        >
          <span className="text-destructive">RED</span>FIRST
        </Link>
        <Suspense fallback={<nav className="min-w-0 flex-1" />}>
          <NavLinks />
        </Suspense>
        <Link
          href="/investigations/new"
          aria-label="New investigation"
          className={buttonVariants({ size: "sm" })}
        >
          <Plus data-icon="inline-start" aria-hidden />
          <span className="hidden sm:inline">New investigation</span>
          <span className="sm:hidden">New</span>
        </Link>
      </div>
    </header>
  );
}
