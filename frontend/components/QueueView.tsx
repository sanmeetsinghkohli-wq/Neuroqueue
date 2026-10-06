"use client";

import { AnimatePresence, motion } from "framer-motion";
import { ArrowRight, CheckCircle2, CircleAlert, FastForward, FileSignature, Inbox, Loader2, Play, Trash2, UploadCloud } from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { api, ApiError, fileUrl, type Scan, type Tier } from "@/lib/api";
import { CLASS_LABEL, cn, pct, TIER_HINT, TIER_LABEL, waitLabel } from "@/lib/format";
import { useJob, useLiveQueue, useNow, useRealtime } from "@/lib/realtime";
import { Button, Chip, Empty, ErrorNote, LiveDot, PageHeader, Progress, Skeleton, TierChip } from "./ui";

const TIER_RANK: Record<string, number> = { URGENT: 0, REVIEW: 1, ROUTINE: 2 };
type GroupKey = Tier | "UNPROCESSED" | "REPORTING" | "SIGNED";
const GROUPS: { key: GroupKey; title: string; hint: string }[] = [
  { key: "URGENT", title: TIER_LABEL.URGENT, hint: TIER_HINT.URGENT },
  { key: "REVIEW", title: TIER_LABEL.REVIEW, hint: TIER_HINT.REVIEW },
  { key: "ROUTINE", title: TIER_LABEL.ROUTINE, hint: TIER_HINT.ROUTINE },
  { key: "UNPROCESSED", title: "Not processed yet", hint: "Run the classification model" },
  { key: "REPORTING", title: "Reviewed, report in progress", hint: "Draft, check and sign" },
  { key: "SIGNED", title: "Signed and released", hint: "Read and signed by a radiologist" },
];

function groupOf(s: Scan): GroupKey {
  if (s.status === "signed") return "SIGNED";
  if (s.status === "reviewed" || s.status === "drafted") return "REPORTING";
  if (!s.tier) return "UNPROCESSED";
  return s.tier;
}

export function ReasonChips({ scan, reasonText }: { scan: Scan; reasonText: Record<string, string> }) {
  return (
    <div className="flex flex-wrap gap-1">
      {scan.reasons.map((r) => (
        <Chip key={r} tone={r.startsWith("CONFIDENT") ? "neutral" : r === "AWAITING_SIGNALS" ? "info" : "warn"} title={r}>
          {r === "AWAITING_SIGNALS" && <Loader2 className="h-3 w-3 animate-spin" aria-hidden />}{reasonText[r] ?? r}
        </Chip>
      ))}
      {scan.notes?.map((n) => <Chip key={n} title={n}>{reasonText[n] ?? n}</Chip>)}
    </div>
  );
}

interface Doctor { id: string; full_name: string }

/** Administrator only: who reads this scan. Locked once a doctor has reviewed it. */
function AssignSelect({ scan, doctors, onAssign }: { scan: Scan; doctors: Doctor[]; onAssign: (scanId: string, doctorId: string) => void }) {
  const locked = scan.status === "reviewed" || scan.status === "drafted" || scan.status === "signed";
  if (locked) return <span translate="no" className="truncate text-xs text-ink-2">{scan.assigned_doctor_name ?? "Unassigned"}</span>;
  return (
    <select aria-label={`Doctor assigned to ${scan.filename}`} value={scan.assigned_doctor_id ?? ""} onChange={(e) => e.target.value && onAssign(scan.id, e.target.value)}
      className={cn("w-full max-w-44 rounded-lg border bg-surface-2 px-2 py-1 text-xs text-ink", scan.assigned_doctor_id ? "border-line" : "border-review")}>
      {!scan.assigned_doctor_id && <option value="">Assign a doctor</option>}
      {scan.assigned_doctor_id && !doctors.some((d) => d.id === scan.assigned_doctor_id) && <option value={scan.assigned_doctor_id}>{scan.assigned_doctor_name}</option>}
      {doctors.map((d) => <option key={d.id} value={d.id}>{d.full_name}</option>)}
    </select>
  );
}

function Row({ scan, now, reasonText, canReview, doctors, onAssign }: { scan: Scan; now: number; reasonText: Record<string, string>; canReview: boolean;
  doctors?: Doctor[]; onAssign?: (scanId: string, doctorId: string) => void }) {
  const g = groupOf(scan);
  const href = canReview ? (g === "REPORTING" || g === "SIGNED" ? `/doctor/report/${scan.id}` : `/doctor/review/${scan.id}`) : null;
  const body = (
    <div className="grid grid-cols-[52px_1fr] items-center gap-3 md:grid-cols-[52px_minmax(150px,1.1fr)_minmax(150px,auto)_minmax(180px,1.4fr)_minmax(130px,auto)_84px_28px]">
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src={fileUrl(`/api/scans/${scan.id}/image`)} alt="" loading="lazy" className="h-12 w-12 rounded-lg bg-black object-cover" />
      <div className="min-w-0">
        <p className="truncate font-mono text-sm text-ink">{scan.filename}</p>
        <p translate="no" className="truncate text-xs text-ink-3">{scan.patient_name ?? "No patient linked"}</p>
        {doctors && onAssign && <div className="mt-1"><AssignSelect scan={scan} doctors={doctors} onAssign={onAssign} /></div>}
        <div className="mt-1.5 md:hidden"><TierChip tier={scan.tier} provisional={scan.tier_provisional} size="sm" /></div>
      </div>
      <div className="hidden md:block">
        {scan.status === "processing" && !scan.tier ? <span className="inline-flex items-center gap-1.5 text-xs text-ink-2"><Loader2 className="h-3.5 w-3.5 animate-spin text-accent" aria-hidden />Classifying</span>
          : scan.status === "failed" ? <span className="inline-flex items-center gap-1.5 text-xs text-urgent"><CircleAlert className="h-3.5 w-3.5" aria-hidden />Failed</span>
          : <TierChip tier={scan.tier} provisional={scan.tier_provisional} />}
        {scan.tier === "ROUTINE" && g === "ROUTINE" && <p className="mt-1 text-[11px] text-ink-3">Read last, still read</p>}
      </div>
      <div className="col-span-2 md:col-span-1">{scan.error ? <p className="text-xs text-urgent">{scan.error}</p> : <ReasonChips scan={scan} reasonText={reasonText} />}</div>
      <div className="hidden text-xs md:block">
        {scan.prediction ? (
          <>
            <p className="text-ink">{CLASS_LABEL[scan.prediction.top_class]} <span className="tabular-nums text-ink-2">{pct(scan.prediction.top_prob)}</span></p>
            <p className="text-ink-3">margin {pct(scan.prediction.margin_top2, 0)}</p>
          </>
        ) : <span className="text-ink-3">–</span>}
      </div>
      <div className="hidden text-right text-xs tabular-nums text-ink-2 md:block">
        {g === "SIGNED" ? <span className="inline-flex items-center gap-1 text-ink-2"><FileSignature className="h-3.5 w-3.5" aria-hidden />signed</span>
          : g === "REPORTING" ? <span className="inline-flex items-center gap-1"><CheckCircle2 className="h-3.5 w-3.5 text-accent" aria-hidden />reviewed</span>
          : <>waiting<br /><span className="text-ink">{waitLabel(scan.uploaded_at, now)}</span></>}
      </div>
      <div className="hidden justify-end md:flex">{href && <ArrowRight className="h-4 w-4 text-ink-3 transition group-hover:translate-x-1 group-hover:text-accent" aria-hidden />}</div>
    </div>
  );
  const cls = "group block rounded-xl border border-line bg-surface px-3 py-2.5 transition hover:border-accent/60 hover:bg-surface-2";
  return (
    <motion.li layout layoutId={scan.id} initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, scale: 0.97 }} transition={{ type: "spring", stiffness: 420, damping: 36 }}>
      {href ? <Link href={href} className={cls} aria-label={`Open ${scan.filename}, ${scan.tier ? TIER_LABEL[scan.tier] : "not processed"}`}>{body}</Link> : <div className={cls}>{body}</div>}
    </motion.li>
  );
}

export function QueueView({ role }: { role: "doctor" | "admin" }) {
  const { scans, reason_text, thresholds, loading, error } = useLiveQueue();
  const { connected } = useRealtime();
  const now = useNow();
  const job = useJob<{ processed: number }>();
  const [busy, setBusy] = useState("");
  const [actionError, setActionError] = useState<ApiError | null>(null);
  const [doctors, setDoctors] = useState<Doctor[]>([]);
  useEffect(() => { if (role === "admin") api<{ doctors: Doctor[] }>("/api/doctors").then((r) => setDoctors(r.doctors)).catch(() => {}); }, [role]);
  const assign = async (scanId: string, doctorId: string) => {
    setActionError(null);
    try { await api(`/api/scans/${scanId}/assign`, { body: { doctor_id: doctorId } }); } catch (e) { setActionError(e as ApiError); }
  };

  const grouped = useMemo(() => {
    const m = new Map<GroupKey, Scan[]>();
    [...scans].sort((a, b) => (TIER_RANK[a.tier ?? ""] ?? 3) - (TIER_RANK[b.tier ?? ""] ?? 3) || a.uploaded_at.localeCompare(b.uploaded_at))
      .forEach((s) => m.set(groupOf(s), [...(m.get(groupOf(s)) ?? []), s]));
    return m;
  }, [scans]);
  const pending = scans.filter((s) => s.status === "pending" || s.status === "failed").length;

  const act = async (name: string, path: string, body?: object) => {
    setBusy(name);
    setActionError(null);
    try { await api(path, { method: "POST", body: body ?? {} }); } catch (e) { setActionError(e as ApiError); } finally { setBusy(""); }
  };

  return (
    <>
      <PageHeader title={role === "doctor" ? "My scans" : "Reading queue"} sub={`${role === "doctor" ? "Scans an administrator assigned to you." : "Every scan, with the doctor it is assigned to."} Ordered by tier, then longest wait. Scans waiting more than ${thresholds.max_wait_min ?? 60} minutes are escalated to Urgent.`}>
        <LiveDot on={connected} />
        {role === "admin" && <Link href="/admin/upload"><Button variant="ghost" size="sm"><UploadCloud className="h-4 w-4" aria-hidden />Upload scans</Button></Link>}
        <Button variant="ghost" size="sm" loading={busy === "adv"} onClick={() => act("adv", "/api/demo/advance", { minutes: 45 })} title="Demo aid: ages unread scans by 45 minutes to show escalation"><FastForward className="h-4 w-4" aria-hidden />Simulate +45 min</Button>
        {role === "admin" && <Button variant="ghost" size="sm" loading={busy === "clear"} onClick={() => act("clear", "/api/demo/clear")}><Trash2 className="h-4 w-4" aria-hidden />Clear unsigned demo scans</Button>}
        {<Button loading={job.status === "running"} disabled={pending === 0} onClick={() => job.start("/api/queue/process")}><Play className="h-4 w-4" aria-hidden />Run classification{pending ? ` (${pending})` : ""}</Button>}
      </PageHeader>

      <AnimatePresence>
        {job.status === "running" && (
          <motion.div initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: "auto" }} exit={{ opacity: 0, height: 0 }} className="mb-4 overflow-hidden">
            <div className="card p-4"><Progress pct={job.pct} label={job.stage || "Starting"} /></div>
          </motion.div>
        )}
      </AnimatePresence>
      <ErrorNote error={actionError ?? job.error ?? error} className="mb-4" />

      {loading ? <div className="space-y-2">{[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-16" />)}</div>
        : scans.length === 0 ? (
          <Empty icon={<Inbox className="h-8 w-8" />} title="The queue is empty">
            {role === "doctor" ? "No scans are assigned to you yet. An administrator uploads scans and assigns them to a doctor." : "Upload scans and assign them to a doctor from the Upload scans page."}
          </Empty>
        ) : (
          <div className="space-y-6">
            {GROUPS.filter((g) => grouped.get(g.key)?.length).map((g) => (
              <section key={g.key} aria-label={g.title}>
                <motion.div layout="position" className="mb-2 flex items-baseline gap-3">
                  {(["URGENT", "REVIEW", "ROUTINE"] as string[]).includes(g.key) ? <TierChip tier={g.key as Tier} /> : <h2 className="text-sm font-semibold text-ink">{g.title}</h2>}
                  <span className="text-xs text-ink-3">{g.hint}</span>
                  <span className={cn("ml-auto rounded-full bg-surface-2 px-2 py-0.5 text-xs tabular-nums text-ink-2")}>{grouped.get(g.key)!.length}</span>
                </motion.div>
                <ul className="space-y-1.5">
                  <AnimatePresence initial={false}>
                    {grouped.get(g.key)!.map((s) => <Row key={s.id} scan={s} now={now} reasonText={reason_text} canReview={role === "doctor"} doctors={role === "admin" ? doctors : undefined} onAssign={role === "admin" ? assign : undefined} />)}
                  </AnimatePresence>
                </ul>
              </section>
            ))}
          </div>
        )}
    </>
  );
}
