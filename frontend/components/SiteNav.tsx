"use client";

import { motion } from "framer-motion";
import Link from "next/link";
import { portalPath, useAuth } from "@/lib/auth";
import { LanguageToggle } from "./LanguageToggle";

/** The NeuroQueue mark: half a brain on the left, a sorted queue on the right, the top (most urgent) row brightest. */
export function LogoMark({ className = "h-9 w-9" }: { className?: string }) {
  return (
    <svg viewBox="0 0 64 64" className={className} aria-hidden>
      <rect width="64" height="64" rx="15" fill="#0B1A33" />
      <path d="M30 13C22 9 14 14 16 22C9 25 9 35 15 38C12 46 20 54 30 51V13Z" fill="none" stroke="#38BDF8" strokeWidth="4.5" strokeLinejoin="round" strokeLinecap="round" />
      <path d="M38 20H55" stroke="#F8FAFC" strokeWidth="5.5" strokeLinecap="round" />
      <path d="M38 32H50" stroke="#7DB7F5" strokeWidth="5.5" strokeLinecap="round" />
      <path d="M38 44H45" stroke="#4A78C8" strokeWidth="5.5" strokeLinecap="round" />
    </svg>
  );
}

export function Logo({ href = "/" }: { href?: string }) {
  return (
    <Link href={href} translate="no" dir="ltr" className="flex items-center gap-2.5" aria-label="NeuroQueue home">
      <LogoMark className="h-9 w-9 rounded-xl shadow-[0_0_24px_-6px_rgb(56_189_248/0.8)] ring-1 ring-sky-400/30" />
      <span className="font-display text-lg font-semibold tracking-tight text-ink">Neuro<span className="text-accent">Queue</span></span>
    </Link>
  );
}

export function SiteNav() {
  const { user } = useAuth();
  return (
    <motion.header initial={{ y: -20, opacity: 0 }} animate={{ y: 0, opacity: 1 }} transition={{ duration: 0.5 }}
      className="glass sticky top-[29px] z-30 mx-auto mt-3 flex w-[min(1180px,calc(100%-1.5rem))] items-center justify-between rounded-2xl px-4 py-2.5">
      <Logo />
      <nav className="hidden items-center gap-6 text-sm text-ink-2 md:flex" aria-label="Main">
        <Link href="/#how" className="transition hover:text-ink">How it works</Link>
        <Link href="/#tiers" className="transition hover:text-ink">Tiers</Link>
        <Link href="/#portals" className="transition hover:text-ink">Portals</Link>
        <Link href="/#safety" className="transition hover:text-ink">Safety</Link>
        <Link href="/help" className="transition hover:text-ink">Help</Link>
      </nav>
      <div className="flex items-center gap-2">
        <LanguageToggle />
        {user ? (
          <Link href={portalPath(user.role)} className="rounded-xl bg-accent px-4 py-2 text-sm font-semibold text-accent-ink transition hover:brightness-110">Open my portal</Link>
        ) : (
          <>
            <Link href="/login" className="rounded-xl px-3 py-2 text-sm text-ink transition hover:bg-surface-2">Sign in</Link>
            <Link href="/register" className="rounded-xl bg-accent px-4 py-2 text-sm font-semibold text-accent-ink transition hover:brightness-110">Register</Link>
          </>
        )}
      </div>
    </motion.header>
  );
}
