"use client";

import { Crosshair, Gauge, Play, ShieldCheck, Target } from "lucide-react";
import { useEffect, useState } from "react";
import { api, ApiError, type ClassName } from "@/lib/api";
import { CLASS_SHORT, pct } from "@/lib/format";
import { useEvents, useJob } from "@/lib/realtime";
import { BarList, ChartCard, ConfusionMatrix, GroupedBars, ReliabilityChart, TIER_BAR_COLORS } from "./charts";
import { Button, Card, ErrorNote, Notice, PageHeader, Progress, Skeleton, Stat } from "./ui";

interface Sim { chart: any[]; policies: Record<string, Record<string, number>>; assumptions: Record<string, any>; disclaimer: string }

export function MetricsView() {
  const [m, setM] = useState<any>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [sim, setSim] = useState<Sim | null>(null);
  const [p, setP] = useState({ arrivals_per_hour: 9, read_minutes: 6, urgent_fraction: 0.25, hours: 8, radiologists: 1 });
  const job = useJob<Sim>();

  const load = () => api("/api/metrics").then((r) => { setM(r); setSim((s) => s ?? r.simulation); setP((cur) => ({ ...cur, ...Object.fromEntries(Object.entries(r.simulation_defaults).filter(([k]) => k in cur)) })); }).catch(setError);
  useEffect(() => { load(); }, []); // eslint-disable-line react-hooks/exhaustive-deps
  // live verifier numbers move as scans are classified and reviewed
  useEvents((msg) => { if (msg.type === "scan_updated" && msg.scan?.prediction !== undefined && ["classified", "reviewed"].includes(msg.scan.status) && !msg.scan.tier_provisional) api("/api/metrics").then((r) => setM(r)).catch(() => {}); });
  useEffect(() => { if (job.status === "done" && job.result) setSim(job.result); }, [job.status, job.result]);

  if (error) return <ErrorNote error={error} />;
  if (!m) return <div className="grid gap-4 md:grid-cols-4">{[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-28" />)}<Skeleton className="h-72 md:col-span-4" /></div>;

  const t = m.model?.test;
  const live = m.live;
  const th = m.thresholds;
  const f = sim?.policies.fcfs, n = sim?.policies.neuroqueue;

  return (
    <>
      <PageHeader title="Metrics" sub="Measured once on a de-duplicated held-out test set. Thresholds were tuned on validation only." />
      {!t && <Notice tone="warn" className="mb-5">No trained model artifacts were found, so model metrics are unavailable. Run <code className="font-mono">python -m ml.train</code>. Live queue statistics below still work.</Notice>}

      {t && (
        <>
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <Stat label="Test accuracy" value={pct(t.accuracy)} hint={`${t.n} held-out scans`} icon={<Target className="h-5 w-5" />} />
            <Stat delay={0.05} label="Tumor recall" value={pct(t.tumor_vs_no_tumor.tumor_recall)} hint="tumor vs no tumor" icon={<Crosshair className="h-5 w-5" />} />
            <Stat delay={0.1} label="Errors caught by verifier" value={`${t.verifier.errors_caught_by_verifier} / ${t.verifier.misclassified}`} hint="misclassified scans sent to Review or Urgent, not read-last" icon={<ShieldCheck className="h-5 w-5" />} />
            <Stat delay={0.15} label="Calibration error (ECE)" value={t.calibration.ece.toFixed(3)} hint={`${t.calibration.ece_uncalibrated.toFixed(3)} before temperature scaling`} icon={<Gauge className="h-5 w-5" />} />
          </div>

          <div className="mt-5 grid gap-5 xl:grid-cols-2">
            <ChartCard title="Per-class precision and recall" sub="Held-out test set" delay={0.1}>
              <GroupedBars x="name" unit="%" domain={[80, 100]} series={[{ key: "recall", name: "Recall" }, { key: "precision", name: "Precision" }]}
                data={(t.classes as ClassName[]).map((c) => ({ name: CLASS_SHORT[c], recall: +(t.per_class[c].recall * 100).toFixed(1), precision: +(t.per_class[c].precision * 100).toFixed(1) }))} />
            </ChartCard>
            <ChartCard title="Confusion matrix" sub="Counts of test scans" delay={0.15} height="auto"><ConfusionMatrix classes={t.classes} matrix={t.confusion_matrix} /></ChartCard>
            <ChartCard title="Calibration" sub={`Reliability after temperature scaling (T = ${t.calibration.temperature}). The dashed line is perfect calibration.`} delay={0.2} height={260}>
              <ReliabilityChart rows={t.calibration.reliability} />
            </ChartCard>
            <Card delay={0.25}>
              <h3 className="font-display text-base font-semibold">How the verifier routed the test set</h3>
              <p className="mt-0.5 text-xs text-ink-3">The same rules the live queue uses</p>
              <div className="mt-4"><BarList colors={TIER_BAR_COLORS} data={[{ name: "Urgent", value: t.verifier.tier_counts.URGENT }, { name: "Review", value: t.verifier.tier_counts.REVIEW }, { name: "Routine", value: t.verifier.tier_counts.ROUTINE }]} /></div>
              <dl className="mt-5 grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
                <dt className="text-ink-3">min confidence</dt><dd className="text-right tabular-nums text-ink">{th.min_conf}</dd>
                <dt className="text-ink-3">min margin</dt><dd className="text-right tabular-nums text-ink">{th.min_margin}</dd>
                <dt className="text-ink-3">routine bar</dt><dd className="text-right tabular-nums text-ink">{th.routine_conf}</dd>
                <dt className="text-ink-3">max wait</dt><dd className="text-right tabular-nums text-ink">{th.max_wait_min} min</dd>
                <dt className="text-ink-3">sent to Review</dt><dd className="text-right tabular-nums text-ink">{pct(t.verifier.review_fraction)}</dd>
                <dt className="text-ink-3">true tumors tiered Routine</dt><dd className="text-right tabular-nums text-ink">{t.verifier.tumors_sent_to_routine} of {t.n - t.per_class.no_tumor.support}</dd>
              </dl>
              <p className="mt-3 text-[11px] text-ink-3">Thresholds tuned on {th.tuned_on}. Dataset: {m.model.dataset.name}; {m.model.dataset.duplicates_removed} duplicates and {m.model.dataset.label_conflicts_removed} conflicting images removed before splitting.</p>
            </Card>
          </div>
        </>
      )}

      {/* ---------- live ---------- */}
      <h2 className="mb-3 mt-8 font-display text-lg font-semibold">Live verifier statistics</h2>
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Stat label="Scans classified" value={live.classified} hint={`${live.reviewed} reviewed`} />
        <Stat label="Confirmed" value={live.confirmed} hint="radiologist agreed" />
        <Stat label="Overridden" value={live.overridden} hint={`${live.errors_caught_by_verifier} had been flagged Review or Urgent`} />
        <Stat label="Flagged for review" value={live.tier_counts.REVIEW} hint="by the model-only triage rules" />
      </div>

      {/* ---------- simulation ---------- */}
      <h2 className="mb-3 mt-8 font-display text-lg font-semibold">Before and after: wait time simulation</h2>
      <div className="grid gap-5 xl:grid-cols-[1.5fr_1fr]">
        <ChartCard title="Minutes waited before a radiologist opens the scan" sub="First-come-first-served vs NeuroQueue order" height={300}>
          {sim && <GroupedBars data={sim.chart} x="metric" series={[{ key: "FCFS", name: "First come, first served" }, { key: "NeuroQueue", name: "NeuroQueue order" }]} />}
        </ChartCard>
        <Card>
          <h3 className="font-display text-base font-semibold">Assumptions</h3>
          <div className="mt-3 space-y-3">
            {([["arrivals_per_hour", "Scans arriving per hour", 2, 40, 1], ["read_minutes", "Minutes to read one scan", 2, 20, 0.5], ["urgent_fraction", "Fraction that are true tumors", 0.05, 0.9, 0.05], ["radiologists", "Radiologists reading", 1, 6, 1]] as const).map(([k, label, min, max, step]) => (
              <div key={k}>
                <div className="mb-1 flex justify-between text-xs"><label htmlFor={k} className="text-ink-2">{label}</label><span className="tabular-nums text-ink">{p[k]}</span></div>
                <input id={k} type="range" min={min} max={max} step={step} value={p[k]} onChange={(e) => setP({ ...p, [k]: Number(e.target.value) })} className="w-full accent-sky-400" />
              </div>
            ))}
          </div>
          {job.status === "running" ? <div className="mt-4"><Progress pct={job.pct} label={job.stage} /></div> : <Button className="mt-4 w-full" variant="subtle" onClick={() => job.start("/api/simulation/run", p)}><Play className="h-4 w-4" aria-hidden />Run simulation</Button>}
          <ErrorNote error={job.error} className="mt-3" />
          {f && n && <p className="mt-4 text-sm text-ink-2">Urgent scans: mean wait <b className="text-ink">{f.urgent_mean_wait_min} min</b> first-come-first-served vs <b className="text-ink">{n.urgent_mean_wait_min} min</b> with NeuroQueue; 90th percentile {f.urgent_p90_wait_min} vs {n.urgent_p90_wait_min} min.</p>}
          {sim && <p className="mt-3 text-[11px] leading-relaxed text-ink-3">{sim.disclaimer} {sim.assumptions.replications} simulated days per policy, {sim.assumptions.hours} h day, {sim.assumptions.arrival_process}. Source: {sim.assumptions.prediction_source}.</p>}
        </Card>
      </div>

      <Card className="mt-5">
        <h3 className="font-display text-base font-semibold">Limits</h3>
        <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-ink-2">{m.limits.map((l: string) => <li key={l}>{l}</li>)}</ul>
      </Card>
    </>
  );
}
