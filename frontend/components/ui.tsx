"use client";

import { motion } from "framer-motion";
import { AlertTriangle, ArrowDownToLine, CheckCircle2, CircleAlert, Clock, Eye, Loader2, Siren } from "lucide-react";
import type { ApiError, Tier } from "@/lib/api";
import { cn, TIER_COLOR, TIER_LABEL } from "@/lib/format";

export function Button({ variant = "primary", size = "md", loading, className, children, ...rest }:
  React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "ghost" | "danger" | "subtle"; size?: "sm" | "md" | "lg"; loading?: boolean }) {
  const styles = {
    primary: "bg-accent text-accent-ink hover:brightness-110 font-semibold shadow-[0_0_0_1px_rgb(56_189_248/0.4),0_8px_24px_-8px_rgb(56_189_248/0.6)]",
    ghost: "border border-line text-ink hover:bg-surface-2",
    subtle: "bg-surface-2 text-ink hover:brightness-125",
    danger: "bg-urgent text-white hover:brightness-110 font-semibold",
  }[variant];
  const sizes = { sm: "px-3 py-1.5 text-xs", md: "px-4 py-2 text-sm", lg: "px-6 py-3 text-base" }[size];
  return (
    <button {...rest} disabled={rest.disabled || loading}
      className={cn("inline-flex items-center justify-center gap-2 rounded-xl transition active:scale-[0.98] disabled:opacity-45 disabled:cursor-not-allowed disabled:active:scale-100", styles, sizes, className)}>
      {loading && <Loader2 className="h-4 w-4 animate-spin" aria-hidden />}
      {children}
    </button>
  );
}

export function Card({ className, children, delay = 0, ...rest }: React.HTMLAttributes<HTMLDivElement> & { delay?: number }) {
  return (
    <motion.div initial={{ opacity: 0, y: 14 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.45, delay, ease: [0.22, 1, 0.36, 1] }}
      className={cn("card p-5", className)} {...(rest as any)}>
      {children}
    </motion.div>
  );
}

export function PageHeader({ title, sub, children }: { title: string; sub?: string; children?: React.ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <motion.div initial={{ opacity: 0, x: -10 }} animate={{ opacity: 1, x: 0 }} transition={{ duration: 0.4 }}>
        <h1 className="font-display text-2xl font-semibold tracking-tight text-ink sm:text-3xl">{title}</h1>
        {sub && <p className="mt-1 max-w-2xl text-sm text-ink-2">{sub}</p>}
      </motion.div>
      {children && <div className="flex flex-wrap items-center gap-2">{children}</div>}
    </div>
  );
}

export function Stat({ label, value, hint, icon, tone, delay = 0 }: { label: string; value: React.ReactNode; hint?: string; icon?: React.ReactNode; tone?: string; delay?: number }) {
  return (
    <Card delay={delay} className="relative overflow-hidden">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-xs font-medium uppercase tracking-wider text-ink-3">{label}</p>
          <p className="mt-2 font-display text-3xl font-semibold tabular-nums text-ink">{value}</p>
          {hint && <p className="mt-1 text-xs text-ink-2">{hint}</p>}
        </div>
        {icon && <div className="rounded-xl bg-surface-2 p-2.5" style={{ color: tone ?? "var(--accent)" }}>{icon}</div>}
      </div>
      {tone && <div className="absolute inset-x-0 bottom-0 h-0.5" style={{ background: tone }} />}
    </Card>
  );
}

const TIER_ICON: Record<Tier, React.ReactNode> = {
  URGENT: <Siren className="h-3.5 w-3.5" aria-hidden />,
  REVIEW: <Eye className="h-3.5 w-3.5" aria-hidden />,
  ROUTINE: <ArrowDownToLine className="h-3.5 w-3.5" aria-hidden />,
};

/** Tier is never conveyed by colour alone: icon + word, always. */
export function TierChip({ tier, provisional, size = "md" }: { tier: Tier | null; provisional?: boolean; size?: "sm" | "md" }) {
  if (!tier) {
    return <span className="inline-flex items-center gap-1.5 rounded-full border border-line px-2.5 py-1 text-xs text-ink-3"><Clock className="h-3.5 w-3.5" aria-hidden />Not processed</span>;
  }
  return (
    <span className={cn("inline-flex items-center gap-1.5 rounded-full border font-semibold text-ink", size === "sm" ? "px-2 py-0.5 text-[11px]" : "px-2.5 py-1 text-xs")}
      style={{ borderColor: TIER_COLOR[tier], background: `color-mix(in oklab, ${TIER_COLOR[tier]} 22%, transparent)` }}>
      <span style={{ color: tier === "REVIEW" ? "var(--review)" : "var(--ink)" }}>{TIER_ICON[tier]}</span>
      {TIER_LABEL[tier]}
      {provisional && <span className="ml-0.5 inline-flex items-center gap-1 font-normal text-ink-2"><Loader2 className="h-3 w-3 animate-spin" aria-hidden />finalizing</span>}
    </span>
  );
}

export function Chip({ children, tone = "neutral", title }: { children: React.ReactNode; tone?: "neutral" | "warn" | "info" | "good"; title?: string }) {
  const c = { neutral: "border-line text-ink-2", warn: "border-review/50 text-ink", info: "border-accent/50 text-ink", good: "border-routine/60 text-ink" }[tone];
  return <span title={title} className={cn("inline-flex items-center gap-1 rounded-md border bg-surface-2 px-2 py-0.5 text-[11px]", c)}>{children}</span>;
}

export function ErrorNote({ error, className }: { error: Pick<ApiError, "message" | "hint"> | { message: string; hint?: string } | null; className?: string }) {
  if (!error) return null;
  return (
    <motion.div role="alert" initial={{ opacity: 0, y: -6 }} animate={{ opacity: 1, y: 0 }}
      className={cn("flex items-start gap-2.5 rounded-xl border border-urgent/60 bg-urgent/10 px-3.5 py-2.5 text-sm", className)}>
      <CircleAlert className="mt-0.5 h-4 w-4 shrink-0 text-urgent" aria-hidden />
      <div><p className="font-medium text-ink">{error.message}</p>{error.hint && <p className="mt-0.5 text-ink-2">{error.hint}</p>}</div>
    </motion.div>
  );
}

export function Notice({ tone = "info", children, className }: { tone?: "info" | "warn" | "good"; children: React.ReactNode; className?: string }) {
  const map = { info: ["border-accent/40 bg-accent/10", <CircleAlert key="i" className="h-4 w-4 text-accent" />], warn: ["border-review/50 bg-review/10", <AlertTriangle key="w" className="h-4 w-4 text-review" />],
                good: ["border-routine/50 bg-routine/10", <CheckCircle2 key="g" className="h-4 w-4 text-routine" />] } as const;
  return <div className={cn("flex items-start gap-2.5 rounded-xl border px-3.5 py-2.5 text-sm text-ink", map[tone][0], className)}><span className="mt-0.5 shrink-0" aria-hidden>{map[tone][1]}</span><div>{children}</div></div>;
}

export function Progress({ pct, label }: { pct: number; label?: string }) {
  return (
    <div>
      {label && <div className="mb-1.5 flex justify-between text-xs text-ink-2"><span>{label}</span><span className="tabular-nums">{Math.round(pct)}%</span></div>}
      <div className="h-1.5 overflow-hidden rounded-full bg-surface-2" role="progressbar" aria-valuenow={Math.round(pct)} aria-valuemin={0} aria-valuemax={100}>
        <motion.div className="h-full rounded-full bg-accent" animate={{ width: `${pct}%` }} transition={{ ease: "easeOut", duration: 0.4 }} />
      </div>
    </div>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={cn("shimmer rounded-xl bg-surface-2", className)} />;
}

export function Empty({ icon, title, children }: { icon?: React.ReactNode; title: string; children?: React.ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 rounded-2xl border border-dashed border-line px-6 py-14 text-center">
      {icon && <div className="mb-1 text-ink-3">{icon}</div>}
      <p className="font-medium text-ink">{title}</p>
      {children && <div className="max-w-md text-sm text-ink-2">{children}</div>}
    </div>
  );
}

export function LiveDot({ on, label }: { on: boolean; label?: string }) {
  return (
    <span className="inline-flex items-center gap-2 text-xs text-ink-2" title={on ? "Live connection to the server" : "Reconnecting"}>
      <span className={cn("relative inline-flex h-2 w-2 rounded-full", on ? "bg-routine text-routine pulse-ring" : "bg-review")} />
      {label ?? (on ? "Live" : "Reconnecting")}
    </span>
  );
}
