import type { Metadata } from "next";

import { InvestigationHistory } from "@/components/pages/investigation-history";

export const metadata: Metadata = { title: "Investigations" };

export default function Page() {
  return <InvestigationHistory />;
}
