"use client";

import { motion } from "framer-motion";
import { ArrowRight, Clock, Cpu, Eye, FileSignature, Inbox, Server, Siren, UserCheck, Users } from "lucide-react";
import Link from "next/link";
import { useAuth } from "@/lib/auth";
import { useLang } from "@/lib/i18n";
import { CLASS_SHORT } from "@/lib/format";
import { useLive } from "@/lib/useLive";
import type { ClassName } from "@/lib/api";
import { BarList, ChartCard, DailyTierChart, GroupedBars, HourlyChart, TIER_BAR_COLORS } from "./charts";
import { Button, Card, ErrorNote, LiveDot, PageHeader, Skeleton, Stat } from "./ui";
import { useRealtime } from "@/lib/realtime";

export function StaffDashboard({ role }: { role: "doctor" | "admin" }) {
  const { user } = useAuth();
  const { t, lang } = useLang();
  const { connected } = useRealtime();
  const { data: d, error } = useLive<any>("/api/stats/overview", ["scan_updated", "scan_removed", "user_updated"]);

  if (error) return <ErrorNote error={error} />;
  if (!d) return <div className="grid gap-4 md:grid-cols-4">{[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-28" />)}<Skeleton className="h-72 md:col-span-2" /><Skeleton className="h-72 md:col-span-2" /></div>;

  const hello = new Date().getHours() < 12 ? "Good morning" : new Date().getHours() < 18 ? "Good afternoon" : "Good evening";
  return (
    <>
      <PageHeader title={`${t(hello)}${lang === "ar" ? "،" : ","} ${user?.full_name.split(" ").slice(0, 2).join(" ")}`} sub={role === "doctor" ? "Your worklist at a glance. Every number updates live." : "System overview. Every number updates live."}>
        <LiveDot on={connected} />
        <Link href={`/${role}/queue`}><Button>Open queue <ArrowRight className="h-4 w-4" aria-hidden /></Button></Link>
      </PageHeader>

      {role === "admin" && d.users?.pending_doctors > 0 && (
        <motion.div initial={{ opacity: 0, y: -8 }} animate={{ opacity: 1, y: 0 }} className="mb-5 flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-review/50 bg-review/10 px-4 py-3">
          <p className="flex items-center gap-2 text-sm text-ink"><UserCheck className="h-5 w-5 text-review" aria-hidden /><b>{d.users.pending_doctors}</b> doctor registration{d.users.pending_doctors === 1 ? "" : "s"} waiting for your approval.</p>
          <Link href="/admin/approvals"><Button size="sm">Review now</Button></Link>
        </motion.div>
      )}

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Stat label="Urgent, unread" value={d.urgent_unread} hint="read first" tone="var(--urgent)" icon={<Siren className="h-5 w-5" />} />
        <Stat delay={0.05} label="Review, unread" value={d.review_unread} hint="needs a careful read" tone="var(--review)" icon={<Eye className="h-5 w-5" />} />
        <Stat delay={0.1} label="Routine, unread" value={d.routine_unread} hint="read last, still read" tone="var(--routine)" icon={<Inbox className="h-5 w-5" />} />
        <Stat delay={0.15} label="Longest wait" value={`${Math.round(d.oldest_unread_min)} min`} hint={`${d.unread} unread · ${d.signed} signed`} icon={<Clock className="h-5 w-5" />} />
      </div>

      <div className="mt-5 grid gap-5 xl:grid-cols-3">
        <ChartCard className="xl:col-span-2" title="Scans received per day, by tier" sub="Last 14 days" delay={0.1}><DailyTierChart data={d.daily} /></ChartCard>
        <ChartCard title="Tier split" sub="All classified scans" delay={0.15} height="auto"><BarList data={d.tiers} colors={TIER_BAR_COLORS} /></ChartCard>
        <ChartCard title="Activity by hour" sub="Last 12 hours" delay={0.2}><HourlyChart data={d.hourly.map((h: any) => ({ ...h, hour: new Date(h.t).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" }) }))} /></ChartCard>
        <ChartCard title="Predicted vs radiologist-confirmed" sub="Count of scans per finding" delay={0.25}>
          <GroupedBars x="name" series={[{ key: "predicted", name: "Predicted" }, { key: "confirmed", name: "Confirmed" }]} data={d.predicted_classes.map((c: any) => ({ ...c, name: CLASS_SHORT[c.name as ClassName] }))} />
        </ChartCard>
        <ChartCard title="Why scans were tiered" sub="Verifier reasons" delay={0.3} height="auto"><BarList data={d.reasons.map((r: any) => ({ name: r.name, value: r.value }))} color="var(--s3)" /></ChartCard>
        <ChartCard className="xl:col-span-2" title="Model confidence" sub="Scans per top-class probability band" delay={0.35}><GroupedBars x="bin" series={[{ key: "scans", name: "Scans" }]} data={d.confidence} /></ChartCard>
        <Card delay={0.4}>
          <h3 className="font-display text-base font-semibold">Review outcomes</h3>
          <dl className="mt-3 space-y-2.5 text-sm">
            {[["Reviewed", d.live.reviewed], ["Confirmed", d.live.confirmed], ["Overridden", d.live.overridden], ["Overrides already flagged by the verifier", d.live.errors_caught_by_verifier],
              ...(role === "doctor" ? [["Reviewed by you", d.my_reviews]] : [])].map(([k, v]) => (
              <div key={k as string} className="flex justify-between gap-3"><dt className="text-ink-2">{k}</dt><dd className="tabular-nums font-medium text-ink">{v}</dd></div>
            ))}
          </dl>
          <p className="mt-4 flex items-center gap-2 text-xs text-ink-3"><FileSignature className="h-3.5 w-3.5" aria-hidden />{d.signed} report{d.signed === 1 ? "" : "s"} signed and released</p>
        </Card>
      </div>

      {role === "admin" && d.users && (
        <div className="mt-5 grid gap-5 xl:grid-cols-3">
          <ChartCard title="Accounts by role" sub={`${d.users.total} in total`} height="auto" delay={0.1}><BarList data={d.users.by_role.map((r: any) => ({ name: r.name[0].toUpperCase() + r.name.slice(1), value: r.value }))} color="var(--s1)" /></ChartCard>
          <ChartCard title="New registrations" sub="Last 14 days" delay={0.15}>
            <GroupedBars x="date" series={[{ key: "Patient", name: "Patient" }, { key: "Doctor", name: "Doctor" }, { key: "Admin", name: "Admin" }]} data={d.users.signups.map((s: any) => ({ Patient: 0, Doctor: 0, Admin: 0, ...s }))} />
          </ChartCard>
          <Card delay={0.2}>
            <h3 className="flex items-center gap-2 font-display text-base font-semibold"><Server className="h-4 w-4 text-accent" aria-hidden />System status</h3>
            <dl className="mt-3 space-y-2 text-sm">
              {[["Database", d.system.store === "supabase" ? "Supabase (brain2)" : "Local file store"], ["Classifier", d.system.classifier], ["Model version", d.system.model_version ?? "n/a"],
                ["Report writer", d.system.report_writer], ["Help assistant", d.system.assistant], ["Voice", d.system.voice], ["Thresholds", `tuned on ${d.system.thresholds_source}`],
                ["Connected clients", d.system.connected_clients], ["Running jobs", d.system.running_jobs]].map(([k, v]) => (
                <div key={k as string} className="flex justify-between gap-3"><dt className="flex items-center gap-1.5 text-ink-2">{k === "Classifier" && <Cpu className="h-3.5 w-3.5" aria-hidden />}{k === "Connected clients" && <Users className="h-3.5 w-3.5" aria-hidden />}{k}</dt><dd className="truncate text-right font-mono text-xs text-ink">{String(v)}</dd></div>
              ))}
            </dl>
            {d.system.mock_mode && <p className="mt-3 text-xs text-review">Mock mode is on: no network providers are being called.</p>}
          </Card>
        </div>
      )}
    </>
  );
}
