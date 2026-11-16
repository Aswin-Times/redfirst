"use client";

import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";

type Announce = (message: string) => void;

const AnnounceContext = createContext<Announce>(() => {});

/** Say something to screen reader users when its effect is already visible on screen. */
export const useAnnounce = (): Announce => useContext(AnnounceContext);

/**
 * One polite, visually hidden live region for the whole app. A repeated message gets a trailing
 * space on alternate calls so the region's text changes and is read again.
 */
export function AnnouncerProvider({ children }: { children: ReactNode }) {
  const [text, setText] = useState("");
  const announce = useCallback<Announce>((message) => {
    setText((prev) => (prev.trim() === message ? `${message}${prev.endsWith(" ") ? "" : " "}` : message));
  }, []);
  const value = useMemo(() => announce, [announce]);
  return (
    <AnnounceContext.Provider value={value}>
      {children}
      <div role="status" aria-live="polite" className="sr-only">
        {text}
      </div>
    </AnnounceContext.Provider>
  );
}
