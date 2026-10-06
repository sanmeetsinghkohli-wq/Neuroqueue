"use client";

import { AnimatePresence, motion, useScroll, useTransform } from "framer-motion";
import {
  ArrowRight, ClipboardCheck, FileSignature, FileText, Fingerprint, Layers, ListOrdered, Mail, Phone, ScanLine,
  ShieldCheck, Stethoscope, UploadCloud, UserRound, UserCog, XCircle,
} from "lucide-react";
import dynamic from "next/dynamic";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { SUPPORT_EMAIL, SUPPORT_PHONE } from "@/components/HelpAssistant";
import { SiteNav, Logo } from "@/components/SiteNav";
import { Button, ErrorNote, Notice, TierChip } from "@/components/ui";
import { api, ApiError, type Tier } from "@/lib/api";
import { pct } from "@/lib/format";

const Brain3D = dynamic(() => import("@/components/Brain3D"), { ssr: false });

const fadeUp = { initial: { opacity: 0, y: 28 }, whileInView: { opacity: 1, y: 0 }, viewport: { once: true, margin: "-80px" }, transition: { duration: 0.6, ease: [0.22, 1, 0.36, 1] as const } };

const STEPS = [
  { icon: UploadCloud, title: "Admin uploads and assigns", text: "An administrator adds one or many MRI scans and chooses the doctor and the patient they belong to." },
  { icon: Layers, title: "One trained model classifies", text: "Our own MRI model gives the classification and its confidence. No chatbot looks at the scan or can change the result." },
  { icon: ListOrdered, title: "Live queue", text: "Scans re-sort as results arrive: Urgent first, then Review, then Routine. Nobody refreshes anything." },
  { icon: Stethoscope, title: "Doctor review", text: "Image, class probabilities, heatmap and the reasons for the tier. The doctor confirms or overrides." },
  { icon: FileText, title: "Checked report", text: "Worded only from the confirmed fields. Missing details are written as Not provided, never invented." },
  { icon: FileSignature, title: "Approve and finalize", text: "The doctor approves, the official PDF is issued, and only then can the patient see it." },
];

const TIER_INFO: { tier: Tier; title: string; text: string }[] = [
  { tier: "URGENT", title: "Read first", text: "A confident tumor-class prediction, or any scan that has waited past the maximum wait time." },
  { tier: "REVIEW", title: "Needs a careful read", text: "Low model confidence, a close call between two classes, or an image unlike the training scans. When in doubt, it lands here." },
  { tier: "ROUTINE", title: "Read last, still read", text: "A confident no-tumor prediction that cleared a stricter bar. Routine never means cleared." },
];

const VIDEOS = [
  { src: "/videos/scanner.mp4", poster: "/videos/scanner.jpg", title: "From scanner to worklist", text: "Scans arrive all day in the order they were taken, not the order they matter." },
  { src: "/videos/doc-1.mp4", poster: "/videos/doc-1.jpg", title: "Signals, not verdicts", text: "The models flag what deserves attention first. The radiologist decides what it is." },
  { src: "/videos/tumor-glow.mp4", poster: "/videos/tumor-glow.jpg", title: "The urgent ones rise", text: "A scan that looks pressing moves to the top of the queue within seconds." },
  { src: "/videos/doc-2.mp4", poster: "/videos/doc-2.jpg", title: "Built to be checked", text: "Every step is logged in a hash-chained audit trail that shows tampering." },
];

const DEMO_ROWS = [
  { id: "a", name: "scan_0412", tier: "ROUTINE" as Tier, wait: 31 }, { id: "b", name: "scan_0413", tier: "URGENT" as Tier, wait: 27 },
  { id: "c", name: "scan_0414", tier: "REVIEW" as Tier, wait: 22 }, { id: "d", name: "scan_0415", tier: "ROUTINE" as Tier, wait: 18 },
  { id: "e", name: "scan_0416", tier: "URGENT" as Tier, wait: 9 },
];
const ORDER: Record<Tier, number> = { URGENT: 0, REVIEW: 1, ROUTINE: 2 };

function QueueIllustration() {
  const [sorted, setSorted] = useState(false);
  useEffect(() => {
    const t = setInterval(() => setSorted((v) => !v), 3200);
    return () => clearInterval(t);
  }, []);
  const rows = sorted ? [...DEMO_ROWS].sort((x, y) => ORDER[x.tier] - ORDER[y.tier] || y.wait - x.wait) : DEMO_ROWS;
  return (
    <div className="card overflow-hidden p-0">
      <div className="flex items-center justify-between border-b border-line px-4 py-3 text-xs text-ink-2">
        <span className="font-medium text-ink">{sorted ? "NeuroQueue order" : "Arrival order"}</span>
        <span>Illustration with made-up scans</span>
      </div>
      <ul className="p-2">
        {rows.map((r) => (
          <motion.li layout key={r.id} transition={{ type: "spring", stiffness: 380, damping: 32 }} className="mb-1.5 flex items-center justify-between rounded-xl bg-surface-2 px-3 py-2.5 text-sm last:mb-0">
            <span className="font-mono text-ink">{r.name}</span>
            <span className="flex items-center gap-3">
              <span className="text-xs tabular-nums text-ink-3">{r.wait} min</span>
              <AnimatePresence mode="wait">
                {sorted ? (
                  <motion.span key="t" initial={{ opacity: 0, scale: 0.8 }} animate={{ opacity: 1, scale: 1 }} exit={{ opacity: 0 }}><TierChip tier={r.tier} size="sm" /></motion.span>
                ) : (
                  <motion.span key="n" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}><TierChip tier={null} /></motion.span>
                )}
              </AnimatePresence>
            </span>
          </motion.li>
        ))}
      </ul>
    </div>
  );
}

function VideoCard({ v, i }: { v: (typeof VIDEOS)[number]; i: number }) {
  const ref = useRef<HTMLVideoElement>(null);
  return (
    <motion.article {...fadeUp} transition={{ ...fadeUp.transition, delay: i * 0.08 }} whileHover={{ y: -6 }}
      onMouseEnter={() => ref.current?.play().catch(() => {})} onMouseLeave={() => ref.current?.pause()}
      className="card group overflow-hidden p-0">
      <div className="relative aspect-video overflow-hidden">
        <video ref={ref} src={v.src} poster={v.poster} muted loop playsInline preload="none" className="h-full w-full object-cover transition duration-700 group-hover:scale-105" aria-label={v.title} />
        <div className="pointer-events-none absolute inset-0 bg-gradient-to-t from-surface via-transparent" />
      </div>
      <div className="p-4">
        <h3 className="font-display font-semibold text-ink">{v.title}</h3>
        <p className="mt-1 text-sm text-ink-2">{v.text}</p>
      </div>
    </motion.article>
  );
}

function ContactForm() {
  const [form, setForm] = useState({ name: "", email: "", message: "" });
  const [state, setState] = useState<"idle" | "sending" | "sent">("idle");
  const [error, setError] = useState<ApiError | null>(null);
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setState("sending");
    setError(null);
    try {
      await api("/api/support/contact", { body: form });
      setState("sent");
    } catch (err) {
      setError(err as ApiError);
      setState("idle");
    }
  };
  if (state === "sent") return <Notice tone="good">Thanks, your message has been received. Support will reply to {form.email}.</Notice>;
  return (
    <form onSubmit={submit} className="space-y-3">
      <div className="grid gap-3 sm:grid-cols-2">
        <div><label className="label" htmlFor="c-name">Name</label><input id="c-name" className="input" required minLength={2} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></div>
        <div><label className="label" htmlFor="c-email">Email</label><input id="c-email" type="email" className="input" required value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} /></div>
      </div>
      <div><label className="label" htmlFor="c-msg">Message</label><textarea id="c-msg" className="input min-h-28" required minLength={5} value={form.message} onChange={(e) => setForm({ ...form, message: e.target.value })} /></div>
      <ErrorNote error={error} />
      <Button type="submit" loading={state === "sending"}>Send message</Button>
    </form>
  );
}

export default function Landing() {
  const { scrollY } = useScroll();
  const brainY = useTransform(scrollY, [0, 600], [0, 90]);
  const brainOpacity = useTransform(scrollY, [0, 500], [1, 0.25]);
  const [model, setModel] = useState<Record<string, number> | null>(null);
  useEffect(() => { api("/api/site").then((r) => setModel(r.model)).catch(() => {}); }, []);

  const stats = model
    ? [
        { v: pct(model.test_accuracy), l: `accuracy on ${model.test_scans} held-out test scans` },
        { v: `${model.errors_caught_by_verifier} of ${model.misclassified}`, l: "model errors routed to a careful read, not to read-last" },
        { v: model.duplicates_removed.toLocaleString(), l: "duplicate images removed before splitting" },
      ]
    : [{ v: "3 tiers", l: "Urgent, Review, Routine" }, { v: "4 classes", l: "glioma, meningioma, pituitary, no tumor" }, { v: "100%", l: "of reports approved by a doctor" }];

  return (
    <div className="relative">
      <SiteNav />

      {/* ---------- hero ---------- */}
      <section className="relative overflow-hidden">
        <div className="grid-bg pointer-events-none absolute inset-0 [mask-image:radial-gradient(ellipse_at_center,black_20%,transparent_72%)]" />
        <div className="pointer-events-none absolute -top-40 left-1/2 h-[520px] w-[820px] -translate-x-1/2 rounded-full bg-sky-500/15 blur-[120px]" />
        <div className="relative mx-auto grid min-h-[calc(100vh-110px)] w-[min(1180px,calc(100%-2rem))] items-center gap-6 py-14 lg:grid-cols-[1.05fr_1fr]">
          <div>
            <motion.p initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.1 }}
              className="inline-flex items-center gap-2 rounded-full border border-line bg-surface px-3 py-1 text-xs text-ink-2">
              <ScanLine className="h-3.5 w-3.5 text-accent" aria-hidden /> Brain MRI triage for radiology queues
            </motion.p>
            <motion.h1 initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.2, duration: 0.7 }}
              className="mt-5 font-display text-4xl font-semibold leading-[1.05] tracking-tight sm:text-6xl">
              The scan that cannot wait <span className="text-gradient">gets read first.</span>
            </motion.h1>
            <motion.p initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.35, duration: 0.7 }} className="mt-5 max-w-xl text-lg leading-relaxed text-ink-2">
              A trained MRI model classifies each brain scan and NeuroQueue sorts the queue into Urgent, Review and Routine in real time. A doctor reviews every scan and approves the official report.
            </motion.p>
            <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.5 }} className="mt-8 flex flex-wrap gap-3">
              <Link href="/register"><Button size="lg">Get started <ArrowRight className="h-4 w-4" aria-hidden /></Button></Link>
              <Link href="/login"><Button size="lg" variant="ghost">Sign in</Button></Link>
            </motion.div>
            <dl className="mt-10 grid max-w-xl grid-cols-3 gap-4">
              {stats.map((s, i) => (
                <motion.div key={s.l} initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.65 + i * 0.1 }}>
                  <dd className="font-display text-2xl font-semibold tabular-nums text-ink sm:text-3xl">{s.v}</dd>
                  <dt className="mt-1 text-xs leading-snug text-ink-3">{s.l}</dt>
                </motion.div>
              ))}
            </dl>
          </div>
          <motion.div style={{ y: brainY, opacity: brainOpacity }} initial={{ opacity: 0, scale: 0.9 }} animate={{ opacity: 1, scale: 1 }} transition={{ duration: 1.1, delay: 0.2 }} className="relative h-[380px] sm:h-[520px]">
            <div className="absolute inset-8 rounded-full bg-indigo-500/20 blur-[90px]" />
            <Brain3D className="absolute inset-0" />
            <p className="absolute bottom-2 left-1/2 -translate-x-1/2 text-[11px] text-ink-3">Interactive 3D illustration. Move your pointer.</p>
          </motion.div>
        </div>
      </section>

      {/* ---------- how it works ---------- */}
      <section id="how" className="mx-auto w-[min(1180px,calc(100%-2rem))] scroll-mt-32 py-20">
        <motion.div {...fadeUp} className="max-w-2xl">
          <h2 className="font-display text-3xl font-semibold tracking-tight sm:text-4xl">From upload to signed report</h2>
          <p className="mt-3 text-ink-2">Six steps with clear roles: the model classifies, the doctor decides, the patient receives the approved report.</p>
        </motion.div>
        <div className="mt-10 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {STEPS.map((s, i) => (
            <motion.div key={s.title} {...fadeUp} transition={{ ...fadeUp.transition, delay: i * 0.07 }} whileHover={{ y: -4 }} className="card relative p-5">
              <span className="absolute right-4 top-4 font-mono text-xs text-ink-3">0{i + 1}</span>
              <span className="grid h-11 w-11 place-items-center rounded-xl bg-accent/12 text-accent"><s.icon className="h-5 w-5" aria-hidden /></span>
              <h3 className="mt-4 font-display text-lg font-semibold">{s.title}</h3>
              <p className="mt-1.5 text-sm leading-relaxed text-ink-2">{s.text}</p>
            </motion.div>
          ))}
        </div>
      </section>

      {/* ---------- tiers ---------- */}
      <section id="tiers" className="scroll-mt-32 border-y border-line bg-surface/40 py-20">
        <div className="mx-auto grid w-[min(1180px,calc(100%-2rem))] items-center gap-10 lg:grid-cols-2">
          <div>
            <motion.h2 {...fadeUp} className="font-display text-3xl font-semibold tracking-tight sm:text-4xl">Three tiers. None of them means "done".</motion.h2>
            <div className="mt-7 space-y-4">
              {TIER_INFO.map((t, i) => (
                <motion.div key={t.tier} {...fadeUp} transition={{ ...fadeUp.transition, delay: i * 0.08 }} className="flex gap-4">
                  <div className="pt-0.5"><TierChip tier={t.tier} /></div>
                  <div><p className="font-medium text-ink">{t.title}</p><p className="mt-0.5 text-sm leading-relaxed text-ink-2">{t.text}</p></div>
                </motion.div>
              ))}
            </div>
            <motion.p {...fadeUp} className="mt-6 text-sm text-ink-3">The thresholds behind these tiers are tuned on a validation set and never on the test set.</motion.p>
          </div>
          <motion.div {...fadeUp}><QueueIllustration /></motion.div>
        </div>
      </section>

      {/* ---------- videos ---------- */}
      <section className="mx-auto w-[min(1180px,calc(100%-2rem))] py-20">
        <motion.div {...fadeUp} className="max-w-2xl">
          <h2 className="font-display text-3xl font-semibold tracking-tight sm:text-4xl">See the idea</h2>
          <p className="mt-3 text-ink-2">Hover a clip to play it. These are illustrative animations, not patient data.</p>
        </motion.div>
        <div className="mt-10 grid gap-4 sm:grid-cols-2">{VIDEOS.map((v, i) => <VideoCard key={v.src} v={v} i={i} />)}</div>
      </section>

      {/* ---------- portals ---------- */}
      <section id="portals" className="scroll-mt-32 border-y border-line bg-surface/40 py-20">
        <div className="mx-auto w-[min(1180px,calc(100%-2rem))]">
          <motion.h2 {...fadeUp} className="font-display text-3xl font-semibold tracking-tight sm:text-4xl">One system, three portals</motion.h2>
          <div className="mt-10 grid gap-4 md:grid-cols-3">
            {[
              { icon: UserRound, role: "patient", title: "Patient", text: "Follow your examination and read the official report once your doctor has finalized it.", points: ["Instant registration", "Status in real time", "Doctor-approved report and PDF"] },
              { icon: Stethoscope, role: "doctor", title: "Doctor", text: "Review each scan assigned to you with the evidence beside it, and finalize official reports.", points: ["Approved by an administrator", "Review, report, finalize", "Sees only assigned scans"] },
              { icon: UserCog, role: "admin", title: "Admin", text: "Approve doctor registrations, manage users and watch the whole system on one dashboard.", points: ["Doctor approvals", "System status and analytics", "One-click 20-scan demo"] },
            ].map((p, i) => (
              <motion.div key={p.role} {...fadeUp} transition={{ ...fadeUp.transition, delay: i * 0.08 }} whileHover={{ y: -6 }} className="card flex flex-col p-6">
                <span className="grid h-12 w-12 place-items-center rounded-2xl bg-gradient-to-br from-sky-400/25 to-indigo-500/25 text-accent"><p.icon className="h-6 w-6" aria-hidden /></span>
                <h3 className="mt-4 font-display text-xl font-semibold">{p.title}</h3>
                <p className="mt-1.5 text-sm leading-relaxed text-ink-2">{p.text}</p>
                <ul className="mt-4 flex-1 space-y-1.5 text-sm text-ink-2">
                  {p.points.map((x) => <li key={x} className="flex items-center gap-2"><ClipboardCheck className="h-4 w-4 shrink-0 text-accent" aria-hidden />{x}</li>)}
                </ul>
                <div className="mt-5 flex gap-2">
                  <Link href={`/login?role=${p.role}`} className="flex-1"><Button variant="ghost" className="w-full">Sign in</Button></Link>
                  <Link href={`/register?role=${p.role}`} className="flex-1"><Button className="w-full">Register</Button></Link>
                </div>
              </motion.div>
            ))}
          </div>
        </div>
      </section>

      {/* ---------- safety ---------- */}
      <section id="safety" className="mx-auto w-[min(1180px,calc(100%-2rem))] scroll-mt-32 py-20">
        <div className="grid gap-10 lg:grid-cols-2">
          <motion.div {...fadeUp}>
            <h2 className="font-display text-3xl font-semibold tracking-tight sm:text-4xl">What it will never do</h2>
            <ul className="mt-6 space-y-3">
              {["Diagnose, or say whether something is malignant", "Mark a scan as cleared, or remove it from the worklist", "Release a report a doctor has not approved", "Put a detail in a report that the doctor did not confirm", "Let a language model classify a scan or change the model\u2019s result"].map((x, i) => (
                <motion.li key={x} {...fadeUp} transition={{ ...fadeUp.transition, delay: i * 0.05 }} className="flex items-start gap-3 text-ink-2"><XCircle className="mt-0.5 h-5 w-5 shrink-0 text-urgent" aria-hidden />{x}</motion.li>
              ))}
            </ul>
          </motion.div>
          <motion.div {...fadeUp} className="card p-6">
            <h3 className="flex items-center gap-2 font-display text-lg font-semibold"><ShieldCheck className="h-5 w-5 text-accent" aria-hidden />Honest about its limits</h3>
            <ul className="mt-4 space-y-2.5 text-sm leading-relaxed text-ink-2">
              <li>Trained on public 2D MRI images from one dataset.</li>
              <li>Uses no patient history or clinical context.</li>
              <li>Performance on other scanners and protocols is unknown.</li>
              <li>Wait-time figures come from a simulation with stated assumptions, not from clinical outcomes.</li>
            </ul>
            <div className="mt-5 flex items-center gap-2 rounded-xl bg-surface-2 px-3 py-2.5 text-sm text-ink-2"><Fingerprint className="h-4 w-4 shrink-0 text-accent" aria-hidden />Every action is written to a hash-chained audit log.</div>
          </motion.div>
        </div>
      </section>

      {/* ---------- contact ---------- */}
      <section id="contact" className="scroll-mt-32 border-t border-line bg-surface/40 py-20">
        <div className="mx-auto grid w-[min(1180px,calc(100%-2rem))] gap-10 lg:grid-cols-2">
          <motion.div {...fadeUp}>
            <h2 className="font-display text-3xl font-semibold tracking-tight sm:text-4xl">Talk to us</h2>
            <p className="mt-3 max-w-md text-ink-2">Questions about the website? Open the Help assistant in the corner, by text or by voice, or reach support directly.</p>
            <div className="mt-6 space-y-3">
              <a href={`mailto:${SUPPORT_EMAIL}`} className="flex items-center gap-3 text-ink hover:text-accent"><span className="grid h-10 w-10 place-items-center rounded-xl bg-surface-2"><Mail className="h-4 w-4" aria-hidden /></span>{SUPPORT_EMAIL}</a>
              <a href={`tel:${SUPPORT_PHONE.replace(/\s/g, "")}`} className="flex items-center gap-3 text-ink hover:text-accent"><span className="grid h-10 w-10 place-items-center rounded-xl bg-surface-2"><Phone className="h-4 w-4" aria-hidden /></span>{SUPPORT_PHONE}</a>
            </div>
          </motion.div>
          <motion.div {...fadeUp} className="card p-6"><ContactForm /></motion.div>
        </div>
      </section>

      <footer className="border-t border-line py-8">
        <div className="mx-auto flex w-[min(1180px,calc(100%-2rem))] flex-wrap items-center justify-between gap-4 text-sm text-ink-3">
          <Logo />
          <p>Decision support only. Not a medical device. Report wording and help assistant powered by Alibaba Cloud Model Studio (Qwen).</p>
          <Link href="/help" className="hover:text-ink">Help</Link>
        </div>
      </footer>
    </div>
  );
}
