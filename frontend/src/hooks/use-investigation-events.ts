"use client";

import { useEffect, useEffectEvent, useState } from "react";

import type { StateEvent } from "@/lib/types";

export type StreamStatus = "connecting" | "open" | "closed" | "error";

/**
 * Subscribe to the investigation's Server-Sent Events stream. Calls ``onEvent`` for each
 * persisted state change; the server ends the stream once the investigation is terminal.
 * EventSource reconnects on its own and resends Last-Event-ID, so no event is lost.
 */
export function useInvestigationEvents(
  id: string,
  enabled: boolean,
  onEvent: (event: StateEvent) => void,
): StreamStatus {
  const [stream, setStream] = useState<{ id: string; status: StreamStatus }>();
  const handle = useEffectEvent(onEvent);

  useEffect(() => {
    if (!enabled) return;
    const source = new EventSource(`/api/investigations/${id}/events`);
    source.onopen = () => setStream({ id, status: "open" });
    source.addEventListener("state", (e) => {
      try {
        handle(JSON.parse((e as MessageEvent).data) as StateEvent);
      } catch {
        // A malformed event is ignored; the next refresh of the report is authoritative.
      }
    });
    source.addEventListener("end", () => {
      source.close();
      setStream({ id, status: "closed" });
    });
    source.onerror = () =>
      setStream({ id, status: source.readyState === EventSource.CLOSED ? "error" : "connecting" });
    return () => source.close();
  }, [id, enabled]);

  if (!enabled) return "closed";
  return stream?.id === id ? stream.status : "connecting";
}
