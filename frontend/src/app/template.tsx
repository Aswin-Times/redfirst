import type { ReactNode } from "react";

/** A template remounts on every navigation, so each page fades in (see .page-in in globals.css). */
export default function Template({ children }: { children: ReactNode }) {
  return <div className="page-in">{children}</div>;
}
