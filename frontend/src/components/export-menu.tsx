"use client";

import { ChevronDown, Download, FileCode2, FileJson, FileText } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuLinkItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { exportUrls } from "@/lib/api";

/** The three downloads for one investigation, in one place. */
export function ExportMenu({ id, hasTest }: { id: string; hasTest: boolean }) {
  const urls = exportUrls(id);
  return (
    <DropdownMenu>
      <DropdownMenuTrigger render={<Button variant="outline" size="sm" />}>
        <Download data-icon="inline-start" aria-hidden />
        Export
        <ChevronDown data-icon="inline-end" aria-hidden />
      </DropdownMenuTrigger>
      <DropdownMenuContent>
        {hasTest && (
          <DropdownMenuLinkItem href={urls.test}>
            <FileCode2 aria-hidden /> Test file (.py)
          </DropdownMenuLinkItem>
        )}
        <DropdownMenuLinkItem href={urls.markdown}>
          <FileText aria-hidden /> Report (Markdown)
        </DropdownMenuLinkItem>
        <DropdownMenuLinkItem href={urls.json}>
          <FileJson aria-hidden /> Report (JSON)
        </DropdownMenuLinkItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
