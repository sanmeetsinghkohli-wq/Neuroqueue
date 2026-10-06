"use client";

import { AnimatePresence, motion } from "framer-motion";
import { Link2, ShieldAlert, ShieldCheck } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError, type AuditEvent } from "@/lib/api";
import { cn, dateTime, timeOnly } from "@/lib/format";
import { useEvents } from "@/lib/realtime";
import { Card, Empty, ErrorNote, PageHeader, Skeleton } from "./ui";

interface Chain { ok: boolean; count: number; broken_at: number | null; reason: string | null; head?: string }
const TONE: Record<string, string> = { SIGN: "border-accent/60", APPROVED_AND_FINALIZED: "border-accent/60", PATIENT_ACCESSED_REPORT: "border-routine/50", OVERRIDE: "border-review/60", CHECK_BLOCKED: "border-urgent/60", SIGN_REFUSED: "border-urgent/60", CLASSIFY_FAILED: "border-urgent/60", SECOND_OPINION_UNAVAILABLE: "border-review/60" };

export function AuditView() {
  const [events, setEvents] = useState<AuditEvent[] | null>(null);
  const [chain, setChain] = useState<Chain | null>(null);
  const [actions, setActions] = useState<string[]>([]);
  const [action, setAction] = useState("");
  const [scanId, setScanId] = useState("");
  const [error, setError] = useState<ApiError | null>(null);

  const load = useCallback(() => {
    const q = new URLSearchParams();
    if (action) q.set("action", action);
    if (scanId.trim().length >= 8) q.set("scan_id", scanId.trim());
    api<{ events: AuditEvent[]; chain: Chain; actions: string[] }>(`/api/audit?${q}`).then((r) => {
      setEvents(r.events); setChain(r.chain); if (!action) setActions(r.actions); setError(null);
    }).catch(setError);
  }, [action, scanId]);
  useEffect(() => { load(); }, [load]);
  // new events are pushed by the server; the chain is re-verified on the server each time we refetch
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEvents((m) => {
    if (m.type !== "audit_appended") return;
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(load, 300);   // a burst of events is one refetch
  });

  return (
    <>
      <PageHeader title="Audit log" sub="Append-only. Each event stores the hash of the one before it, so any edit, deletion or re-ordering breaks the chain." />
      <AnimatePresence mode="wait">
        {chain && (
          <motion.div key={String(chain.ok)} initial={{ opacity: 0, y: -8 }} animate={{ opacity: 1, y: 0 }}
            className={cn("mb-5 flex flex-wrap items-center gap-3 rounded-2xl border px-4 py-3", chain.ok ? "border-routine/50 bg-routine/10" : "border-urgent/60 bg-urgent/10")}>
            {chain.ok ? <ShieldCheck className="h-6 w-6 text-routine" aria-hidden /> : <ShieldAlert className="h-6 w-6 text-urgent" aria-hidden />}
            <div className="min-w-0 flex-1">
              <p className="font-medium text-ink">{chain.ok ? `Chain verified: ${chain.count} events intact` : `Chain broken at event ${(chain.broken_at ?? 0) + 1} of ${chain.count}`}</p>
              <p className="truncate text-xs text-ink-2">{chain.ok ? <>Head hash <span className="font-mono">{chain.head}</span></> : chain.reason}</p>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      <Card className="mb-4 !p-3">
        <div className="grid gap-3 sm:grid-cols-[220px_1fr]">
          <div><label className="label" htmlFor="act">Action</label>
            <select id="act" className="input" value={action} onChange={(e) => setAction(e.target.value)}><option value="">All actions</option>{actions.map((a) => <option key={a}>{a}</option>)}</select></div>
          <div><label className="label" htmlFor="sid">Scan ID</label><input id="sid" className="input font-mono" placeholder="Paste a full scan ID to filter" value={scanId} onChange={(e) => setScanId(e.target.value)} /></div>
        </div>
      </Card>
      <ErrorNote error={error} className="mb-4" />

      {!events ? <div className="space-y-2">{[0, 1, 2, 3, 4].map((i) => <Skeleton key={i} className="h-14" />)}</div>
        : events.length === 0 ? <Empty title="No events match this filter" />
        : (
          <ol className="space-y-1.5">
            <AnimatePresence initial={false}>
              {events.map((e) => (
                <motion.li key={e.id} layout initial={{ opacity: 0, y: -10 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.25 }}
                  className={cn("rounded-xl border bg-surface px-3 py-2.5", TONE[e.action] ?? "border-line")}>
                  <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
                    <span className="w-9 font-mono text-xs text-ink-3">#{e.seq}</span>
                    <span className="rounded-md bg-surface-2 px-2 py-0.5 font-mono text-xs font-semibold text-ink">{e.action}</span>
                    <span className="text-ink-2">{e.actor_name}</span>
                    {e.scan_id && <button onClick={() => setScanId(e.scan_id!)} className="font-mono text-xs text-accent hover:underline" title="Filter by this scan">scan {e.scan_id.slice(0, 8)}</button>}
                    <time className="ml-auto text-xs tabular-nums text-ink-3" title={dateTime(e.ts)}>{timeOnly(e.ts)}</time>
                  </div>
                  {Object.keys(e.details ?? {}).length > 0 && <p translate="no" dir="ltr" className="mt-1 break-words pl-12 text-left font-mono text-[11px] leading-relaxed text-ink-3">{JSON.stringify(e.details)}</p>}
                  <p className="mt-1 flex items-center gap-1.5 pl-12 font-mono text-[10px] text-ink-3"><Link2 className="h-3 w-3" aria-hidden />{e.prev_hash.slice(0, 12)}… → {e.hash.slice(0, 12)}…</p>
                </motion.li>
              ))}
            </AnimatePresence>
          </ol>
        )}
    </>
  );
}
