"use client";

import { AnimatePresence, motion } from "framer-motion";
import { ChevronDown, Mail, Mic, Phone, Search } from "lucide-react";
import { useMemo, useState } from "react";
import { SUPPORT_EMAIL, SUPPORT_PHONE } from "@/components/HelpAssistant";
import { SiteNav } from "@/components/SiteNav";
import { Card, TierChip } from "@/components/ui";
import { cn } from "@/lib/format";

const SECTIONS: { title: string; items: { q: string; a: string }[] }[] = [
  { title: "The basics", items: [
    { q: "What is NeuroQueue?", a: "An AI-assisted brain MRI reporting system. A trained MRI model classifies each scan, the queue is sorted so the most pressing scans are read first, and a doctor reviews and approves every report." },
    { q: "Who classifies the scan?", a: "Only NeuroQueue's own trained MRI model. It gives one of four classes (glioma, meningioma, pituitary tumor, no tumor) and a confidence. No chatbot or language model looks at the scan or can change the result." },
    { q: "Is the result a diagnosis?", a: "The AI classification is decision support. The doctor reviews it, confirms or overrides it, and approves the final report. Nothing reaches a patient until a doctor has finalized it." },
    { q: "What do the three tiers mean?", a: "Urgent: confident tumor-class classification, or a scan that has waited too long. Review: the model is unsure, so it needs a careful read. Routine: confident no-tumor classification, read last but still read. Routine never means cleared." },
    { q: "Why would a scan be in Review?", a: "Low model confidence, a close call between two classes, an image that looks unlike the training scans, or a no-tumor result that did not clear the stricter routine bar." },
  ] },
  { title: "Accounts", items: [
    { q: "How do I register as a patient?", a: "Choose Register, pick Patient, and fill in your name, email and a password. You can sign in straight away." },
    { q: "How do I register as a doctor?", a: "Choose Register, pick Doctor, and give your medical licence number and specialty. Your account is pending until an administrator approves it. The clinical pages unlock by themselves when you are approved." },
    { q: "How do admins get an account?", a: "Admin registration needs the administrator access code held by the system owner. Admins approve doctors, manage users and oversee the system." },
  ] },
  { title: "For patients", items: [
    { q: "Can I upload my own scan?", a: "No. The clinic administrator uploads MRI scans and links each examination to your account and to your doctor. It then appears on your My reports page." },
    { q: "When will I see my result?", a: "When your doctor has reviewed the scan and approved and finalized the report. Your My reports page updates by itself and shows the approved result, a plain-language summary and the official PDF to download." },
    { q: "What can I see?", a: "Only your own examinations and your own finalized reports. You never see draft reports, raw model output, or anyone else's records." },
  ] },
  { title: "For doctors", items: [
    { q: "Where do my scans come from?", a: "An administrator uploads the MRI images and assigns them to you together with the patient. They appear on your My scans page, already classified by the trained model. You only see scans assigned to you." },
    { q: "What is on the review screen?", a: "The image, the model's probability for every class, an occlusion heatmap toggle, the reasons for the tier, and Confirm or Override. An override needs a reason and never changes the stored model result. Keyboard: C confirm, O override, H heatmap, Ctrl+Enter save." },
    { q: "How are reports written?", a: "Only from the fields you confirmed: finding, size, location and notes, plus a fixed list of follow-up suggestions. Anything you did not record is written as Not provided. The model classification and confidence are printed from the stored result." },
    { q: "What does the report check block?", a: "A different tumor type than you confirmed, any number or location you did not record, subtype names, and malignancy, prognosis, grading or 'cleared' language. Approval stays locked until every check is green." },
    { q: "What happens when I approve and finalize?", a: "The official PDF report is issued with a unique report ID, the patient can view and download it, and the approval is written to the audit chain. Finalized reports cannot be changed." },
  ] },
  { title: "Trust and limits", items: [
    { q: "What is the audit chain?", a: "An append-only log of uploads, classifications, reviews, drafts, approvals and patient access. Each event stores the hash of the previous one, so any edit or deletion breaks the chain and shows on the Audit page." },
    { q: "How accurate is the model?", a: "On 901 held-out test images from the public dataset it was trained on, it classified 98.7% correctly. It is sometimes wrong, which is why a doctor reviews every scan. It uses no patient history and its performance on other scanners is unknown." },
  ] },
];

export default function HelpPage() {
  const [q, setQ] = useState("");
  const [open, setOpen] = useState<string | null>("What is NeuroQueue?");
  const filtered = useMemo(() => {
    const k = q.trim().toLowerCase();
    return SECTIONS.map((s) => ({ ...s, items: s.items.filter((i) => !k || i.q.toLowerCase().includes(k) || i.a.toLowerCase().includes(k)) })).filter((s) => s.items.length);
  }, [q]);

  return (
    <div>
      <SiteNav />
      <main className="mx-auto w-[min(900px,calc(100%-2rem))] py-14">
        <motion.div initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }}>
          <h1 className="font-display text-4xl font-semibold tracking-tight">Help</h1>
          <p className="mt-2 text-ink-2">How NeuroQueue works, page by page. For anything else, open the Help assistant in the corner and ask, by text or by voice.</p>
        </motion.div>

        <div className="relative mt-6">
          <Search className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-3" aria-hidden />
          <input className="input !pl-10" placeholder="Search the help guide" aria-label="Search the help guide" value={q} onChange={(e) => setQ(e.target.value)} />
        </div>

        <Card className="mt-6" delay={0.1}>
          <p className="text-xs font-medium uppercase tracking-wider text-ink-3">The tiers at a glance</p>
          <div className="mt-3 grid gap-3 sm:grid-cols-3">
            <div><TierChip tier="URGENT" /><p className="mt-1.5 text-sm text-ink-2">Read first.</p></div>
            <div><TierChip tier="REVIEW" /><p className="mt-1.5 text-sm text-ink-2">Needs a careful read.</p></div>
            <div><TierChip tier="ROUTINE" /><p className="mt-1.5 text-sm text-ink-2">Read last, still read.</p></div>
          </div>
        </Card>

        {filtered.length === 0 && <p className="mt-10 text-center text-ink-3">Nothing matches. Try the Help assistant, or contact support below.</p>}
        {filtered.map((s, si) => (
          <motion.section key={s.title} initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.05 * si }} className="mt-8">
            <h2 className="mb-3 font-display text-xl font-semibold">{s.title}</h2>
            <ul className="space-y-2">
              {s.items.map((it) => {
                const isOpen = open === it.q || !!q;
                return (
                  <li key={it.q} className="card overflow-hidden !rounded-xl">
                    <button onClick={() => setOpen(open === it.q ? null : it.q)} aria-expanded={isOpen} className="flex w-full items-center justify-between gap-3 px-4 py-3 text-left text-sm font-medium text-ink">
                      {it.q}<ChevronDown className={cn("h-4 w-4 shrink-0 text-ink-3 transition-transform", isOpen && "rotate-180")} aria-hidden />
                    </button>
                    <AnimatePresence initial={false}>
                      {isOpen && <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }} exit={{ height: 0, opacity: 0 }} transition={{ duration: 0.22 }} className="overflow-hidden">
                        <p className="px-4 pb-4 text-sm leading-relaxed text-ink-2">{it.a}</p>
                      </motion.div>}
                    </AnimatePresence>
                  </li>
                );
              })}
            </ul>
          </motion.section>
        ))}

        <Card className="mt-10">
          <h2 className="font-display text-xl font-semibold">Still stuck?</h2>
          <p className="mt-1 flex items-center gap-2 text-sm text-ink-2"><Mic className="h-4 w-4 text-accent" aria-hidden />Tap Help in the corner, then the microphone, and ask out loud.</p>
          <div className="mt-4 flex flex-wrap gap-x-8 gap-y-3 text-sm">
            <a href={`mailto:${SUPPORT_EMAIL}`} className="inline-flex items-center gap-2 text-ink hover:text-accent"><Mail className="h-4 w-4" aria-hidden />{SUPPORT_EMAIL}</a>
            <a href={`tel:${SUPPORT_PHONE.replace(/\s/g, "")}`} className="inline-flex items-center gap-2 text-ink hover:text-accent"><Phone className="h-4 w-4" aria-hidden />{SUPPORT_PHONE}</a>
          </div>
        </Card>
      </main>
    </div>
  );
}
