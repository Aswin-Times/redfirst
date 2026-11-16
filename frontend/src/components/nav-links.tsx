"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { cn } from "@/lib/utils";

const LINKS = [
  { href: "/", label: "Dashboard", match: (p: string) => p === "/" },
  {
    href: "/investigations",
    label: "Investigations",
    match: (p: string) => p.startsWith("/investigations") && p !== "/investigations/new",
  },
  { href: "/projects", label: "Projects", match: (p: string) => p.startsWith("/projects") },
];

export function NavLinks({ className }: { className?: string }) {
  const pathname = usePathname();
  return (
    <nav
      aria-label="Main"
      className={cn("flex min-w-0 items-center gap-1 overflow-x-auto text-sm [scrollbar-width:none]", className)}
    >
      {LINKS.map((l) => {
        const active = l.match(pathname);
        return (
          <Link
            key={l.href}
            href={l.href}
            aria-current={active ? "page" : undefined}
            className={cn(
              "shrink-0 rounded-md px-2.5 py-1.5 text-muted-foreground outline-none transition-colors hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring/50",
              active && "bg-muted text-foreground",
            )}
          >
            {l.label}
          </Link>
        );
      })}
    </nav>
  );
}
