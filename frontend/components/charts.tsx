"use client";

import { motion } from "framer-motion";
import { Area, AreaChart, Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { CLASS_LABEL, cn, SERIES, TIER_COLOR } from "@/lib/format";
import type { ClassName } from "@/lib/api";
import { Card } from "./ui";

const AXIS = { stroke: "var(--line)", tick: { fill: "var(--ink-3)", fontSize: 11 }, tickLine: false as const };
const GRID = <CartesianGrid stroke="var(--line)" strokeDasharray="2 4" vertical={false} />;
const TOOLTIP = {
  contentStyle: { background: "var(--surface-2)", border: "1px solid var(--line)", borderRadius: 10, fontSize: 12, color: "var(--ink)" },
  labelStyle: { color: "var(--ink-2)", marginBottom: 4 }, itemStyle: { color: "var(--ink)" }, cursor: { fill: "rgb(255 255 255 / 0.04)" },
};
// Legend text stays in ink; only the swatch carries the series colour.
const LEGEND = { wrapperStyle: { fontSize: 12, paddingTop: 6 }, iconType: "circle" as const, iconSize: 8,
  itemSorter: null, formatter: (value: string) => <span style={{ color: "var(--ink-2)" }}>{value}</span> };

export function ChartCard({ title, sub, children, className, delay, height = 240 }: { title: string; sub?: string; children: React.ReactNode; className?: string; delay?: number; height?: number | "auto" }) {
  return (
    <Card delay={delay} className={className}>
      <h3 className="font-display text-base font-semibold text-ink">{title}</h3>
      {sub && <p className="mt-0.5 text-xs text-ink-3">{sub}</p>}
      <div className="mt-4" style={height === "auto" ? undefined : { height }}>{children}</div>
    </Card>
  );
}

/** Ranked horizontal bars with the value written beside each one. */
export function BarList({ data, color = "var(--s1)", unit = "", colors }: { data: { name: string; value: number }[]; color?: string; unit?: string; colors?: Record<string, string> }) {
  const max = Math.max(1, ...data.map((d) => d.value));
  if (!data.length) return <p className="py-8 text-center text-sm text-ink-3">No data yet.</p>;
  return (
    <ul className="space-y-3">
      {data.map((d, i) => (
        <li key={d.name}>
          <div className="mb-1 flex justify-between gap-3 text-xs"><span className="truncate text-ink-2">{d.name}</span><span className="tabular-nums text-ink">{d.value}{unit}</span></div>
          <div className="h-2 overflow-hidden rounded-full bg-surface-2">
            <motion.div className="h-full rounded-full" style={{ background: colors?.[d.name] ?? color }} initial={{ width: 0 }} animate={{ width: `${(d.value / max) * 100}%` }} transition={{ duration: 0.7, delay: i * 0.05, ease: "easeOut" }} />
          </div>
        </li>
      ))}
    </ul>
  );
}

export const TIER_BAR_COLORS = { Urgent: TIER_COLOR.URGENT, Review: TIER_COLOR.REVIEW, Routine: TIER_COLOR.ROUTINE };

export function DailyTierChart({ data }: { data: any[] }) {
  return (
    <ResponsiveContainer>
      <BarChart data={data} barCategoryGap="28%">
        {GRID}<XAxis dataKey="date" {...AXIS} /><YAxis allowDecimals={false} width={28} {...AXIS} axisLine={false} />
        <Tooltip {...TOOLTIP} /><Legend {...LEGEND} />
        <Bar dataKey="Urgent" stackId="t" fill={TIER_COLOR.URGENT} stroke="var(--surface)" strokeWidth={2} />
        <Bar dataKey="Review" stackId="t" fill={TIER_COLOR.REVIEW} stroke="var(--surface)" strokeWidth={2} />
        <Bar dataKey="Routine" stackId="t" fill={TIER_COLOR.ROUTINE} stroke="var(--surface)" strokeWidth={2} />
        <Bar dataKey="Untiered" stackId="t" fill="var(--ink-3)" stroke="var(--surface)" strokeWidth={2} radius={[4, 4, 0, 0]} />
      </BarChart>
    </ResponsiveContainer>
  );
}

export function HourlyChart({ data }: { data: any[] }) {
  return (
    <ResponsiveContainer>
      <LineChart data={data}>
        {GRID}<XAxis dataKey="hour" {...AXIS} minTickGap={24} /><YAxis allowDecimals={false} width={28} {...AXIS} axisLine={false} />
        <Tooltip {...TOOLTIP} cursor={{ stroke: "var(--ink-3)" }} /><Legend {...LEGEND} />
        <Line type="monotone" dataKey="uploaded" name="Uploaded" stroke={SERIES[0]} strokeWidth={2} dot={false} activeDot={{ r: 4 }} />
        <Line type="monotone" dataKey="reviewed" name="Reviewed" stroke={SERIES[1]} strokeWidth={2} dot={false} activeDot={{ r: 4 }} />
      </LineChart>
    </ResponsiveContainer>
  );
}

export function SingleAreaChart({ data, x, y, name }: { data: any[]; x: string; y: string; name: string }) {
  return (
    <ResponsiveContainer>
      <AreaChart data={data}>
        <defs><linearGradient id="areaFill" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="var(--s1)" stopOpacity={0.35} /><stop offset="100%" stopColor="var(--s1)" stopOpacity={0} /></linearGradient></defs>
        {GRID}<XAxis dataKey={x} {...AXIS} /><YAxis allowDecimals={false} width={28} {...AXIS} axisLine={false} />
        <Tooltip {...TOOLTIP} cursor={{ stroke: "var(--ink-3)" }} />
        <Area type="monotone" dataKey={y} name={name} stroke="var(--s1)" strokeWidth={2} fill="url(#areaFill)" />
      </AreaChart>
    </ResponsiveContainer>
  );
}

export function GroupedBars({ data, x, series, unit = "", domain }: { data: any[]; x: string; series: { key: string; name: string }[]; unit?: string; domain?: [number, number] }) {
  return (
    <ResponsiveContainer>
      <BarChart data={data} barGap={2} barCategoryGap="24%">
        {GRID}<XAxis dataKey={x} {...AXIS} minTickGap={4} /><YAxis width={36} {...AXIS} axisLine={false} domain={domain} unit={unit} />
        <Tooltip {...TOOLTIP} formatter={(v) => `${v}${unit}`} />
        {series.length > 1 && <Legend {...LEGEND} />}
        {series.map((s, i) => <Bar key={s.key} dataKey={s.key} name={s.name} fill={SERIES[i]} radius={[4, 4, 0, 0]} maxBarSize={38} />)}
      </BarChart>
    </ResponsiveContainer>
  );
}

export function ReliabilityChart({ rows }: { rows: { confidence: number | null; accuracy: number | null; count: number }[] }) {
  const data = rows.filter((r) => r.count > 0).map((r) => ({ confidence: r.confidence, accuracy: r.accuracy, count: r.count }));
  return (
    <ResponsiveContainer>
      <LineChart data={data} margin={{ left: 4, right: 12, bottom: 14 }}>
        {GRID}
        <XAxis type="number" dataKey="confidence" domain={[0, 1]} {...AXIS} label={{ value: "confidence", position: "insideBottom", offset: -8, fill: "var(--ink-3)", fontSize: 11 }} />
        <YAxis type="number" domain={[0, 1]} width={34} {...AXIS} axisLine={false} label={{ value: "accuracy", angle: -90, position: "insideLeft", fill: "var(--ink-3)", fontSize: 11 }} />
        <ReferenceLine segment={[{ x: 0, y: 0 }, { x: 1, y: 1 }]} stroke="var(--ink-3)" strokeDasharray="4 4" />
        <Tooltip {...TOOLTIP} cursor={{ stroke: "var(--ink-3)" }} formatter={(v, n) => [Number(v).toFixed(3), n]} labelFormatter={(l) => `confidence ${Number(l).toFixed(3)}`} />
        <Line dataKey="accuracy" name="Accuracy in bin" stroke="var(--s1)" strokeWidth={2} dot={{ r: 4, fill: "var(--s1)", stroke: "var(--surface)", strokeWidth: 2 }} />
      </LineChart>
    </ResponsiveContainer>
  );
}

/** Sequential single-hue heat cells; every count is written in the cell. */
export function ConfusionMatrix({ classes, matrix }: { classes: ClassName[]; matrix: number[][] }) {
  const max = Math.max(...matrix.flat(), 1);
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-separate border-spacing-1 text-xs">
        <caption className="sr-only">Confusion matrix: rows are the true class, columns the predicted class</caption>
        <thead>
          <tr><th className="text-left font-normal text-ink-3">true ↓ / predicted →</th>{classes.map((c) => <th key={c} className="px-1 pb-1 font-medium text-ink-2">{CLASS_LABEL[c]}</th>)}</tr>
        </thead>
        <tbody>
          {matrix.map((row, i) => (
            <tr key={classes[i]}>
              <th className="whitespace-nowrap pr-2 text-left font-medium text-ink-2">{CLASS_LABEL[classes[i]]}</th>
              {row.map((v, j) => {
                const t = v / max;
                return (
                  <motion.td key={j} initial={{ opacity: 0, scale: 0.8 }} animate={{ opacity: 1, scale: 1 }} transition={{ delay: 0.03 * (i * 4 + j) }}
                    title={`${v} scans: true ${CLASS_LABEL[classes[i]]}, predicted ${CLASS_LABEL[classes[j]]}`}
                    className={cn("h-12 rounded-lg text-center font-mono text-sm tabular-nums", i !== j && v > 0 && "ring-1 ring-review/70")}
                    style={{ background: `color-mix(in oklab, var(--s1) ${Math.round(8 + t * 80)}%, var(--surface-2))`, color: "var(--ink)" }}>
                    {v}
                  </motion.td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
      <p className="mt-2 text-[11px] text-ink-3">Outlined cells are misclassifications.</p>
    </div>
  );
}
