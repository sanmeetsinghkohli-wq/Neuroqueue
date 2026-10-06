"use client";

import { motion } from "framer-motion";
import { CalendarClock, ClipboardList, HeartPulse, Info, LifeBuoy, ListChecks, Pill, ScanLine, Search, Stethoscope } from "lucide-react";
import type { PatientReport } from "@/lib/api";
import { dateTime } from "@/lib/format";

const ICON: Record<string, typeof Info> = { visit: ClipboardList, found: Search, result: HeartPulse, tests: ScanLine, treatment: Stethoscope, medicines: Pill,
  next: ListChecks, follow_up: CalendarClock, notes: Info, help: LifeBuoy };

/** The patient version of a report: plain language, its own structure. Used in the patient portal and as the doctor's preview. */
export function PatientReportView({ report }: { report: PatientReport }) {
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <p className="font-display text-xl font-semibold text-ink">{report.title}</p>
        <p className="text-xs text-ink-3">Report ID <span className="font-mono">{report.report_no ?? "pending"}</span>{report.signed_at ? ` · approved ${dateTime(report.signed_at)}` : ""}</p>
      </div>
      {report.sections.map((sec, i) => {
        const Icon = ICON[sec.id] ?? Info;
        return (
          <motion.section key={sec.id} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.03 * i }} className="rounded-xl bg-bg p-4">
            <h3 className="flex items-center gap-2 text-sm font-semibold text-ink"><Icon className="h-4 w-4 text-accent" aria-hidden />{sec.title}</h3>
            {sec.headline && <p className="mt-2 font-display text-2xl font-semibold text-ink">{sec.headline}</p>}
            {sec.from_doctor && <p className="mt-2 text-[11px] italic text-ink-3">In your doctor&apos;s words:</p>}
            {sec.text && <p translate={sec.from_doctor || sec.id === "found" ? "no" : undefined} dir={sec.from_doctor || sec.id === "found" ? "auto" : undefined} className="mt-1.5 whitespace-pre-wrap text-[15px] leading-relaxed text-ink-2">{sec.text}</p>}
            {(sec.facts?.length || sec.items?.length) ? <ul className="mt-2 list-disc space-y-1 pl-5 text-[15px] leading-relaxed text-ink-2">{[...(sec.facts ?? []), ...(sec.items ?? [])].map((x) => <li key={x}>{x}</li>)}</ul> : null}
            {sec.medicines?.map((m) => (
              <div key={m.name} className="mt-3 overflow-hidden rounded-lg border border-line">
                <p translate="no" dir="auto" className="bg-accent/10 px-3 py-2 font-semibold text-ink">{m.name}</p>
                <dl>{m.details.map((d) => (
                  <div key={d.label} className="grid grid-cols-[140px_1fr] gap-3 border-t border-line px-3 py-2 text-sm"><dt className="text-ink-3">{d.label}</dt><dd translate={d.value === "Not provided" ? undefined : "no"} dir="auto" className="text-ink">{d.value}</dd></div>
                ))}</dl>
              </div>
            ))}
          </motion.section>
        );
      })}
    </div>
  );
}
