"use client";

import { AnimatePresence, motion } from "framer-motion";
import {
  Activity, BarChart3, ClipboardList, FileClock, Hourglass, LayoutDashboard, LogOut, Menu, ScrollText, UploadCloud, UserCheck, UserRound, Users, X,
} from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import type { Role } from "@/lib/api";
import { portalPath, useAuth } from "@/lib/auth";
import { cn } from "@/lib/format";
import { useRealtime } from "@/lib/realtime";
import { LanguageToggle } from "./LanguageToggle";
import { Logo } from "./SiteNav";
import { Button, LiveDot, Skeleton } from "./ui";

const NAV: Record<Role, { href: string; label: string; icon: typeof Activity }[]> = {
  doctor: [
    { href: "/doctor", label: "Dashboard", icon: LayoutDashboard },
    { href: "/doctor/queue", label: "My scans", icon: ClipboardList }, { href: "/doctor/metrics", label: "Metrics", icon: BarChart3 },
    { href: "/doctor/audit", label: "Audit", icon: ScrollText }, { href: "/doctor/account", label: "Account", icon: UserRound },
  ],
  admin: [
    { href: "/admin", label: "Dashboard", icon: LayoutDashboard }, { href: "/admin/upload", label: "Upload scans", icon: UploadCloud },
    { href: "/admin/approvals", label: "Approvals", icon: UserCheck },
    { href: "/admin/users", label: "Users", icon: Users }, { href: "/admin/queue", label: "Queue", icon: ClipboardList },
    { href: "/admin/metrics", label: "Metrics", icon: BarChart3 }, { href: "/admin/audit", label: "Audit", icon: ScrollText },
    { href: "/admin/account", label: "Account", icon: UserRound },
  ],
  patient: [
    { href: "/patient", label: "Dashboard", icon: LayoutDashboard }, { href: "/patient/scans", label: "My reports", icon: FileClock },
    { href: "/patient/profile", label: "Profile", icon: UserRound },
  ],
};
const ROLE_TITLE: Record<Role, string> = { doctor: "Radiologist", admin: "Administrator", patient: "Patient" };

function PendingApproval() {
  const { user, logout } = useAuth();
  const { connected } = useRealtime();
  return (
    <div className="grid min-h-[70vh] place-items-center px-4">
      <motion.div initial={{ opacity: 0, scale: 0.96 }} animate={{ opacity: 1, scale: 1 }} className="card max-w-lg p-8 text-center">
        <motion.span animate={{ rotate: [0, 180, 180, 360] }} transition={{ repeat: Infinity, duration: 4, times: [0, 0.4, 0.5, 0.9] }}
          className="mx-auto grid h-14 w-14 place-items-center rounded-2xl bg-review/15 text-review"><Hourglass className="h-7 w-7" aria-hidden /></motion.span>
        <h1 className="mt-5 font-display text-2xl font-semibold">Waiting for administrator approval</h1>
        <p className="mt-2 text-sm leading-relaxed text-ink-2">
          Thanks, {user?.full_name}. Your doctor registration (licence {user?.license_no}) is with an administrator.
          This page unlocks by itself the moment you are approved. You do not need to refresh.
        </p>
        <div className="mt-5 flex items-center justify-center gap-4"><LiveDot on={connected} label={connected ? "Listening for approval" : "Reconnecting"} /></div>
        <Button variant="ghost" className="mt-6" onClick={logout}>Sign out</Button>
      </motion.div>
    </div>
  );
}

export function PortalShell({ role, children }: { role: Role; children: React.ReactNode }) {
  const { user, ready, logout } = useAuth();
  const { connected } = useRealtime();
  const router = useRouter();
  const path = usePathname();
  const [open, setOpen] = useState(false);

  useEffect(() => {
    if (!ready) return;
    if (!user) router.replace(`/login?role=${role}`);
    else if (user.role !== role) router.replace(portalPath(user.role));
  }, [ready, user, role, router]);
  useEffect(() => setOpen(false), [path]);

  if (!ready || !user || user.role !== role) {
    return <div className="mx-auto max-w-5xl space-y-4 p-8"><Skeleton className="h-10 w-64" /><Skeleton className="h-40" /><Skeleton className="h-64" /></div>;
  }
  const items = NAV[role];
  const active = (href: string) => (href === `/${role}` ? path === href : path.startsWith(href));
  const locked = user.status !== "approved";

  const nav = (
    <nav aria-label="Portal" className="flex flex-1 flex-col gap-1">
      {items.map((it) => (
        <Link key={it.href} href={it.href} aria-current={active(it.href) ? "page" : undefined}
          className={cn("relative flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm transition", active(it.href) ? "font-medium text-ink" : "text-ink-2 hover:bg-surface-2 hover:text-ink",
            locked && "pointer-events-none opacity-40")}>
          {active(it.href) && <motion.span layoutId={`nav-${role}`} className="absolute inset-0 -z-10 rounded-xl border border-accent/40 bg-accent/10" transition={{ type: "spring", stiffness: 400, damping: 34 }} />}
          <it.icon className={cn("h-4 w-4", active(it.href) && "text-accent")} aria-hidden />{it.label}
        </Link>
      ))}
    </nav>
  );
  const foot = (
    <div className="border-t border-line pt-4">
      <LanguageToggle className="mb-3 w-full justify-center" />
      <div className="mb-3 flex items-center gap-3">
        <span className="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-gradient-to-br from-sky-400 to-indigo-500 text-sm font-semibold text-slate-950">{user.full_name.slice(0, 1).toUpperCase()}</span>
        <div className="min-w-0"><p translate="no" className="truncate text-sm font-medium text-ink">{user.full_name}</p><p className="text-xs text-ink-3">{ROLE_TITLE[role]}</p></div>
      </div>
      <div className="flex items-center justify-between">
        <LiveDot on={connected} />
        <button onClick={async () => { await logout(); router.replace("/"); }} className="inline-flex items-center gap-1.5 rounded-lg px-2 py-1.5 text-xs text-ink-2 hover:bg-surface-2 hover:text-ink"><LogOut className="h-3.5 w-3.5" aria-hidden />Sign out</button>
      </div>
    </div>
  );

  return (
    <div className="flex min-h-[calc(100vh-29px)]">
      <aside className="sticky top-[29px] hidden h-[calc(100vh-29px)] w-60 shrink-0 flex-col gap-6 border-r border-line bg-surface/50 p-4 lg:flex rtl:border-l rtl:border-r-0">
        <Logo href={`/${role}`} />{nav}{foot}
      </aside>

      <div className="min-w-0 flex-1">
        <div className="sticky top-[29px] z-20 flex items-center justify-between border-b border-line bg-bg/90 px-4 py-2.5 backdrop-blur lg:hidden">
          <Logo href={`/${role}`} />
          <div className="flex items-center gap-2"><LanguageToggle className="!px-2.5 !py-1.5" /><button onClick={() => setOpen(true)} aria-label="Open menu" className="rounded-lg p-2 text-ink hover:bg-surface-2"><Menu className="h-5 w-5" /></button></div>
        </div>
        <AnimatePresence>
          {open && (
            <>
              <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={() => setOpen(false)} className="fixed inset-0 z-40 bg-black/60 lg:hidden" />
              <motion.aside initial={{ x: "-100%" }} animate={{ x: 0 }} exit={{ x: "-100%" }} transition={{ type: "spring", stiffness: 340, damping: 36 }}
                className="fixed bottom-0 left-0 top-0 z-50 flex w-64 flex-col gap-6 border-r border-line bg-surface p-4 lg:hidden">
                <div className="flex items-center justify-between"><Logo href={`/${role}`} /><button onClick={() => setOpen(false)} aria-label="Close menu" className="rounded-lg p-2 hover:bg-surface-2"><X className="h-4 w-4" /></button></div>
                {nav}{foot}
              </motion.aside>
            </>
          )}
        </AnimatePresence>

        <main className="mx-auto w-full max-w-[1320px] px-4 pb-24 pt-6 sm:px-6 lg:px-8">
          {locked ? <PendingApproval /> : (
            <motion.div key={path} initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.35, ease: "easeOut" }}>{children}</motion.div>
          )}
        </main>
      </div>
    </div>
  );
}
