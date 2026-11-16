import Link from "next/link";
import { Plus } from "lucide-react";
import { Suspense } from "react";

import { Logo } from "@/components/logo";
import { NavLinks } from "@/components/nav-links";
import { ThemeToggle } from "@/components/theme-toggle";
import { buttonVariants } from "@/components/ui/button";

export function AppHeader() {
  return (
    <header className="sticky top-0 z-40 border-b bg-background/85 backdrop-blur">
      {/* Two rows on phones (brand and actions, then the full-width nav) so no link is ever
          squeezed or hidden; one row from `sm` up. */}
      <div className="mx-auto flex w-full max-w-6xl flex-wrap items-center gap-x-3 gap-y-1 px-4 py-2 sm:h-14 sm:flex-nowrap sm:gap-6 sm:px-6 sm:py-0">
        <Link
          href="/"
          aria-label="REDFIRST dashboard"
          className="order-1 shrink-0 rounded-md outline-none focus-visible:ring-2 focus-visible:ring-ring/50"
        >
          <Logo />
        </Link>
        <div className="order-2 ml-auto flex items-center gap-2 sm:order-3 sm:ml-0 sm:gap-3">
          <ThemeToggle />
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
        <Suspense fallback={<nav className="order-3 basis-full sm:order-2 sm:basis-auto sm:flex-1" />}>
          <NavLinks className="order-3 basis-full sm:order-2 sm:basis-auto sm:flex-1" />
        </Suspense>
      </div>
    </header>
  );
}
