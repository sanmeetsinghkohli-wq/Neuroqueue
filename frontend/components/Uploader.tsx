"use client";

import { AnimatePresence, motion } from "framer-motion";
import { CheckCircle2, FlaskConical, ImagePlus, Link2, Play, Stethoscope, UploadCloud, UserRound, X } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError } from "@/lib/api";
import { cn } from "@/lib/format";
import { useJob } from "@/lib/realtime";
import { Button, ErrorNote, Notice, PageHeader, Progress } from "./ui";

interface Item { id: string; file: File; url: string; state: "ready" | "uploading" | "done" }
interface Patient { id: string; full_name: string; email: string }
interface Doctor { id: string; full_name: string; email: string; specialty?: string | null; hospital?: string | null }
interface Batch { count: number; doctor: string; patient: string }

/** Administrator-only. The administrator adds the scans and chooses the doctor and the patient; that doctor is then
 *  the only doctor who can open, review and report on them. The API refuses uploads from any other role. */
export function Uploader() {
  const [items, setItems] = useState<Item[]>([]);
  const [drag, setDrag] = useState(false);
  const [busy, setBusy] = useState(false);
  const [demoBusy, setDemoBusy] = useState(false);
  const [error, setError] = useState<ApiError | { message: string; hint?: string } | null>(null);
  const [batches, setBatches] = useState<Batch[]>([]);
  const [patients, setPatients] = useState<Patient[]>([]);
  const [doctors, setDoctors] = useState<Doctor[] | null>(null);
  const [noAccount, setNoAccount] = useState(false);
  const [exam, setExam] = useState({ doctor_id: "", patient_id: "", patient_name: "", patient_age: "", patient_gender: "", exam_type: "MRI Brain", clinical_concern: "", referring_doctor: "" });
  const input = useRef<HTMLInputElement>(null);
  const job = useJob();
  const set = (k: keyof typeof exam) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) => { const v = e.target.value; setExam((x) => ({ ...x, [k]: v })); };

  useEffect(() => {
    api<{ patients: Patient[] }>("/api/patients").then((r) => setPatients(r.patients)).catch(() => {});
    api<{ doctors: Doctor[] }>("/api/doctors").then((r) => setDoctors(r.doctors)).catch(() => setDoctors([]));
  }, []);
  useEffect(() => () => items.forEach((i) => URL.revokeObjectURL(i.url)), []); // eslint-disable-line react-hooks/exhaustive-deps

  /** Thumbnails come from the local file, so they show before the server has seen anything. */
  const add = useCallback((files: FileList | File[]) => {
    const list = Array.from(files);
    const bad = list.filter((f) => !f.type.startsWith("image/"));
    setError(bad.length ? { message: `${bad.length} file(s) skipped: not an image.`, hint: "Upload JPEG or PNG brain MRI slices." } : null);
    setItems((prev) => [...prev, ...list.filter((f) => f.type.startsWith("image/")).map((file) => ({ id: `${file.name}-${file.size}-${Math.random()}`, file, url: URL.createObjectURL(file), state: "ready" as const }))].slice(0, 50));
  }, []);

  const doctor = doctors?.find((d) => d.id === exam.doctor_id);
  const patient = patients.find((p) => p.id === exam.patient_id);
  const patientLabel = noAccount ? exam.patient_name.trim() : patient?.full_name ?? "";
  const readyCount = items.filter((i) => i.state === "ready").length;
  const missing = !doctor ? "Choose the doctor who will read these scans." : !patientLabel ? "Choose the patient these scans belong to." : !readyCount ? "Add at least one MRI image." : "";

  const upload = async () => {
    const ready = items.filter((i) => i.state === "ready");
    if (!ready.length || !doctor || !patientLabel) return;
    setBusy(true);
    setError(null);
    setItems((prev) => prev.map((i) => (i.state === "ready" ? { ...i, state: "uploading" } : i)));
    const form = new FormData();
    ready.forEach((i) => form.append("files", i.file));
    const skip = noAccount ? "patient_id" : "patient_name";
    Object.entries(exam).forEach(([k, v]) => { if (v.trim() && k !== skip) form.append(k, v.trim()); });
    try {
      const r = await api<{ scans: unknown[] }>("/api/scans/batch", { form });
      setBatches((b) => [{ count: r.scans.length, doctor: doctor.full_name, patient: patientLabel }, ...b]);
      setItems((prev) => prev.map((i) => (i.state === "uploading" ? { ...i, state: "done" } : i)));
      job.start("/api/queue/process");   // the trained model classifies the new scans straight away
    } catch (e) {
      setError(e as ApiError);
      setItems((prev) => prev.map((i) => (i.state === "uploading" ? { ...i, state: "ready" } : i)));
    } finally {
      setBusy(false);
    }
  };

  const loadDemo = async () => {
    if (!doctor) return;
    setDemoBusy(true);
    setError(null);
    try {
      const r = await api<{ scans: unknown[] }>("/api/demo/load", { body: { doctor_id: doctor.id } });
      setBatches((b) => [{ count: r.scans.length, doctor: doctor.full_name, patient: "Demo patients" }, ...b]);
      job.start("/api/queue/process");
    } catch (e) { setError(e as ApiError); } finally { setDemoBusy(false); }
  };

  return (
    <>
      <PageHeader title="Upload scans" sub="Add one MRI image or many at once, then choose the doctor who will read them and the patient they belong to. The trained model classifies them, and the assigned doctor reviews them and finalizes the report." />
      <div className="grid gap-5 lg:grid-cols-[1fr_400px]">
        <div>
          <motion.div onDragOver={(e) => { e.preventDefault(); setDrag(true); }} onDragLeave={() => setDrag(false)}
            onDrop={(e) => { e.preventDefault(); setDrag(false); add(e.dataTransfer.files); }}
            onClick={() => input.current?.click()} onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && input.current?.click()} role="button" tabIndex={0}
            aria-label="Choose images to upload" animate={{ scale: drag ? 1.01 : 1 }}
            className={cn("grid cursor-pointer place-items-center rounded-2xl border-2 border-dashed px-6 py-14 text-center transition", drag ? "border-accent bg-accent/10" : "border-line bg-surface hover:border-accent/60")}>
            <motion.span animate={{ y: drag ? -6 : [0, -5, 0] }} transition={drag ? {} : { repeat: Infinity, duration: 2.4 }} className="grid h-14 w-14 place-items-center rounded-2xl bg-accent/15 text-accent"><UploadCloud className="h-7 w-7" aria-hidden /></motion.span>
            <p className="mt-4 font-medium text-ink">Drag and drop MRI images here</p>
            <p className="mt-1 text-sm text-ink-2">or click to browse. One scan or many: JPEG or PNG, up to 15 MB each, 50 per batch.</p>
            <input ref={input} type="file" accept="image/*" multiple hidden onChange={(e) => { if (e.target.files) add(e.target.files); e.target.value = ""; }} />
          </motion.div>

          {items.length > 0 && (
            <ul className="mt-4 grid grid-cols-3 gap-3 sm:grid-cols-4 md:grid-cols-6">
              <AnimatePresence>
                {items.map((it) => (
                  <motion.li key={it.id} layout initial={{ opacity: 0, scale: 0.8 }} animate={{ opacity: 1, scale: 1 }} exit={{ opacity: 0, scale: 0.8 }} className="group relative aspect-square overflow-hidden rounded-xl border border-line bg-black">
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img src={it.url} alt={it.file.name} className={cn("h-full w-full object-cover transition", it.state === "uploading" && "opacity-50")} />
                    {it.state === "uploading" && <div className="shimmer absolute inset-0" />}
                    {it.state === "done" && <span className="absolute right-1.5 top-1.5 grid h-5 w-5 place-items-center rounded-full bg-accent text-accent-ink"><CheckCircle2 className="h-3.5 w-3.5" aria-label="Uploaded" /></span>}
                    {it.state === "ready" && (
                      <button onClick={() => setItems((p) => p.filter((x) => x.id !== it.id))} aria-label={`Remove ${it.file.name}`}
                        className="absolute right-1.5 top-1.5 grid h-5 w-5 place-items-center rounded-full bg-black/70 text-white opacity-0 transition focus:opacity-100 group-hover:opacity-100"><X className="h-3 w-3" /></button>
                    )}
                    <p className="absolute inset-x-0 bottom-0 truncate bg-black/70 px-1.5 py-0.5 font-mono text-[10px] text-white">{it.file.name}</p>
                  </motion.li>
                ))}
              </AnimatePresence>
            </ul>
          )}

          {batches.length > 0 && (
            <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} className="card mt-5 space-y-3 p-5">
              <h2 className="font-display text-base font-semibold">Assigned in this session</h2>
              <ul className="space-y-2">
                {batches.map((b, i) => (
                  <li key={i} className="flex flex-wrap items-center gap-x-2 gap-y-1 rounded-xl border border-line bg-surface-2 px-3 py-2 text-sm">
                    <span className="font-semibold tabular-nums text-ink">{b.count}</span><span className="text-ink-2">scan{b.count === 1 ? "" : "s"}</span>
                    <UserRound className="h-3.5 w-3.5 text-ink-3" aria-hidden /><span translate="no" className="text-ink">{b.patient}</span>
                    <Link2 className="h-3.5 w-3.5 text-accent" aria-hidden />
                    <Stethoscope className="h-3.5 w-3.5 text-ink-3" aria-hidden /><span translate="no" className="text-ink">{b.doctor}</span>
                  </li>
                ))}
              </ul>
              {job.status === "running" ? <Progress pct={job.pct} label={job.stage || "Running the classification model"} />
                : job.status === "done" ? <Notice tone="good">Classified by the trained model. The assigned doctor can now review the scans and finalize the report.</Notice>
                : <Button variant="subtle" onClick={() => job.start("/api/queue/process")}><Play className="h-4 w-4" aria-hidden />Run classification model</Button>}
              <ErrorNote error={job.error} />
              <Link href="/admin/queue" className="block text-sm text-accent hover:underline">Open the queue</Link>
            </motion.div>
          )}
        </div>

        <div className="card h-fit space-y-3.5 p-5">
          <h2 className="font-display text-base font-semibold">Assign doctor and patient</h2>
          <div>
            <label className="label" htmlFor="dr">Doctor who will read the scans</label>
            <select id="dr" className="input" value={exam.doctor_id} onChange={set("doctor_id")} required>
              <option value="">Choose a doctor</option>
              {doctors?.map((d) => <option key={d.id} value={d.id}>{d.full_name}{d.specialty ? ` · ${d.specialty}` : ""}</option>)}
            </select>
            {doctors?.length === 0 && <p className="mt-1 text-[11px] text-review">No approved doctors yet. Approve a doctor registration first.</p>}
            {doctor && <p translate="no" className="mt-1 text-[11px] text-ink-3">{doctor.email}{doctor.hospital ? ` · ${doctor.hospital}` : ""}</p>}
          </div>
          <div>
            <label className="label" htmlFor="pt">Patient</label>
            {noAccount
              ? <input id="pt" className="input" value={exam.patient_name} onChange={set("patient_name")} placeholder="Patient's full name" />
              : (
                <select id="pt" className="input" value={exam.patient_id} onChange={set("patient_id")}>
                  <option value="">Choose a patient</option>
                  {patients.map((p) => <option key={p.id} value={p.id}>{p.full_name} ({p.email})</option>)}
                </select>
              )}
            <label className="mt-1.5 flex items-center gap-2 text-[11px] text-ink-2">
              <input type="checkbox" checked={noAccount} onChange={(e) => setNoAccount(e.target.checked)} />The patient has no account yet
            </label>
            <p className="mt-1 text-[11px] text-ink-3">{noAccount ? "Without an account the patient cannot see the report online." : "The patient sees the finalized report in their portal."}</p>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div><label className="label" htmlFor="pa">Age</label><input id="pa" type="number" min={1} max={129} className="input" value={exam.patient_age} onChange={set("patient_age")} /></div>
            <div><label className="label" htmlFor="pg">Gender</label><select id="pg" className="input" value={exam.patient_gender} onChange={set("patient_gender")}><option value="">Not provided</option><option>Female</option><option>Male</option><option>Other</option></select></div>
          </div>
          <div><label className="label" htmlFor="et">Examination type</label><input id="et" className="input" value={exam.exam_type} onChange={set("exam_type")} /></div>
          <div><label className="label" htmlFor="cc">Clinical concern / reason for examination</label><textarea id="cc" className="input min-h-16" value={exam.clinical_concern} onChange={set("clinical_concern")} placeholder="e.g. persistent headaches for two weeks" /></div>
          <div><label className="label" htmlFor="rd">Referring doctor</label><input id="rd" className="input" value={exam.referring_doctor} onChange={set("referring_doctor")} placeholder="Optional" /></div>
          <p className="text-[11px] text-ink-3">Anything left empty is printed on the report as &ldquo;Not provided&rdquo;. Nothing is filled in automatically.</p>
          <ErrorNote error={error} />
          <Button className="w-full" onClick={upload} loading={busy} disabled={!!missing} title={missing}><ImagePlus className="h-4 w-4" aria-hidden />Upload and assign {readyCount || ""} scan{readyCount === 1 ? "" : "s"}</Button>
          {missing && <p className="text-center text-[11px] text-ink-3">{missing}</p>}
          <div className="border-t border-line pt-3">
            <Button variant="ghost" size="sm" className="w-full" onClick={loadDemo} loading={demoBusy} disabled={!doctor} title="Demo aid: 20 held-out test scans, assigned to the chosen doctor"><FlaskConical className="h-4 w-4" aria-hidden />Load 20 demo scans for this doctor</Button>
          </div>
        </div>
      </div>
    </>
  );
}
