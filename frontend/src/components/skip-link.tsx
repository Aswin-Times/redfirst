/** First focusable element on every page: lets keyboard users jump past the header. */
export function SkipLink() {
  return (
    <a
      href="#main"
      className="sr-only rounded-md bg-primary px-3 py-2 text-sm font-medium text-primary-foreground focus:not-sr-only focus:fixed focus:top-3 focus:left-4 focus:z-50 focus-visible:ring-2 focus-visible:ring-ring/50 focus:outline-none"
    >
      Skip to content
    </a>
  );
}
