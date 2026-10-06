"use client";

import { AnimatePresence, motion } from "framer-motion";
import { BadgeCheck, Ban, Building2, Check, IdCard, Mail, Stethoscope, UserCheck, X } from "lucide-react";
import { useState } from "react";
import { api, ApiError, type User } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { cn, dateTime } from "@/lib/format";
import { useLive } from "@/lib/useLive";
import { Button, Card, Chip, Empty, ErrorNote, PageHeader, Skeleton } from "./ui";

const STATUS_TONE: Record<User["status"], "good" | "warn" | "neutral"> = { approved: "good", pending: "warn", rejected: "neutral", disabled: "neutral" };

function useDecide(reload: () => void) {
  const [busy, setBusy] = useState("");
  const [error, setError] = useState<ApiError | null>(null);
  const decide = async (id: string, status: string) => {
    setBusy(id + status);
    setError(null);
    try { await api(`/api/users/${id}/status`, { body: { status } }); reload(); } catch (e) { setError(e as ApiError); } finally { setBusy(""); }
  };
  return { busy, error, decide };
}

/** Doctor registrations waiting for an administrator. New ones appear here live. */
export function ApprovalsView() {
  const { data, error, reload } = useLive<{ users: User[] }>("/api/users?role=doctor&status=pending", ["user_updated"]);
  const { busy, error: actError, decide } = useDecide(reload);
  return (
    <>
      <PageHeader title="Doctor approvals" sub="Doctors cannot reach any clinical page until you approve them. Their screen unlocks the moment you do." />
      <ErrorNote error={error ?? actError} className="mb-4" />
      {!data ? <div className="grid gap-4 md:grid-cols-2">{[0, 1].map((i) => <Skeleton key={i} className="h-44" />)}</div>
        : data.users.length === 0 ? <Empty icon={<UserCheck className="h-8 w-8" />} title="No registrations are waiting">New doctor registrations appear here automatically.</Empty>
        : (
          <ul className="grid gap-4 md:grid-cols-2">
            <AnimatePresence>
              {data.users.map((u) => (
                <motion.li key={u.id} layout initial={{ opacity: 0, scale: 0.96 }} animate={{ opacity: 1, scale: 1 }} exit={{ opacity: 0, scale: 0.9, x: 40 }} className="card p-5">
                  <div className="flex items-start gap-3">
                    <span className="grid h-11 w-11 shrink-0 place-items-center rounded-xl bg-accent/15 text-accent"><Stethoscope className="h-5 w-5" aria-hidden /></span>
                    <div className="min-w-0 flex-1">
                      <p className="truncate font-display text-lg font-semibold">{u.full_name}</p>
                      <p className="text-xs text-ink-3">Registered {dateTime(u.created_at)}</p>
                    </div>
                  </div>
                  <dl className="mt-4 space-y-1.5 text-sm text-ink-2">
                    <div className="flex items-center gap-2"><Mail className="h-4 w-4 shrink-0 text-ink-3" aria-hidden /><dd className="truncate">{u.email}</dd></div>
                    <div className="flex items-center gap-2"><IdCard className="h-4 w-4 shrink-0 text-ink-3" aria-hidden /><dd>Licence <span className="font-mono text-ink">{u.license_no}</span></dd></div>
                    <div className="flex items-center gap-2"><BadgeCheck className="h-4 w-4 shrink-0 text-ink-3" aria-hidden /><dd>{u.specialty}</dd></div>
                    {u.hospital && <div className="flex items-center gap-2"><Building2 className="h-4 w-4 shrink-0 text-ink-3" aria-hidden /><dd>{u.hospital}</dd></div>}
                  </dl>
                  <div className="mt-5 flex gap-2">
                    <Button className="flex-1" loading={busy === u.id + "approved"} onClick={() => decide(u.id, "approved")}><Check className="h-4 w-4" aria-hidden />Approve</Button>
                    <Button className="flex-1" variant="ghost" loading={busy === u.id + "rejected"} onClick={() => decide(u.id, "rejected")}><X className="h-4 w-4" aria-hidden />Reject</Button>
                  </div>
                </motion.li>
              ))}
            </AnimatePresence>
          </ul>
        )}
    </>
  );
}

export function UsersView() {
  const { user: me } = useAuth();
  const [role, setRole] = useState("");
  const { data, error, reload } = useLive<{ users: User[] }>(`/api/users${role ? `?role=${role}` : ""}`, ["user_updated"]);
  const { busy, error: actError, decide } = useDecide(reload);
  return (
    <>
      <PageHeader title="Users" sub="Every account in the system. Disabling an account signs it out and blocks sign-in.">
        <div role="tablist" aria-label="Filter by role" className="flex rounded-xl bg-surface p-1">
          {[["", "All"], ["patient", "Patients"], ["doctor", "Doctors"], ["admin", "Admins"]].map(([v, l]) => (
            <button key={v} role="tab" aria-selected={role === v} onClick={() => setRole(v)} className={cn("rounded-lg px-3 py-1.5 text-sm transition", role === v ? "bg-accent font-semibold text-accent-ink" : "text-ink-2 hover:text-ink")}>{l}</button>
          ))}
        </div>
      </PageHeader>
      <ErrorNote error={error ?? actError} className="mb-4" />
      {!data ? <Skeleton className="h-72" /> : (
        <Card className="overflow-x-auto !p-0">
          <table className="w-full min-w-[720px] text-sm">
            <thead><tr className="border-b border-line text-left text-xs uppercase tracking-wider text-ink-3">
              <th className="px-4 py-3 font-medium">Name</th><th className="px-4 py-3 font-medium">Role</th><th className="px-4 py-3 font-medium">Status</th><th className="px-4 py-3 font-medium">Joined</th><th className="px-4 py-3" /></tr></thead>
            <tbody>
              {data.users.map((u, i) => (
                <motion.tr key={u.id} initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: Math.min(i * 0.02, 0.3) }} className="border-b border-line/60 last:border-0 hover:bg-surface-2/50">
                  <td className="px-4 py-3"><p className="font-medium text-ink">{u.full_name}{u.id === me?.id && <span className="ml-2 text-xs text-ink-3">(you)</span>}</p><p className="text-xs text-ink-3">{u.email}</p></td>
                  <td className="px-4 py-3 capitalize text-ink-2">{u.role}{u.specialty ? ` · ${u.specialty}` : ""}</td>
                  <td className="px-4 py-3"><Chip tone={STATUS_TONE[u.status]}>{u.status}</Chip>{!u.email_verified && <span className="ml-1.5"><Chip tone="warn">email not verified</Chip></span>}</td>
                  <td className="px-4 py-3 text-xs tabular-nums text-ink-3">{dateTime(u.created_at)}</td>
                  <td className="px-4 py-3 text-right">
                    {u.id !== me?.id && (u.status === "approved"
                      ? <Button size="sm" variant="ghost" loading={busy === u.id + "disabled"} onClick={() => decide(u.id, "disabled")}><Ban className="h-3.5 w-3.5" aria-hidden />Disable</Button>
                      : <Button size="sm" variant="subtle" loading={busy === u.id + "approved"} onClick={() => decide(u.id, "approved")}><Check className="h-3.5 w-3.5" aria-hidden />{u.status === "pending" ? "Approve" : "Enable"}</Button>)}
                  </td>
                </motion.tr>
              ))}
            </tbody>
          </table>
          {data.users.length === 0 && <p className="p-8 text-center text-sm text-ink-3">No accounts here yet.</p>}
        </Card>
      )}
      <DevOutbox />
    </>
  );
}

/** Shown only while the server has no mail server configured: the verification and reset emails it would have sent. */
function DevOutbox() {
  const { data } = useLive<{ emails: { to: string; subject: string; link: string; at: string }[]; note: string }>("/api/dev/outbox", ["user_updated"]);
  if (!data) return null;   // 404 once SMTP is configured
  return (
    <Card className="mt-5">
      <h3 className="font-display text-base font-semibold">Development email outbox</h3>
      <p className="mt-1 text-xs text-ink-3">{data.note} Set SMTP_HOST and SMTP_FROM in backend/.env to send real email; this panel then disappears.</p>
      {data.emails.length === 0 ? <p className="mt-3 text-sm text-ink-3">No emails yet.</p> : (
        <ul className="mt-3 space-y-2">
          {data.emails.map((m) => (
            <li key={m.link} className="rounded-xl bg-bg p-3 text-sm">
              <p className="text-ink">{m.subject} <span className="text-ink-3">to {m.to} · {dateTime(m.at)}</span></p>
              <a href={m.link} className="mt-1 block break-all font-mono text-xs text-accent hover:underline">{m.link}</a>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
