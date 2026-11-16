import Link from "next/link";
import { ChevronRight } from "lucide-react";
import { Fragment } from "react";

export interface Crumb {
  label: string;
  href?: string;
}

/** Where you are: ancestors are links, the last item is the current page. */
export function Breadcrumbs({ items }: { items: Crumb[] }) {
  return (
    <nav aria-label="Breadcrumb" className="mb-3 text-sm">
      <ol className="flex min-w-0 items-center gap-1.5 text-muted-foreground">
        {items.map((item, i) => (
          <Fragment key={`${i}-${item.label}`}>
            {i > 0 && <ChevronRight className="size-3.5 shrink-0" aria-hidden />}
            <li className="flex min-w-0 items-center">
              {item.href ? (
                <Link
                  href={item.href}
                  className="inline-flex min-h-6 items-center rounded-sm px-0.5 underline-offset-4 outline-none hover:text-foreground hover:underline focus-visible:ring-2 focus-visible:ring-ring/50"
                >
                  {item.label}
                </Link>
              ) : (
                <span aria-current="page" title={item.label} className="truncate text-foreground">
                  {item.label}
                </span>
              )}
            </li>
          </Fragment>
        ))}
      </ol>
    </nav>
  );
}
