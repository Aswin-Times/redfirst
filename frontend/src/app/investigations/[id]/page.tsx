import type { Metadata } from "next";
import { Suspense } from "react";

import { LoadingRows } from "@/components/feedback";
import { InvestigationWorkspace } from "@/components/pages/investigation-workspace";

export const metadata: Metadata = { title: "Investigation" };

// The id is runtime data under Cache Components, so it is read inside a Suspense boundary.
export default function Page() {
  return (
    <Suspense fallback={<LoadingRows rows={6} />}>
      <InvestigationWorkspace />
    </Suspense>
  );
}
