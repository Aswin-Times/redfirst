import { cn } from "@/lib/utils";

/**
 * The mark is a red test that has just failed: the first red of "red first". Red is reserved
 * for this mark and for what red means in the product (a confirmed bug, an error).
 */
export function LogoMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden className={cn("size-5", className)}>
      <rect width="24" height="24" rx="6" className="fill-brand" />
      <path
        d="M8 8l8 8M16 8l-8 8"
        className="stroke-white"
        strokeWidth="2.4"
        strokeLinecap="round"
        fill="none"
      />
    </svg>
  );
}

export function Logo({ className }: { className?: string }) {
  return (
    <span className={cn("inline-flex items-center gap-2", className)}>
      <LogoMark />
      <span className="font-mono text-sm font-semibold tracking-tight">
        <span className="text-brand">RED</span>FIRST
      </span>
    </span>
  );
}
