"use client";

import { AnimatePresence, motion } from "framer-motion";
import { ArrowLeft, Check, Flame, Lightbulb, Loader2, PenLine, Plus, Sparkles, Trash2 } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { ReasonChips } from "@/components/QueueView";
import { Button, Card, ErrorNote, Notice, PageHeader, Skeleton, TierChip } from "@/components/ui";
import { api, ApiError, fileUrl, streamTokens, type ClassName, type Medication, type Scan } from "@/lib/api";
import { CLASS_LABEL, CLASSES, cn, pct, waitLabel } from "@/lib/format";
import { useEvents, useNow } from "@/lib/realtime";

interface Detail { scan: Scan; reason_text: Record<string, string>; all_next_steps: Record<ClassName, string[]> }

export default function ReviewPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const now = useNow();
  const [d, setD] = useState<Detail | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [heat, setHeat] = useState(false);
  const [heatReady, setHeatReady] = useState(false);
  const [decision, setDecision] = useState<"confirm" | "override">("confirm");
  const [finalClass, setFinalClass] = useState<ClassName | "">("");
  const [reason, setReason] = useState("");
  const [size, setSize] = useState("");
  const [location, setLocation] = useState("");
  const [notes, setNotes] = useState("");
  const [clin, setClin] = useState({ symptoms: "", history: "", treatment_plan: "", follow_up: "", patient_instructions: "", warning_signs: "" });
  const [meds, setMeds] = useState<Medication[]>([]);
  const setMed = (i: number, k: keyof Medication, v: string) => setMeds((prev) => prev.map((m, j) => (j === i ? { ...m, [k]: v } : m)));
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<ApiError | { message: string; hint?: string } | null>(null);
  const [explain, setExplain] = useState("");
  const [explaining, setExplaining] = useState(false);
  const formRef = useRef<HTMLFormElement>(null);

  const load = useCallback(() => api<Detail>(`/api/scans/${id}`).then((r) => {
    setD(r);
    const rev = r.scan.review;
    if (rev) {
      setDecision(rev.decision); setFinalClass(rev.decision === "override" ? rev.final_class : ""); setReason(rev.override_reason ?? "");
      setSize(rev.size_mm?.toString() ?? ""); setLocation(rev.location ?? ""); setNotes(rev.notes ?? "");
      setClin({ symptoms: rev.symptoms ?? "", history: rev.history ?? "", treatment_plan: rev.treatment_plan ?? "", follow_up: rev.follow_up ?? "",
                patient_instructions: rev.patient_instructions ?? "", warning_signs: rev.warning_signs ?? "" });
      setMeds((rev.medications ?? []).map((m) => ({ name: m.name, purpose: m.purpose ?? "", how_to_take: m.how_to_take ?? "", when_to_take: m.when_to_take ?? "", duration: m.duration ?? "", instructions: m.instructions ?? "" })));
    }
  }).catch(setError), [id]);
  useEffect(() => { load(); }, [load]);
  useEvents((m) => { if (m.type === "scan_updated" && m.scan?.id === id && m.scan.prediction !== undefined) setD((prev) => (prev ? { ...prev, scan: m.scan } : prev)); });

  const scan = d?.scan;
  const predicted = scan?.prediction?.top_class;
  const chosen: ClassName | undefined = decision === "confirm" ? predicted : finalClass || undefined;
  const signed = scan?.status === "signed";
  const notReady = !scan?.prediction;

  const submit = async (e?: React.FormEvent) => {
    e?.preventDefault();
    if (!scan || signed || notReady) return;
    if (decision === "override" && (!finalClass || !reason.trim())) {
      setFormError({ message: "An override needs the finding you are changing to, and a reason.", hint: "Choose a finding and say briefly why you disagree." });
      return;
    }
    setSaving(true);
    setFormError(null);
    try {
      await api(`/api/scans/${id}/review`, { body: { decision, final_class: decision === "override" ? finalClass : null, override_reason: reason || null,
        size_mm: size ? Number(size) : null, location: location || null, notes: notes || null,
        ...Object.fromEntries(Object.entries(clin).map(([k, v]) => [k, v.trim() || null])),
        medications: meds.filter((m) => m.name.trim()).map((m) => Object.fromEntries(Object.entries(m).map(([k, v]) => [k, (v ?? "").trim() || null])) as unknown as Medication) } });
      router.push(`/doctor/report/${id}`);
    } catch (err) {
      setFormError(err as ApiError);
      setSaving(false);
    }
  };

  // Keyboard-friendly review: C confirm, O override, H heatmap, Ctrl+Enter save.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const typing = ["INPUT", "TEXTAREA", "SELECT"].includes((e.target as HTMLElement)?.tagName);
      if ((e.ctrlKey || e.metaKey) && e.key === "Enter") { formRef.current?.requestSubmit(); return; }
      if (typing || e.ctrlKey || e.metaKey || e.altKey) return;
      if (e.key.toLowerCase() === "c") setDecision("confirm");
      if (e.key.toLowerCase() === "o") setDecision("override");
      if (e.key.toLowerCase() === "h") setHeat((v) => !v);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const runExplain = async () => {
    setExplain("");
    setExplaining(true);
    try { await streamTokens(`/api/scans/${id}/explain`, {}, (t) => setExplain((s) => s + t)); }
    catch (err) { setExplain((err as ApiError).message); }
    finally { setExplaining(false); }
  };

  if (error) return <ErrorNote error={error} />;
  if (!d || !scan) return <div className="grid gap-5 lg:grid-cols-2"><Skeleton className="h-[520px]" /><Skeleton className="h-[520px]" /></div>;

  return (
    <>
      <PageHeader title="Review scan" sub={`${scan.filename} · ${scan.patient_name ?? "no patient linked"} · waiting ${waitLabel(scan.uploaded_at, now)}`}>
        <Link href="/doctor/queue"><Button variant="ghost" size="sm"><ArrowLeft className="h-4 w-4" aria-hidden />Queue</Button></Link>
      </PageHeader>
      {signed && <Notice tone="good" className="mb-4">This report is signed and released. The review is locked. <Link href={`/doctor/report/${id}`} className="text-accent underline">Open the report</Link></Notice>}

      <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_minmax(0,1.15fr)]">
        {/* ---------- image ---------- */}
        <Card className="p-3">
          <div className="relative mx-auto aspect-square max-h-[62vh] overflow-hidden rounded-xl bg-black">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={fileUrl(`/api/scans/${id}/image`)} alt={`MRI slice ${scan.filename}`} className="h-full w-full object-contain" />
            <AnimatePresence>
              {heat && scan.prediction && (
                // eslint-disable-next-line @next/next/no-img-element
                <motion.img key="heat" src={fileUrl(`/api/scans/${id}/heatmap`)} alt="Occlusion heatmap overlay" onLoad={() => setHeatReady(true)}
                  initial={{ opacity: 0 }} animate={{ opacity: heatReady ? 1 : 0 }} exit={{ opacity: 0 }} transition={{ duration: 0.35 }} className="absolute inset-0 h-full w-full object-contain" />
              )}
            </AnimatePresence>
            {heat && !heatReady && <div className="absolute inset-0 grid place-items-center bg-black/40 text-sm text-ink"><span className="inline-flex items-center gap-2"><Loader2 className="h-4 w-4 animate-spin" aria-hidden />Computing occlusion heatmap</span></div>}
          </div>
          <div className="mt-3 flex flex-wrap items-center justify-between gap-2 px-1">
            <button type="button" role="switch" aria-checked={heat} disabled={!scan.prediction} onClick={() => setHeat((v) => !v)}
              className={cn("inline-flex items-center gap-2 rounded-lg border px-3 py-1.5 text-sm transition disabled:opacity-40", heat ? "border-accent bg-accent/15 text-ink" : "border-line text-ink-2 hover:bg-surface-2")}>
              <Flame className="h-4 w-4" aria-hidden />{heat ? "Heatmap on" : "Heatmap off"} <kbd className="rounded bg-surface-2 px-1.5 text-[10px] text-ink-3">H</kbd>
            </button>
            <p className="text-xs text-ink-3">Shows where the model looked. It is not a tumor outline.</p>
          </div>
        </Card>

        {/* ---------- evidence + decision ---------- */}
        <div className="space-y-5">
          <Card delay={0.05}>
            <div className="flex flex-wrap items-center gap-3">
              <TierChip tier={scan.tier} provisional={scan.tier_provisional} />
              <ReasonChips scan={scan} reasonText={d.reason_text} />
              <button onClick={runExplain} disabled={explaining || !scan.prediction} className="ml-auto inline-flex items-center gap-1.5 text-xs text-accent hover:underline disabled:opacity-40">
                <Sparkles className="h-3.5 w-3.5" aria-hidden />Explain this tier
              </button>
            </div>
            <AnimatePresence>
              {(explain || explaining) && (
                <motion.p initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: "auto" }} exit={{ opacity: 0, height: 0 }}
                  className={cn("mt-3 overflow-hidden rounded-xl bg-surface-2 px-3 py-2.5 text-sm leading-relaxed text-ink-2", explaining && "caret")}>{explain}</motion.p>
              )}
            </AnimatePresence>

            {scan.prediction ? (
              <div className="mt-5 grid gap-5 sm:grid-cols-[1.4fr_1fr]">
                <div>
                  <p className="mb-2 text-xs font-medium uppercase tracking-wider text-ink-3">Model probability, every class</p>
                  <ul className="space-y-2.5">
                    {CLASSES.map((c, i) => {
                      const p = scan.prediction!.probs[c];
                      const top = c === predicted;
                      return (
                        <li key={c}>
                          <div className="mb-1 flex justify-between text-sm"><span className={top ? "font-semibold text-ink" : "text-ink-2"}>{CLASS_LABEL[c]}{top && " (predicted)"}</span><span className="tabular-nums text-ink">{pct(p, 1)}</span></div>
                          <div className="h-2 overflow-hidden rounded-full bg-surface-2"><motion.div className="h-full rounded-full" style={{ background: top ? "var(--accent)" : "var(--ink-3)" }} initial={{ width: 0 }} animate={{ width: `${p * 100}%` }} transition={{ duration: 0.7, delay: 0.08 * i, ease: "easeOut" }} /></div>
                        </li>
                      );
                    })}
                  </ul>
                  <p className="mt-2 text-[11px] text-ink-3">Margin to the second class: {pct(scan.prediction.margin_top2)}. Model: {scan.prediction.model}{scan.prediction.model_version ? ` (${scan.prediction.model_version})` : ""}.</p>
                </div>
                <div className="rounded-xl bg-surface-2 p-3.5">
                  <p className="text-xs font-medium uppercase tracking-wider text-ink-3">Model classification</p>
                  <p className="mt-2 font-display text-xl font-semibold text-ink">{CLASS_LABEL[scan.prediction.top_class]}</p>
                  <p className="text-sm tabular-nums text-ink-2">Confidence {pct(scan.prediction.top_prob)}</p>
                  <dl className="mt-3 space-y-1 text-xs">
                    <div className="flex justify-between gap-2"><dt className="text-ink-3">Examination</dt><dd className="text-right text-ink">{scan.exam_type || "MRI Brain"}</dd></div>
                    <div className="flex justify-between gap-2"><dt className="text-ink-3">Clinical concern</dt><dd className="text-right text-ink">{scan.clinical_concern || "Not provided"}</dd></div>
                    <div className="flex justify-between gap-2"><dt className="text-ink-3">Referring doctor</dt><dd className="text-right text-ink">{scan.referring_doctor || "Not provided"}</dd></div>
                  </dl>
                  <p className="mt-3 text-[11px] leading-relaxed text-ink-3">This is the output of the trained MRI model. It is stored as-is and is not changed by any other model. You confirm or override it below.</p>
                </div>
              </div>
            ) : <Notice className="mt-4" tone="warn">This scan has not been classified yet. Run the classification model from the queue first.</Notice>}
            {scan.ood?.flag && <Notice tone="warn" className="mt-4">Out-of-distribution warning: {scan.ood.reason}</Notice>}
          </Card>

          <Card delay={0.1}>
            <form ref={formRef} onSubmit={submit} className="space-y-4">
              <fieldset disabled={signed || notReady} className="space-y-4 disabled:opacity-60">
                <legend className="sr-only">Your decision</legend>
                <div className="grid grid-cols-2 gap-2" role="radiogroup" aria-label="Decision">
                  {([["confirm", "Confirm classification", Check, "C"], ["override", "Override", PenLine, "O"]] as const).map(([v, label, Icon, key]) => (
                    <button key={v} type="button" role="radio" aria-checked={decision === v} onClick={() => setDecision(v)}
                      className={cn("flex items-center justify-center gap-2 rounded-xl border px-3 py-3 text-sm font-medium transition", decision === v ? "border-accent bg-accent/15 text-ink" : "border-line text-ink-2 hover:bg-surface-2")}>
                      <Icon className="h-4 w-4" aria-hidden />{label}<kbd className="rounded bg-surface-2 px-1.5 text-[10px] text-ink-3">{key}</kbd>
                    </button>
                  ))}
                </div>
                <AnimatePresence initial={false}>
                  {decision === "override" && (
                    <motion.div initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: "auto" }} exit={{ opacity: 0, height: 0 }} className="grid gap-3 overflow-hidden sm:grid-cols-2">
                      <div>
                        <label className="label" htmlFor="fc">Correct finding</label>
                        <select id="fc" className="input" value={finalClass} onChange={(e) => setFinalClass(e.target.value as ClassName)}>
                          <option value="">Choose</option>
                          {CLASSES.filter((c) => c !== predicted).map((c) => <option key={c} value={c}>{CLASS_LABEL[c]}</option>)}
                        </select>
                      </div>
                      <div><label className="label" htmlFor="rs">Reason for override (required)</label><input id="rs" className="input" value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. dural tail, extra-axial" /></div>
                    </motion.div>
                  )}
                </AnimatePresence>
                {chosen !== "no_tumor" && (
                  <div className="grid gap-3 sm:grid-cols-[130px_1fr]">
                    <div><label className="label" htmlFor="sz">Size (mm)</label><input id="sz" type="number" min={0.1} max={200} step={0.1} className="input" value={size} onChange={(e) => setSize(e.target.value)} /></div>
                    <div><label className="label" htmlFor="loc">Location</label><input id="loc" className="input" value={location} onChange={(e) => setLocation(e.target.value)} placeholder="e.g. left frontal lobe" /></div>
                  </div>
                )}
                <div><label className="label" htmlFor="nt">Clinical notes (doctor report only, never shown to the patient)</label><textarea id="nt" className="input min-h-16" value={notes} onChange={(e) => setNotes(e.target.value)} /></div>

                <details className="group rounded-xl border border-line" open={!!(clin.treatment_plan || clin.symptoms || meds.length)}>
                  <summary className="cursor-pointer select-none px-3.5 py-2.5 text-sm font-medium text-ink">Clinical information for the reports <span className="font-normal text-ink-3">(symptoms, treatment, medicines, follow-up)</span></summary>
                  <div className="space-y-3 border-t border-line p-3.5">
                    <p className="text-[11px] leading-relaxed text-ink-3">These are the source for both versions. The patient report shows treatment, medicines, next steps, follow-up and warning signs in your exact words. Anything left empty is reported as not recorded.</p>
                    <div className="grid gap-3 sm:grid-cols-2">
                      <div><label className="label" htmlFor="sy">Symptoms</label><textarea id="sy" className="input min-h-14" value={clin.symptoms} onChange={(e) => setClin({ ...clin, symptoms: e.target.value })} /></div>
                      <div><label className="label" htmlFor="hx">Relevant medical history</label><textarea id="hx" className="input min-h-14" value={clin.history} onChange={(e) => setClin({ ...clin, history: e.target.value })} /></div>
                    </div>
                    <div><label className="label" htmlFor="tp">Treatment plan</label><textarea id="tp" className="input min-h-14" value={clin.treatment_plan} onChange={(e) => setClin({ ...clin, treatment_plan: e.target.value })} /></div>
                    <div>
                      <div className="mb-1.5 flex items-center justify-between"><span className="label !mb-0">Medicines</span>
                        <button type="button" onClick={() => setMeds([...meds, { name: "", purpose: "", how_to_take: "", when_to_take: "", duration: "", instructions: "" }])} className="inline-flex items-center gap-1 text-xs text-accent hover:underline"><Plus className="h-3.5 w-3.5" aria-hidden />Add medicine</button>
                      </div>
                      {meds.length === 0 && <p className="text-xs text-ink-3">None recorded.</p>}
                      {meds.map((m, i) => (
                        <div key={i} className="mb-2 grid gap-2 rounded-lg bg-bg p-2.5 sm:grid-cols-3">
                          {([["name", "Medicine name"], ["purpose", "What it is for"], ["how_to_take", "How to take (dose, route)"], ["when_to_take", "When to take"], ["duration", "Duration"], ["instructions", "Important instructions"]] as const).map(([k, ph]) => (
                            <input key={k} aria-label={`${ph}, medicine ${i + 1}`} placeholder={ph} className="input !py-1.5 !text-[13px]" value={m[k] ?? ""} onChange={(e) => setMed(i, k, e.target.value)} />
                          ))}
                          <button type="button" onClick={() => setMeds(meds.filter((_, j) => j !== i))} className="inline-flex items-center gap-1 justify-self-start text-xs text-ink-3 hover:text-urgent"><Trash2 className="h-3.5 w-3.5" aria-hidden />Remove</button>
                        </div>
                      ))}
                    </div>
                    <div className="grid gap-3 sm:grid-cols-2">
                      <div><label className="label" htmlFor="pi">What the patient should do next</label><textarea id="pi" className="input min-h-14" value={clin.patient_instructions} onChange={(e) => setClin({ ...clin, patient_instructions: e.target.value })} /></div>
                      <div><label className="label" htmlFor="fu">Follow-up</label><textarea id="fu" className="input min-h-14" value={clin.follow_up} onChange={(e) => setClin({ ...clin, follow_up: e.target.value })} /></div>
                    </div>
                    <div><label className="label" htmlFor="ws">Warning signs: when the patient should seek help</label><textarea id="ws" className="input min-h-12" value={clin.warning_signs} onChange={(e) => setClin({ ...clin, warning_signs: e.target.value })} /></div>
                  </div>
                </details>
              </fieldset>

              {chosen && (
                <motion.div key={chosen} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} className="rounded-xl border border-line bg-surface-2 p-3.5">
                  <p className="flex items-center gap-2 text-xs font-medium uppercase tracking-wider text-ink-3"><Lightbulb className="h-3.5 w-3.5" aria-hidden />For radiologist consideration</p>
                  <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-ink-2">{d.all_next_steps[chosen].map((s) => <li key={s}>{s}</li>)}</ul>
                  <p className="mt-2 text-[11px] text-ink-3">From a fixed rule table for {CLASS_LABEL[chosen]}. Not generated by a model and not a treatment decision.</p>
                </motion.div>
              )}
              <ErrorNote error={formError} />
              <div className="flex items-center justify-between gap-3">
                <p className="text-xs text-ink-3">Reports are written only from these confirmed fields. <kbd className="rounded bg-surface-2 px-1.5 text-[10px]">Ctrl</kbd>+<kbd className="rounded bg-surface-2 px-1.5 text-[10px]">Enter</kbd> saves.</p>
                <Button type="submit" loading={saving} disabled={signed || notReady}>Save review and draft reports</Button>
              </div>
            </form>
          </Card>
        </div>
      </div>
    </>
  );
}
