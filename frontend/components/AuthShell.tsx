"use client";

import { motion } from "framer-motion";
import { Stethoscope, UserCog, UserRound } from "lucide-react";
import type { Role } from "@/lib/api";
import { cn } from "@/lib/format";
import { LanguageToggle } from "./LanguageToggle";
import { Logo } from "./SiteNav";

export const ROLE_META: Record<Role, { label: string; icon: typeof UserRound; blurb: string }> = {
  patient: { label: "Patient", icon: UserRound, blurb: "View and download the reports your doctor has finalized." },
  doctor: { label: "Doctor", icon: Stethoscope, blurb: "Review assigned scans and finalize reports. Needs administrator approval." },
  admin: { label: "Admin", icon: UserCog, blurb: "Approve doctors and oversee the system." },
};

export function RoleTabs({ role, onChange }: { role: Role; onChange: (r: Role) => void }) {
  return (
    <div role="tablist" aria-label="Account type" className="relative grid grid-cols-3 gap-1 rounded-xl bg-bg p-1">
      {(Object.keys(ROLE_META) as Role[]).map((r) => {
        const M = ROLE_META[r];
        return (
          <button key={r} role="tab" type="button" aria-selected={role === r} onClick={() => onChange(r)}
            className={cn("relative z-10 flex items-center justify-center gap-1.5 rounded-lg px-2 py-2 text-sm transition", role === r ? "text-accent-ink font-semibold" : "text-ink-2 hover:text-ink")}>
            {role === r && <motion.span layoutId="role-pill" className="absolute inset-0 -z-10 rounded-lg bg-accent" transition={{ type: "spring", stiffness: 400, damping: 32 }} />}
            <M.icon className="h-4 w-4" aria-hidden />{M.label}
          </button>
        );
      })}
    </div>
  );
}

export function AuthShell({ title, sub, children }: { title: string; sub: string; children: React.ReactNode }) {
  return (
    <div className="relative grid min-h-[calc(100vh-29px)] lg:grid-cols-2">
      <div className="relative hidden overflow-hidden lg:block">
        <video src="/brain-hero.mp4" poster="/brain-hero.jpg" autoPlay muted loop playsInline className="absolute inset-0 h-full w-full object-cover opacity-50" aria-hidden />
        <div className="absolute inset-0 bg-gradient-to-br from-bg/40 via-bg/70 to-bg" />
        <div className="relative flex h-full flex-col justify-between p-10">
          <Logo />
          <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.2, duration: 0.7 }}>
            <p className="max-w-md font-display text-3xl font-semibold leading-tight">The scan that cannot wait <span className="text-gradient">gets read first.</span></p>
            <p className="mt-3 max-w-md text-sm text-ink-2">Classified by a trained MRI model, reviewed and approved by a doctor every time.</p>
          </motion.div>
        </div>
      </div>
      <div className="grid-bg flex items-center justify-center px-4 py-10">
        <motion.div initial={{ opacity: 0, y: 18 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.5 }} className="card w-full max-w-md p-6 sm:p-8">
          <div className="mb-6 flex items-center justify-between gap-3"><div className="lg:invisible"><Logo /></div><LanguageToggle /></div>
          <h1 className="font-display text-2xl font-semibold tracking-tight">{title}</h1>
          <p className="mt-1 text-sm text-ink-2">{sub}</p>
          <div className="mt-6">{children}</div>
        </motion.div>
      </div>
    </div>
  );
}
