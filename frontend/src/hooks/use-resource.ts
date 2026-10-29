"use client";

import { useCallback, useEffect, useRef, useState } from "react";

export interface Resource<T> {
  data: T | undefined;
  error: Error | undefined;
  loading: boolean;
  refresh: () => Promise<void>;
}

interface Result<T> {
  key: string;
  data?: T;
  error?: Error;
}

/**
 * Fetch when ``deps`` change; expose ``refresh`` for mutations and live updates.
 * Results are keyed by deps, so data from a previous key is never shown as current,
 * and a late response for an old key or an older request is discarded.
 */
export function useResource<T>(load: () => Promise<T>, deps: unknown[]): Resource<T> {
  const key = JSON.stringify(deps);
  const [result, setResult] = useState<Result<T>>();
  const loadRef = useRef(load);
  const generation = useRef(0);

  useEffect(() => {
    loadRef.current = load;
  });

  const run = useCallback((forKey: string) => {
    const current = ++generation.current;
    return loadRef.current().then(
      (data) => {
        if (current === generation.current) setResult({ key: forKey, data });
      },
      (error: Error) => {
        if (current === generation.current)
          setResult((prev) => ({ key: forKey, data: prev?.key === forKey ? prev.data : undefined, error }));
      },
    );
  }, []);

  useEffect(() => {
    void run(key);
  }, [key, run]);

  const refresh = useCallback(() => run(key), [run, key]);
  const fresh = result?.key === key;
  return {
    data: fresh ? result.data : undefined,
    error: fresh ? result.error : undefined,
    loading: !fresh,
    refresh,
  };
}
