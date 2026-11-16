"use client";

import { useEffect } from "react";

/** Set the tab title after the data it depends on has loaded. Next sets the next page's own. */
export function useDocumentTitle(title: string): void {
  useEffect(() => {
    document.title = `${title} · REDFIRST`;
  }, [title]);
}
