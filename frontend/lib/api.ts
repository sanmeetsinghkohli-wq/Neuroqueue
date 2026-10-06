/** HTTP calls go to this site's own origin ("/api/..."); Next forwards them to the backend (see next.config.ts). */
export const API = "";
/** The live connection goes straight to the backend. */
export const WS_URL = process.env.NEXT_PUBLIC_WS_URL ?? "ws://localhost:8000/ws";

export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string, public hint: string = "") {
    super(message);
  }
}

async function toError(res: Response): Promise<ApiError> {
  try {
    const j = await res.json();
    return new ApiError(res.status, j.code ?? "ERROR", j.message ?? "Request failed.", j.hint ?? "");
  } catch {
    return new ApiError(res.status, "ERROR", "Request failed.", "");
  }
}

export async function api<T = any>(path: string, opts: { method?: string; body?: unknown; form?: FormData } = {}): Promise<T> {
  let res: Response;
  try {
    res = await fetch(API + path, {
      method: opts.method ?? (opts.body || opts.form ? "POST" : "GET"),
      credentials: "include",   // the session is an HttpOnly cookie; scripts never see or store a token
      headers: opts.body ? { "Content-Type": "application/json" } : {},
      body: opts.form ?? (opts.body ? JSON.stringify(opts.body) : undefined),
    });
  } catch {
    throw new ApiError(0, "NETWORK", "Cannot reach the NeuroQueue server.", "Check that the backend server is running.");
  }
  if (!res.ok) throw await toError(res);
  return res.json();
}

/** URL for an <img>/<a> on the API. The browser attaches the session cookie; nothing secret is put in the URL. */
export const fileUrl = (path: string) => `${API}${path}`;

/** POST and read a newline-delimited JSON token stream. */
export async function streamTokens(path: string, body: unknown, onToken: (t: string) => void, signal?: AbortSignal): Promise<void> {
  let res: Response;
  try {
    res = await fetch(API + path, { method: "POST", credentials: "include", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body ?? {}), signal });
  } catch (e) {
    if ((e as Error).name === "AbortError") return;
    throw new ApiError(0, "NETWORK", "Cannot reach the NeuroQueue server.", "Check your connection and try again.");
  }
  if (!res.ok || !res.body) throw await toError(res);
  const reader = res.body.getReader();
  const dec = new TextDecoder();
  let buf = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    let nl: number;
    while ((nl = buf.indexOf("\n")) >= 0) {
      const line = buf.slice(0, nl).trim();
      buf = buf.slice(nl + 1);
      if (!line) continue;
      const msg = JSON.parse(line);
      if (msg.t) onToken(msg.t);
      if (msg.error) throw new ApiError(503, msg.error.code, msg.error.message, msg.error.hint);
    }
  }
}

export const uid = () => (typeof crypto !== "undefined" && crypto.randomUUID ? crypto.randomUUID() : Math.random().toString(36).slice(2) + Date.now().toString(36));

// ---------- shared types ----------
export type Role = "patient" | "doctor" | "admin";
export type Tier = "URGENT" | "REVIEW" | "ROUTINE";
export type ClassName = "glioma" | "meningioma" | "pituitary" | "no_tumor";

export interface User {
  id: string; email: string; full_name: string; role: Role; status: "pending" | "approved" | "rejected" | "disabled";
  phone?: string | null; specialty?: string | null; license_no?: string | null; hospital?: string | null;
  date_of_birth?: string | null; gender?: string | null; created_at: string; approved_at?: string | null; approved_by_name?: string | null;
  email_verified: boolean; has_password: boolean; google_linked: boolean;
}

export interface Medication { name: string; purpose?: string | null; how_to_take?: string | null; when_to_take?: string | null; duration?: string | null; instructions?: string | null }
export interface PatientSection { id: string; title: string; text?: string; headline?: string; facts?: string[]; items?: string[]; from_doctor?: boolean;
  medicines?: { name: string; details: { label: string; value: string }[] }[] }
export interface PatientReport { title: string; report_no: string | null; status: string; approved_finding: string; exam_type: string; exam_date: string | null;
  doctor: string | null; signed_at: string | null; sections: PatientSection[] }

export interface Scan {
  id: string; filename: string; patient_id: string | null; patient_name: string | null; uploaded_by_name: string; uploaded_at: string;
  assigned_doctor_id: string | null; assigned_doctor_name: string | null;
  status: "pending" | "processing" | "classified" | "reviewed" | "drafted" | "signed" | "failed";
  tier: Tier | null; tier_provisional: boolean; reasons: string[]; notes: string[];
  prediction: { probs: Record<ClassName, number>; top_class: ClassName; top_prob: number; margin_top2: number; model: string; model_version?: string | null } | null;
  exam_type: string | null; clinical_concern: string | null; referring_doctor: string | null; patient_age: number | null; patient_gender: string | null;
  ood: { flag: boolean; reason: string | null } | null;
  heatmap_path: string | null; report_id: string | null; error: string | null; is_demo: boolean; signed_at: string | null;
  review: { decision: "confirm" | "override"; predicted_class: ClassName; final_class: ClassName; override_reason: string | null; size_mm: number | null;
            location: string | null; notes: string | null; reviewer_name: string; at: string;
            symptoms?: string | null; history?: string | null; treatment_plan?: string | null; medications?: Medication[]; follow_up?: string | null;
            patient_instructions?: string | null; warning_signs?: string | null } | null;
}

export interface CheckIssue { code: string; where: "clinical" | "summary"; quote: string; detail: string }
export interface CheckRow { id: string; label: string; status: "pass" | "fail" | "skipped"; issues: CheckIssue[]; detail?: string }
export interface Report {
  id: string; report_no: string | null; scan_id: string; status: "passed" | "blocked" | "signed"; clinical_text: string; patient_summary: string;
  check: { passed: boolean; rows: CheckRow[]; issues: CheckIssue[] }; sources: Record<string, string>; guard: { section: string; phrase: string } | null;
  signed_by_name: string | null; signed_at: string | null;
}

export interface PatientScan {
  id: string; filename: string; uploaded_at: string; status: "signed" | "in_progress"; stage: string;
  exam_type: string | null; clinical_concern: string | null; referring_doctor: string | null; doctor_name?: string | null;
  report?: PatientReport & { id: string; signed_by_name: string };
}

export interface AuditEvent { seq: number; id: string; ts: string; actor_name: string; action: string; scan_id: string | null; details: Record<string, any>; hash: string; prev_hash: string }
