import type { ClassName, Tier } from "./api";

export const CLASS_LABEL: Record<ClassName, string> = { glioma: "Glioma", meningioma: "Meningioma", pituitary: "Pituitary Tumor", no_tumor: "No Tumor" };
export const CLASS_SHORT: Record<ClassName, string> = { glioma: "Glioma", meningioma: "Meningioma", pituitary: "Pituitary", no_tumor: "No tumor" };
export const CLASSES: ClassName[] = ["glioma", "meningioma", "pituitary", "no_tumor"];
export const TIERS: Tier[] = ["URGENT", "REVIEW", "ROUTINE"];
export const TIER_LABEL: Record<Tier, string> = { URGENT: "Urgent", REVIEW: "Review", ROUTINE: "Routine" };
export const TIER_HINT: Record<Tier, string> = { URGENT: "Read first", REVIEW: "Needs a careful read", ROUTINE: "Read last, still read" };
export const TIER_COLOR: Record<Tier, string> = { URGENT: "var(--urgent)", REVIEW: "var(--review)", ROUTINE: "var(--routine)" };

export const SERIES = ["var(--s1)", "var(--s2)", "var(--s3)", "var(--s4)"];

export const pct = (v: number | null | undefined, digits = 1) => (v == null ? "–" : `${(v * 100).toFixed(digits)}%`);

export function waitLabel(fromIso: string, now: number): string {
  const min = Math.max(0, Math.floor((now - new Date(fromIso).getTime()) / 60000));
  if (min < 1) return "just now";
  if (min < 60) return `${min} min`;
  const h = Math.floor(min / 60);
  return h < 24 ? `${h} h ${min % 60} min` : `${Math.floor(h / 24)} d ${h % 24} h`;
}

export const dateTime = (iso?: string | null) =>
  iso ? new Date(iso).toLocaleString(undefined, { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" }) : "–";
export const timeOnly = (iso: string) => new Date(iso).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", second: "2-digit" });

export const cn = (...parts: (string | false | null | undefined)[]) => parts.filter(Boolean).join(" ");
