import type { Metadata } from "next";
import { Suspense } from "react";

import { LoadingRows } from "@/components/feedback";
import { InvestigationHistory } from "@/components/pages/investigation-history";

export const metadata: Metadata = { title: "Investigations" };

export default function Page() {
  // useSearchParams (the ?result= filter) needs a Suspense boundary in a prerendered route.
  return (
    <Suspense fallback={<LoadingRows rows={5} />}>
      <InvestigationHistory />
    </Suspense>
  );
}
