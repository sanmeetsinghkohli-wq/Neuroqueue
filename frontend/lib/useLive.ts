"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError } from "./api";
import { useEvents } from "./realtime";

/**
 * Fetch once, then refetch whenever the server pushes one of `events`.
 * Bursts (a whole queue being classified) collapse into one refetch.
 */
export function useLive<T>(path: string, events: string[]) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const load = useCallback(() => api<T>(path).then((r) => { setData(r); setError(null); }).catch(setError), [path]);
  useEffect(() => { load(); return () => { if (timer.current) clearTimeout(timer.current); }; }, [load]);
  useEvents((m) => {
    if (!events.includes(m.type) && m.type !== "connected") return;
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(load, 350);
  });
  return { data, error, reload: load };
}
