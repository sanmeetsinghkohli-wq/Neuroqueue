"use client";

import { AnimatePresence, motion } from "framer-motion";
import { BadgeCheck, CheckCircle2, ChevronDown, Download, FileCheck2, FileClock, Hourglass, ScanLine, Stethoscope } from "lucide-react";
import { useState } from "react";
import { api, ApiError, fileUrl, type PatientScan, type User } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { cn, dateTime } from "@/lib/format";
import { useRealtime } from "@/lib/realtime";
import { useLive } from "@/lib/useLive";
import { AccountSecurity } from "./AccountSecurity";
import { BarList, ChartCard, SingleAreaChart } from "./charts";
import { PatientReportView } from "./PatientReportView";
import { Button, Card, Empty, ErrorNote, LiveDot, Notice, PageHeader, Skeleton, Stat } from "./ui";

const STAGES = ["Awaiting doctor review", "Reviewed by doctor", "Report under physician review", "Report finalized"];

function Timeline({ stage }: { stage: string }) {
  const at = Math.max(0, STAGES.indexOf(stage));
  return (
    <ol className="mt-4 grid grid-cols-4 gap-1" aria-label={`Status: ${stage}`}>
      {STAGES.map((s, i) => (
        <li key={s} className="text-center">
          <div className="relative mx-auto flex items-center">
            <span className={cn("h-1 flex-1 rounded-full", i <= at ? "bg-accent" : "bg-line", i === 0 && "opacity-0")} />
            <span className={cn("grid h-6 w-6 shrink-0 place-items-center rounded-full border-2 text-[10px] font-bold", i <= at ? "border-accent bg-accent text-accent-ink" : "border-line text-ink-3", i === at && at < 3 && "relative pulse-ring")}>
              {i < at || at === 3 ? <CheckCircle2 className="h-3.5 w-3.5" aria-hidden /> : i + 1}
            </span>
            <span className={cn("h-1 flex-1 rounded-full", i < at ? "bg-accent" : "bg-line", i === 3 && "opacity-0")} />
          </div>
          <p className={cn("mt-1.5 text-[11px] leading-tight", i === at ? "font-medium text-ink" : "text-ink-3")}>{s}</p>
        </li>
      ))}
    </ol>
  );
}

function Row({ k, v }: { k: string; v?: string | null }) {
  return <div className="flex justify-between gap-4 border-b border-line/60 py-1.5 text-sm last:border-0"><dt className="text-ink-3">{k}</dt><dd className="text-right text-ink">{v || "Not provided"}</dd></div>;
}

function ExamCard({ s }: { s: PatientScan }) {
  const [open, setOpen] = useState(false);
  const r = s.report;
  const toggle = () => {
    if (!open && r) api(`/api/my/scans/${s.id}/opened`, { method: "POST" }).catch(() => {});   // audit trail: patient opened the report
    setOpen((v) => !v);
  };
  return (
    <motion.li layout initial={{ opacity: 0, y: 14 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} className="card p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="font-display text-lg font-semibold text-ink">{s.exam_type || "MRI Brain"}</p>
          <p className="text-xs text-ink-3">Examination on {dateTime(s.uploaded_at)}{s.doctor_name ? <> · <span translate="no">{s.doctor_name}</span></> : null}</p>
        </div>
        <span className={cn("inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-semibold", r ? "border-accent text-ink" : "border-review/60 text-ink")}>
          {r ? <FileCheck2 className="h-3.5 w-3.5 text-accent" aria-hidden /> : <Hourglass className="h-3.5 w-3.5 text-review" aria-hidden />}{s.stage}
        </span>
      </div>
      <Timeline stage={s.stage} />

      {r ? (
        <div className="mt-5">
          <div className="rounded-xl border border-accent/40 bg-accent/10 p-4">
            <p className="text-xs font-medium uppercase tracking-wider text-ink-3">Doctor-approved result</p>
            <p className="mt-1 font-display text-2xl font-semibold text-ink">{r.approved_finding}</p>
            <p className="mt-1 flex items-center gap-1.5 text-xs text-ink-2"><BadgeCheck className="h-3.5 w-3.5 text-accent" aria-hidden />Approved and finalized by {r.signed_by_name} on {dateTime(r.signed_at)}</p>
          </div>
          <div className="mt-3 flex gap-2">
            <Button variant="subtle" className="flex-1" onClick={toggle} aria-expanded={open}><ChevronDown className={cn("h-4 w-4 transition-transform", open && "rotate-180")} aria-hidden />{open ? "Hide report" : "View report"}</Button>
            <a href={fileUrl(`/api/scans/${s.id}/pdf`)} className="flex-1"><Button className="w-full"><Download className="h-4 w-4" aria-hidden />Download my report (PDF)</Button></a>
          </div>
          <AnimatePresence initial={false}>
            {open && (
              <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }} exit={{ height: 0, opacity: 0 }} className="overflow-hidden">
                <div className="mt-4"><PatientReportView report={r} /></div>
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      ) : (
        <p className="mt-4 text-xs text-ink-3">Your report appears here only after your doctor has reviewed, approved and finalized it. This page updates by itself.</p>
      )}
    </motion.li>
  );
}

export function PatientScans() {
  const { data, error } = useLive<{ scans: PatientScan[] }>("/api/my/scans", ["scan_updated", "scan_removed"]);
  const { connected } = useRealtime();
  return (
    <>
      <PageHeader title="My reports" sub="Your examinations and the reports your doctor has finalized."><LiveDot on={connected} /></PageHeader>
      <ErrorNote error={error} className="mb-4" />
      {!data ? <div className="grid gap-4 lg:grid-cols-2">{[0, 1].map((i) => <Skeleton key={i} className="h-56" />)}</div>
        : data.scans.length === 0 ? <Empty icon={<ScanLine className="h-8 w-8" />} title="No examinations yet">When your doctor records an MRI examination for you, it appears here.</Empty>
        : <ul className="grid gap-4 lg:grid-cols-2"><AnimatePresence>{data.scans.map((s) => <ExamCard key={s.id} s={s} />)}</AnimatePresence></ul>}
    </>
  );
}

export function PatientDashboard() {
  const { user } = useAuth();
  const { connected } = useRealtime();
  const { data: o, error } = useLive<any>("/api/stats/overview", ["scan_updated", "scan_removed"]);
  const { data: mine } = useLive<{ scans: PatientScan[] }>("/api/my/scans", ["scan_updated", "scan_removed"]);
  if (error) return <ErrorNote error={error} />;
  if (!o) return <div className="grid gap-4 md:grid-cols-3">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-28" />)}</div>;
  const latest = mine?.scans[0];
  return (
    <>
      <PageHeader title={`Hello, ${user?.full_name.split(" ")[0]}`} sub="Your examinations and doctor-approved reports in one place."><LiveDot on={connected} /></PageHeader>
      <div className="grid gap-4 sm:grid-cols-3">
        <Stat label="Examinations" value={o.total} icon={<ScanLine className="h-5 w-5" />} />
        <Stat delay={0.05} label="With your doctor" value={o.total - o.released} icon={<FileClock className="h-5 w-5" />} tone="var(--review)" />
        <Stat delay={0.1} label="Finalized reports" value={o.released} icon={<FileCheck2 className="h-5 w-5" />} tone="var(--accent)" />
      </div>
      <div className="mt-5 grid gap-5 xl:grid-cols-3">
        <ChartCard className="xl:col-span-2" title="Your examinations" sub="Examinations per day, last 30 days"><SingleAreaChart data={o.timeline} x="date" y="total" name="Examinations" /></ChartCard>
        <ChartCard title="Report status" height="auto"><BarList data={o.stages} color="var(--s1)" /></ChartCard>
      </div>
      <h2 className="mb-3 mt-8 font-display text-lg font-semibold">Most recent examination</h2>
      {latest ? <ul className="max-w-2xl"><ExamCard s={latest} /></ul> : <Empty icon={<ScanLine className="h-8 w-8" />} title="No examinations yet">When your doctor records an MRI examination for you, it appears here.</Empty>}
      <Notice className="mt-6 max-w-2xl">Your scans are added by the clinic and reviewed by your assigned doctor. You receive the result only after your doctor has approved and finalized the report.</Notice>
    </>
  );
}

export function PatientProfile() {
  const { user, setUser } = useAuth();
  const [f, setF] = useState({ full_name: user?.full_name ?? "", phone: user?.phone ?? "", date_of_birth: user?.date_of_birth ?? "", gender: user?.gender ?? "" });
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const save = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true); setError(null); setSaved(false);
    try { setUser((await api<{ user: User }>("/api/auth/me", { method: "PATCH", body: Object.fromEntries(Object.entries(f).filter(([, v]) => v)) })).user); setSaved(true); }
    catch (err) { setError(err as ApiError); } finally { setBusy(false); }
  };
  return (
    <>
      <PageHeader title="Profile" sub="Your account details. Your patient ID is printed on your reports." />
      <Card className="max-w-xl">
        <form onSubmit={save} className="space-y-4">
          <div><label className="label" htmlFor="pf-id">Patient ID</label><input id="pf-id" className="input font-mono opacity-60" value={user ? `PT-${user.id.replace(/-/g, "").slice(0, 8).toUpperCase()}` : ""} disabled /></div>
          <div><label className="label" htmlFor="pf-name">Full name</label><input id="pf-name" className="input" required minLength={2} value={f.full_name} onChange={(e) => setF({ ...f, full_name: e.target.value })} /></div>
          <div><label className="label" htmlFor="pf-email">Email</label><input id="pf-email" className="input opacity-60" value={user?.email ?? ""} disabled /></div>
          <div className="grid grid-cols-2 gap-3">
            <div><label className="label" htmlFor="pf-dob">Date of birth</label><input id="pf-dob" type="date" className="input" value={f.date_of_birth} onChange={(e) => setF({ ...f, date_of_birth: e.target.value })} /></div>
            <div><label className="label" htmlFor="pf-g">Gender</label><select id="pf-g" className="input" value={f.gender} onChange={(e) => setF({ ...f, gender: e.target.value })}><option value="">Prefer not to say</option><option>Female</option><option>Male</option><option>Other</option></select></div>
          </div>
          <div><label className="label" htmlFor="pf-ph">Phone</label><input id="pf-ph" type="tel" className="input" value={f.phone} onChange={(e) => setF({ ...f, phone: e.target.value })} /></div>
          <ErrorNote error={error} />
          {saved && <Notice tone="good">Saved.</Notice>}
          <Button type="submit" loading={busy}>Save changes</Button>
        </form>
      </Card>
      <h2 className="mb-3 mt-8 font-display text-lg font-semibold">Security</h2>
      <AccountSecurity />
    </>
  );
}
