import type { Metadata } from "next";

import { NewInvestigation } from "@/components/pages/new-investigation";

export const metadata: Metadata = { title: "New investigation" };

export default function Page() {
  return <NewInvestigation />;
}
