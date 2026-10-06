"use client";

import { AnimatePresence, motion } from "framer-motion";
import { ArrowLeft, CheckCircle2, CircleDashed, Download, FileSignature, Loader2, Lock, MinusCircle, Pencil, RefreshCw, ShieldAlert, ShieldCheck, XCircle } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Button, Card, ErrorNote, Notice, PageHeader, Skeleton } from "@/components/ui";
import { PatientReportView } from "@/components/PatientReportView";
import { api, ApiError, fileUrl, type CheckIssue, type CheckRow, type PatientReport, type Report, type Scan } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { CLASS_LABEL, cn, dateTime } from "@/lib/format";
import { useJob } from "@/lib/realtime";

const EXPECTED_ROWS = ["Radiologist review completed", "Tumor type matches the confirmed review", "No numbers beyond the confirmed fields",
  "No locations beyond the confirmed fields", "No malignancy, prognosis or 'cleared' language", "Required AI-assistance statement present"];

function Highlighted({ text, issues }: { text: string; issues: CheckIssue[] }) {
  const parts = useMemo(() => {
    const quotes = [...new Set(issues.map((i) => i.quote).filter((q) => q && q.length > 1))].sort((a, b) => b.length - a.length);
    if (!quotes.length) return [text];
    const re = new RegExp(`(${quotes.map((q) => q.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|")})`, "gi");
    return text.split(re);
  }, [text, issues]);
  return <>{parts.map((p, i) => (i % 2 ? <mark key={i} className="rounded bg-urgent/40 px-0.5 text-ink underline decoration-urgent decoration-2 underline-offset-2">{p}</mark> : p))}</>;
}

function Panel({ title, stamp, text, streaming, editing, onEdit, issues, signed }: {
  title: string; stamp: string; text: string; streaming: boolean; editing: boolean; onEdit: (v: string) => void; issues: CheckIssue[]; signed: boolean }) {
  return (
    <Card className="flex min-h-[340px] flex-col">
      <div className="mb-3 flex items-center justify-between gap-2">
        <h2 className="font-display text-base font-semibold">{title}</h2>
        <span className={cn("rounded-md border px-2 py-0.5 font-mono text-[11px] font-semibold tracking-widest", signed ? "border-accent text-accent" : "border-review text-review")}>{stamp}</span>
      </div>
      {editing ? (
        <textarea value={text} onChange={(e) => onEdit(e.target.value)} aria-label={`${title} text`} className="input min-h-[280px] flex-1 font-mono !text-[13px] leading-relaxed" />
      ) : (
        <div translate="no" dir="ltr" className={cn("flex-1 whitespace-pre-wrap rounded-xl bg-bg p-4 text-left text-sm leading-relaxed text-ink", streaming && "caret")}>
          {text ? <Highlighted text={text} issues={issues} /> : <span className="text-ink-3">{streaming ? "" : "No draft yet."}</span>}
        </div>
      )}
    </Card>
  );
}

function RowIcon({ status }: { status: CheckRow["status"] | "pending" | "running" }) {
  if (status === "pass") return <CheckCircle2 className="h-4 w-4 text-routine" aria-label="Passed" />;
  if (status === "fail") return <XCircle className="h-4 w-4 text-urgent" aria-label="Failed" />;
  if (status === "skipped") return <MinusCircle className="h-4 w-4 text-ink-3" aria-label="Skipped" />;
  if (status === "running") return <Loader2 className="h-4 w-4 animate-spin text-accent" aria-label="Running" />;
  return <CircleDashed className="h-4 w-4 text-ink-3" aria-label="Waiting" />;
}

export default function ReportPage() {
  const { id } = useParams<{ id: string }>();
  const { user } = useAuth();
  const job = useJob<{ report: Report }>();
  const [scan, setScan] = useState<Scan | null>(null);
  const [report, setReport] = useState<Report | null>(null);
  const [loadError, setLoadError] = useState<ApiError | null>(null);
  const [clinical, setClinical] = useState("");
  const [summary, setSummary] = useState("");
  const [editing, setEditing] = useState(false);
  const [reviewer, setReviewer] = useState("");
  const [signing, setSigning] = useState(false);
  const [signError, setSignError] = useState<ApiError | null>(null);
  const autoStarted = useRef(false);
  const [kind, setKind] = useState<"draft" | "check">("draft");
  const [view, setView] = useState<"doctor" | "patient">("doctor");
  const [patientVersion, setPatientVersion] = useState<PatientReport | null>(null);
  useEffect(() => {   // what the patient will actually receive, rebuilt on the server from the saved report
    if (view === "patient" && report) api<{ patient_report: PatientReport }>(`/api/scans/${id}/patient-version`).then((r) => setPatientVersion(r.patient_report)).catch(() => setPatientVersion(null));
  }, [view, report, id]);
  const startDraft = () => { setKind("draft"); setEditing(false); job.start(`/api/scans/${id}/draft`); };

  const apply = useCallback((r: Report | null) => {
    setReport(r);
    if (r) { setClinical(r.clinical_text); setSummary(r.patient_summary); }
  }, []);

  useEffect(() => {
    api<{ scan: Scan; report: Report | null }>(`/api/scans/${id}`).then((r) => {
      setScan(r.scan);
      apply(r.report);
      if (!r.report && r.scan.review && !autoStarted.current) {   // straight from the review screen: draft immediately
        autoStarted.current = true;
        startDraft();
      }
    }).catch(setLoadError);
  }, [id]); // eslint-disable-line react-hooks/exhaustive-deps

  // Fold streamed job events into the page.
  const assembled = job.partials.find((p) => p.assembled)?.assembled as { clinical_text: string; patient_summary: string } | undefined;
  const liveRows = job.partials.filter((p) => p.check_row).map((p) => p.check_row as CheckRow);
  const guard = job.partials.find((p) => p.guard)?.guard as { section: string; phrase: string } | undefined;
  useEffect(() => { if (job.status === "done" && job.result?.report) { apply(job.result.report); setEditing(false); setScan((s) => (s ? { ...s, status: "drafted" } : s)); } }, [job.status, job.result, apply]);

  const running = job.status === "running";
  const drafting = running && kind === "draft" && !assembled;
  const live = running && kind === "draft";
  const shownClinical = live ? assembled?.clinical_text ?? job.text.clinical ?? "" : clinical;
  const shownSummary = live ? assembled?.patient_summary ?? job.text.summary ?? "" : summary;

  const rows: (CheckRow | { id: string; label: string; status: "pending" | "running"; issues: CheckIssue[] })[] = running
    ? EXPECTED_ROWS.map((label, i) => liveRows[i] ?? { id: `p${i}`, label, status: i === liveRows.length && (assembled || kind === "check") ? "running" : "pending", issues: [] })
    : report?.check.rows ?? [];
  const issues = running ? liveRows.flatMap((r) => r.issues) : report?.check.issues ?? [];
  const signed = report?.status === "signed";
  const dirty = !!report && !signed && (clinical !== report.clinical_text || summary !== report.patient_summary);
  const passed = report?.status === "passed" && !dirty && !running;
  const nameOk = reviewer.trim().toLowerCase() === (user?.full_name ?? "").trim().toLowerCase();

  const sign = async () => {
    setSigning(true);
    setSignError(null);
    try {
      const r = await api<{ report: Report; scan: Scan }>(`/api/scans/${id}/sign`, { body: { reviewer } });
      setReport(r.report);
      setScan(r.scan);
    } catch (e) {
      setSignError(e as ApiError);
    } finally {
      setSigning(false);
    }
  };

  if (loadError) return <ErrorNote error={loadError} />;
  if (!scan) return <div className="grid gap-5 lg:grid-cols-2"><Skeleton className="h-96" /><Skeleton className="h-96" /></div>;
  const rev = scan.review;
  const stamp = signed ? "FINAL" : "DRAFT";
  const stage = signed ? "Approved and finalized" : running && kind === "draft" ? "AI-generated draft" : !report ? "Draft"
    : report.sources?.edited_by || dirty || report.status === "blocked" ? "Under physician review" : "AI-generated draft";
  const pred = scan.prediction;

  return (
    <>
      <PageHeader title="Report" sub={`${scan.filename} · ${scan.patient_name ?? "no patient linked"}`}>
        <Link href="/doctor/queue"><Button variant="ghost" size="sm"><ArrowLeft className="h-4 w-4" aria-hidden />Queue</Button></Link>
        {!signed && <Link href={`/doctor/review/${id}`}><Button variant="ghost" size="sm">Change review</Button></Link>}
        {!signed && rev && <Button variant="ghost" size="sm" disabled={running} onClick={startDraft}><RefreshCw className="h-4 w-4" aria-hidden />Regenerate draft</Button>}
        {!signed && report && <Button variant="ghost" size="sm" disabled={running} onClick={() => setEditing((v) => !v)}><Pencil className="h-4 w-4" aria-hidden />{editing ? "Stop editing" : "Edit text"}</Button>}
      </PageHeader>

      {!rev && <Notice tone="warn" className="mb-4">This scan has not been reviewed. <Link href={`/doctor/review/${id}`} className="text-accent underline">Review it first</Link>; a report can only be written from confirmed fields.</Notice>}
      <ErrorNote error={job.error} className="mb-4" />
      <AnimatePresence>
        {(guard || report?.guard) && !signed && (
          <motion.div initial={{ opacity: 0, y: -6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} className="mb-4">
            <Notice tone="warn"><b>Live guard stopped the draft.</b> The writer started to produce the forbidden phrase &ldquo;{(guard ?? report!.guard)!.phrase}&rdquo; in the {(guard ?? report!.guard)!.section} text. Regenerate the draft.</Notice>
          </motion.div>
        )}
      </AnimatePresence>

      <Card className="mb-5">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <p className="font-display text-lg font-semibold text-ink">AI-Assisted Brain MRI Report</p>
            <p className="text-xs text-ink-3">Report ID <span className="font-mono text-ink-2">{report?.report_no ?? "assigned when drafted"}</span></p>
          </div>
          <span className={cn("rounded-full border px-3 py-1 text-xs font-semibold", signed ? "border-accent bg-accent/15 text-ink" : "border-review/60 bg-review/10 text-ink")}>{stage}</span>
        </div>
        <dl className="mt-4 grid gap-x-8 gap-y-2 text-sm sm:grid-cols-2 lg:grid-cols-4">
          {[["Patient", scan.patient_name], ["Age / gender", [scan.patient_age ? `${scan.patient_age} years` : null, scan.patient_gender].filter(Boolean).join(", ")], ["Examination", scan.exam_type || "MRI Brain"],
            ["Examination date", dateTime(scan.uploaded_at)], ["Referring doctor", scan.referring_doctor], ["Clinical concern", scan.clinical_concern],
            ["AI model classification", pred ? `${CLASS_LABEL[pred.top_class]} (${(pred.top_prob * 100).toFixed(1)}%)` : null],
            ["Physician-confirmed finding", rev ? `${CLASS_LABEL[rev.final_class]}${rev.decision === "override" ? " (override)" : ""}` : null]].map(([k, v]) => (
            <div key={k as string}><dt className="text-xs text-ink-3">{k}</dt><dd className="text-ink">{v || "Not provided"}</dd></div>
          ))}
        </dl>
        <p className="mt-3 text-[11px] text-ink-3">The AI classification is printed on the report exactly as the model produced it. The text below is written only from the fields you confirmed.</p>
      </Card>

      <div role="tablist" aria-label="Report version" className="mb-4 inline-flex rounded-xl bg-surface p-1">
        {([["doctor", "Doctor report (clinical)"], ["patient", "Patient report (plain language)"]] as const).map(([v, label]) => (
          <button key={v} role="tab" aria-selected={view === v} onClick={() => setView(v)} className={cn("rounded-lg px-4 py-2 text-sm transition", view === v ? "bg-accent font-semibold text-accent-ink" : "text-ink-2 hover:text-ink")}>{label}</button>
        ))}
      </div>

      {view === "patient" && (
        <Card className="mb-5">
          <p className="mb-3 text-xs text-ink-3">This is the separate version your patient sees and downloads. It never contains your clinical notes, the model probabilities or the clinical report text. Treatment, medicines, next steps, follow-up and warning signs are shown in your exact words.</p>
          {patientVersion ? <PatientReportView report={patientVersion} /> : <p className="text-sm text-ink-3">{report ? "Loading the patient version" : "Draft the report first."}</p>}
        </Card>
      )}

      <div className={cn("grid gap-5 xl:grid-cols-2", view === "patient" && "hidden")}>
        <Panel title="Clinical report" stamp={stamp} text={shownClinical} streaming={drafting} editing={editing && !signed} onEdit={setClinical} issues={issues.filter((i) => i.where === "clinical")} signed={!!signed} />
        <Panel title="Plain-language finding (used in the patient report)" stamp={stamp} text={shownSummary} streaming={drafting} editing={editing && !signed} onEdit={setSummary} issues={issues.filter((i) => i.where === "summary")} signed={!!signed} />
      </div>

      <div className="mt-5 grid gap-5 xl:grid-cols-[1.3fr_1fr]">
        {/* ---------- check ---------- */}
        <Card>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h2 className="flex items-center gap-2 font-display text-base font-semibold">
              {passed || signed ? <ShieldCheck className="h-5 w-5 text-routine" aria-hidden /> : <ShieldAlert className="h-5 w-5 text-review" aria-hidden />}Report check
            </h2>
            <span className="text-xs text-ink-2">
              {running ? job.stage : signed ? "Passed before sign-off" : !report ? "No draft yet" : dirty ? "Text edited: re-run the check" : report.status === "passed" ? "All checks passed" : `${report.check.issues.length} blocking issue${report.check.issues.length === 1 ? "" : "s"}`}
            </span>
          </div>
          <ul className="mt-4 space-y-1.5">
            <AnimatePresence initial={false}>
              {rows.map((r) => (
                <motion.li key={r.id} layout initial={{ opacity: 0, x: -10 }} animate={{ opacity: 1, x: 0 }} transition={{ duration: 0.25 }}
                  className={cn("rounded-xl border px-3 py-2", r.status === "fail" ? "border-urgent/50 bg-urgent/10" : "border-line bg-surface-2")}>
                  <div className="flex items-center gap-2.5 text-sm"><RowIcon status={r.status} /><span className={r.status === "pending" ? "text-ink-3" : "text-ink"}>{r.label}</span></div>
                  {"detail" in r && r.detail && <p className="mt-1 pl-6 text-xs text-ink-3">{r.detail}</p>}
                  {r.issues.map((i, k) => (
                    <p key={k} className="mt-1.5 pl-6 text-xs leading-relaxed text-ink-2">
                      <span className="mr-1.5 rounded bg-urgent/30 px-1.5 py-0.5 font-mono text-[10px] text-ink">{i.code}</span>
                      <span className="text-ink-3">{i.where === "clinical" ? "Clinical report" : "Patient summary"}: </span>
                      {i.quote && <q className="font-medium text-ink">{i.quote}</q>} {i.detail}
                    </p>
                  ))}
                </motion.li>
              ))}
            </AnimatePresence>
          </ul>
          {dirty && <Button className="mt-4" loading={running} onClick={() => { setKind("check"); job.start(`/api/scans/${id}/check`, { clinical_text: clinical, patient_summary: summary }); }}>Save edits and re-run check</Button>}
          {report?.sources && !running && <p className="mt-3 text-[11px] text-ink-3">Draft source: clinical {report.sources.clinical}, summary {report.sources.summary}{report.sources.edited_by ? `, edited by ${report.sources.edited_by}` : ""}.</p>}
        </Card>

        {/* ---------- sign-off ---------- */}
        <Card>
          <h2 className="flex items-center gap-2 font-display text-base font-semibold"><FileSignature className="h-5 w-5 text-accent" aria-hidden />Approve and finalize</h2>
          {signed ? (
            <motion.div initial={{ opacity: 0, scale: 0.97 }} animate={{ opacity: 1, scale: 1 }} className="mt-4 space-y-4">
              <Notice tone="good">Approved and finalized by <b>{report!.signed_by_name}</b> on {dateTime(report!.signed_at)}.{scan.patient_id ? " The patient can now view and download this report." : " No patient account is linked, so it is not visible in any patient portal."}</Notice>
              <a href={fileUrl(`/api/scans/${id}/pdf`)}><Button className="w-full" size="lg"><Download className="h-4 w-4" aria-hidden />Download doctor report (PDF)</Button></a>
              <a href={fileUrl(`/api/scans/${id}/pdf?version=patient`)}><Button className="w-full" variant="subtle"><Download className="h-4 w-4" aria-hidden />Download patient report (PDF)</Button></a>
            </motion.div>
          ) : (
            <div className="mt-4 space-y-3">
              <ol className="space-y-1.5 text-sm">
                {[["Doctor review completed", !!rev], ["Report check passed", !!passed], ["Named approving doctor", nameOk]].map(([label, ok]) => (
                  <li key={label as string} className="flex items-center gap-2">{ok ? <CheckCircle2 className="h-4 w-4 text-routine" aria-hidden /> : <Lock className="h-4 w-4 text-ink-3" aria-hidden />}<span className={ok ? "text-ink" : "text-ink-3"}>{label}</span></li>
                ))}
              </ol>
              <div><label className="label" htmlFor="rv">Type your full name to sign ({user?.full_name})</label><input id="rv" className="input" value={reviewer} onChange={(e) => setReviewer(e.target.value)} autoComplete="off" disabled={!passed} /></div>
              <ErrorNote error={signError} />
              <Button className="w-full" size="lg" disabled={!passed || !nameOk} loading={signing} onClick={sign}><FileSignature className="h-4 w-4" aria-hidden />Approve and finalize</Button>
              {!passed && <p className="text-xs text-ink-3">Approval stays locked until every check is green.</p>}
            </div>
          )}
        </Card>
      </div>
    </>
  );
}
