"use client";

import { Square } from "lucide-react";
import { useRef, useState } from "react";

import {
  AlertDialog,
  AlertDialogClose,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";

/** Cancelling cannot be undone, so it asks first, with the safe choice focused. */
export function CancelInvestigation({
  onConfirm,
  busy,
}: {
  onConfirm: () => void;
  busy: boolean;
}) {
  const [open, setOpen] = useState(false);
  const keepRef = useRef<HTMLButtonElement>(null);
  return (
    <AlertDialog open={open} onOpenChange={setOpen}>
      <AlertDialogTrigger render={<Button variant="outline" size="sm" disabled={busy} />}>
        <Square data-icon="inline-start" aria-hidden />
        {busy ? "Cancelling…" : "Cancel"}
      </AlertDialogTrigger>
      <AlertDialogContent initialFocus={keepRef}>
        <div className="grid gap-1.5">
          <AlertDialogTitle>Cancel this investigation?</AlertDialogTitle>
          <AlertDialogDescription>
            It stops now and cannot be resumed. What it has produced so far stays in the report.
          </AlertDialogDescription>
        </div>
        <div className="flex flex-wrap justify-end gap-2">
          <AlertDialogClose render={<Button ref={keepRef} variant="outline" />}>
            Keep running
          </AlertDialogClose>
          <Button
            variant="destructive"
            onClick={() => {
              setOpen(false);
              onConfirm();
            }}
          >
            Cancel investigation
          </Button>
        </div>
      </AlertDialogContent>
    </AlertDialog>
  );
}
