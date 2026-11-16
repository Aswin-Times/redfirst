import type { Metadata } from "next";

import { Dashboard } from "@/components/pages/dashboard";

// The layout's title template does not apply to a page in the same segment, so spell it out.
export const metadata: Metadata = { title: { absolute: "Dashboard · REDFIRST" } };

export default function Page() {
  return <Dashboard />;
}
