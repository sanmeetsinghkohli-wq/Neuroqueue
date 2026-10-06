"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { api, ApiError, uid, WS_URL, type Scan } from "./api";
import { useAuth } from "./auth";

type Listener = (msg: any) => void;
interface Realtime {
  connected: boolean;
  subscribe: (fn: Listener) => () => void;
  send: (msg: object) => void;
}

const Ctx = createContext<Realtime | null>(null);

/** One WebSocket per signed-in session. The server pushes every change; nothing polls. */
export function RealtimeProvider({ children }: { children: React.ReactNode }) {
  const { user, refresh } = useAuth();
  const [connected, setConnected] = useState(false);
  const listeners = useRef(new Set<Listener>());
  const socket = useRef<WebSocket | null>(null);
  const userId = user?.id;

  useEffect(() => {
    if (!userId) return;
    let closed = false;
    let attempt = 0;
    let timer: ReturnType<typeof setTimeout>;
    let heartbeat: ReturnType<typeof setInterval>;

    const open = async () => {
      // A one-time, 30-second ticket fetched with the session cookie. The session token itself never goes in a URL.
      let ticket = "";
      try { ticket = (await api<{ ticket: string }>("/api/auth/ws-ticket", { method: "POST" })).ticket; } catch { /* retry below */ }
      if (closed) return;
      if (!ticket) { timer = setTimeout(open, Math.min(8000, 500 * 2 ** attempt++)); return; }
      const ws = new WebSocket(`${WS_URL}?ticket=${encodeURIComponent(ticket)}`);
      socket.current = ws;
      ws.onopen = () => {
        attempt = 0;
        setConnected(true);
        listeners.current.forEach((fn) => fn({ type: "connected" }));
        heartbeat = setInterval(() => ws.readyState === 1 && ws.send(JSON.stringify({ type: "ping" })), 25000);
      };
      ws.onmessage = (ev) => {
        const msg = JSON.parse(ev.data);
        if (msg.type === "user_updated" && msg.user?.id === userId) {
          // e.g. an admin just approved this doctor: unlock the portal without a reload
          refresh().then(() => ws.readyState === 1 && ws.send(JSON.stringify({ type: "refresh_user" })));
        }
        listeners.current.forEach((fn) => fn(msg));
      };
      ws.onclose = () => {
        clearInterval(heartbeat);
        setConnected(false);
        if (!closed) timer = setTimeout(open, Math.min(8000, 500 * 2 ** attempt++));
      };
    };
    open();
    return () => {
      closed = true;
      clearTimeout(timer);
      clearInterval(heartbeat);
      socket.current?.close();
    };
  }, [userId, refresh]);

  const value = useMemo<Realtime>(() => ({
    connected,
    subscribe(fn) {
      listeners.current.add(fn);
      return () => void listeners.current.delete(fn);
    },
    send(msg) {
      if (socket.current?.readyState === 1) socket.current.send(JSON.stringify(msg));
    },
  }), [connected]);

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useRealtime(): Realtime {
  const v = useContext(Ctx);
  if (!v) throw new Error("useRealtime must be used inside RealtimeProvider");
  return v;
}

/** Subscribe to server events for the lifetime of the component. */
export function useEvents(fn: Listener) {
  const { subscribe } = useRealtime();
  const ref = useRef(fn);
  ref.current = fn;
  useEffect(() => subscribe((m) => ref.current(m)), [subscribe]);
}

// ---------------- streamed jobs ----------------
export interface JobState<R = any> {
  id: string | null;
  status: "idle" | "running" | "done" | "failed";
  stage: string;
  pct: number;
  text: Record<string, string>;      // streamed tokens per section
  partials: any[];
  result: R | null;
  error: { code: string; message: string; hint?: string } | null;
}

const IDLE: JobState = { id: null, status: "idle", stage: "", pct: 0, text: {}, partials: [], result: null, error: null };

/**
 * Generic streamed job: job_started, job_progress, job_partial, job_token, job_done, job_failed.
 * The id is generated here so the listener is attached before the server emits anything.
 */
export function useJob<R = any>() {
  const { subscribe, send } = useRealtime();
  const [state, setState] = useState<JobState<R>>(IDLE);
  const idRef = useRef<string | null>(null);

  useEffect(() => subscribe((m) => {
    if (!m.job_id || m.job_id !== idRef.current) return;
    setState((s) => {
      switch (m.type) {
        case "job_progress": return { ...s, stage: m.stage, pct: m.pct };
        case "job_token": {
          const key = m.section ?? "main";
          return { ...s, text: { ...s.text, [key]: (s.text[key] ?? "") + m.text } };
        }
        case "job_partial":
          if (m.data?.reset) return { ...s, text: { ...s.text, [m.data.reset]: "" }, partials: [...s.partials, m.data] };
          return { ...s, partials: [...s.partials, m.data] };
        case "job_done": return { ...s, status: "done", pct: 100, result: m.result };
        case "job_failed": return { ...s, status: "failed", error: m.error };
        default: return s;
      }
    });
  }), [subscribe]);

  const start = useCallback(async (path: string, body: Record<string, unknown> = {}) => {
    const id = uid();
    idRef.current = id;
    setState({ ...IDLE, id, status: "running", stage: "starting" });
    try {
      await api(path, { body: { ...body, job_id: id } });
    } catch (e) {
      const err = e as ApiError;
      setState((s) => ({ ...s, status: "failed", error: { code: err.code, message: err.message, hint: err.hint } }));
    }
    return id;
  }, []);

  const cancel = useCallback(() => idRef.current && send({ type: "cancel_job", job_id: idRef.current }), [send]);
  const reset = useCallback(() => { idRef.current = null; setState(IDLE); }, []);
  return { ...state, start, cancel, reset };
}

// ---------------- live queue ----------------
export interface QueueMeta { thresholds: Record<string, any>; reason_text: Record<string, string> }

/** The worklist, kept in sync by scan_updated / scan_removed events. */
export function useLiveQueue() {
  const { subscribe } = useRealtime();
  const [scans, setScans] = useState<Scan[]>([]);
  const [meta, setMeta] = useState<QueueMeta>({ thresholds: {}, reason_text: {} });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);

  const load = useCallback(async () => {
    try {
      const r = await api<{ scans: Scan[] } & QueueMeta>("/api/queue");
      setScans(r.scans);
      setMeta({ thresholds: r.thresholds, reason_text: r.reason_text });
      setError(null);
    } catch (e) {
      setError(e as ApiError);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);
  useEffect(() => subscribe((m) => {
    if (m.type === "connected") load();  // resync after a reconnect
    else if (m.type === "scan_updated" && m.scan?.prediction !== undefined) {
      setScans((prev) => (prev.some((s) => s.id === m.scan.id) ? prev.map((s) => (s.id === m.scan.id ? m.scan : s)) : [...prev, m.scan]));
    } else if (m.type === "scan_removed") setScans((prev) => prev.filter((s) => s.id !== m.id));
  }), [subscribe, load]);

  return { scans, ...meta, loading, error, reload: load };
}

/** Re-render on a clock tick (for wait times). A local timer, not a server poll. */
export function useNow(ms = 15000) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), ms);
    return () => clearInterval(t);
  }, [ms]);
  return now;
}
