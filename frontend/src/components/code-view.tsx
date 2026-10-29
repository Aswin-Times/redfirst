"use client";

import { Check, Copy } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";

/** Read-only code with line numbers. No syntax highlighting, by design: zero dependencies. */
export function CodeView({ code, label }: { code: string; label: string }) {
  const [copied, setCopied] = useState(false);
  const lines = code.replace(/\n$/, "").split("\n");

  async function copy() {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      setCopied(false); // clipboard blocked (e.g. insecure context): leave the button as-is
    }
  }

  return (
    <div className="overflow-hidden rounded-lg border">
      <div className="flex items-center justify-between border-b bg-muted/50 px-3 py-1.5">
        <span className="font-mono text-xs text-muted-foreground">{label}</span>
        <Button variant="ghost" size="xs" onClick={copy} aria-label="Copy code">
          {copied ? <Check data-icon="inline-start" /> : <Copy data-icon="inline-start" />}
          {copied ? "Copied" : "Copy"}
        </Button>
      </div>
      <pre className="overflow-x-auto py-3 font-mono text-[13px] leading-5">
        <code>
          {lines.map((line, i) => (
            <div key={i} className="flex">
              <span
                aria-hidden
                className="w-10 shrink-0 select-none pr-3 text-right text-muted-foreground/60"
              >
                {i + 1}
              </span>
              <span className="pr-4 whitespace-pre">{line || " "}</span>
            </div>
          ))}
        </code>
      </pre>
    </div>
  );
}

/** Captured process output: preserves whitespace, scrolls instead of growing forever. */
export function LogView({ text, empty = "No output captured." }: { text: string; empty?: string }) {
  if (!text.trim()) return <p className="text-sm text-muted-foreground">{empty}</p>;
  return (
    <pre className="max-h-80 overflow-auto rounded-md border bg-muted/40 p-3 font-mono text-xs leading-5 whitespace-pre-wrap break-words">
      {text}
    </pre>
  );
}
