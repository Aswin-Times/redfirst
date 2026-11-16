"use client";

import { Check, Copy } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";

/** Icon button that copies `value`; announces "Copied" to screen readers as well. */
export function CopyButton({ value, label }: { value: string; label: string }) {
  const [copied, setCopied] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined);
  useEffect(() => () => clearTimeout(timer.current), []);

  async function copy() {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      clearTimeout(timer.current);
      timer.current = setTimeout(() => setCopied(false), 1500);
    } catch {
      setCopied(false); // clipboard blocked (e.g. insecure context): leave the button as-is
    }
  }

  return (
    <Button
      type="button"
      variant="ghost"
      size="icon-xs"
      onClick={copy}
      aria-label={label}
      title={copied ? "Copied" : label}
    >
      {copied ? <Check aria-hidden /> : <Copy aria-hidden />}
      <span role="status" className="sr-only">
        {copied ? "Copied" : ""}
      </span>
    </Button>
  );
}
