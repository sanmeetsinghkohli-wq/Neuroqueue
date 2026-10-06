"use client";

import { BadgeCheck, KeyRound, LogOut } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { api, type ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { Button, Card, ErrorNote, Notice, PageHeader } from "./ui";

export function AccountSecurity({ standalone = false }: { standalone?: boolean }) {
  const { user, setUser, refresh } = useAuth();
  const router = useRouter();
  const [cur, setCur] = useState("");
  const [next, setNext] = useState("");
  const [busy, setBusy] = useState(false);
  const [ok, setOk] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);

  const change = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true); setError(null); setOk(false);
    try {
      await api("/api/auth/change-password", { body: { current_password: cur, new_password: next } });
      setCur(""); setNext(""); setOk(true);
      await refresh();
    } catch (err) { setError(err as ApiError); } finally { setBusy(false); }
  };
  const everywhere = async () => {
    await api("/api/auth/logout-all", { method: "POST" }).catch(() => {});
    setUser(null);
    router.replace("/login");
  };

  return (
    <>
      {standalone && <PageHeader title="Account" sub="Your sign-in and security settings." />}
      <div className="grid max-w-3xl gap-5 md:grid-cols-2">
        <Card>
          <h2 className="flex items-center gap-2 font-display text-base font-semibold"><KeyRound className="h-4 w-4 text-accent" aria-hidden />{user?.has_password ? "Change password" : "Set a password"}</h2>
          <form onSubmit={change} className="mt-4 space-y-3">
            {user?.has_password && <div><label className="label" htmlFor="cp">Current password</label><input id="cp" type="password" required autoComplete="current-password" className="input" value={cur} onChange={(e) => setCur(e.target.value)} /></div>}
            <div><label className="label" htmlFor="np">New password (8 characters or more)</label><input id="np" type="password" required minLength={8} autoComplete="new-password" className="input" value={next} onChange={(e) => setNext(e.target.value)} /></div>
            <ErrorNote error={error} />
            {ok && <Notice tone="good">Password changed. Other devices have been signed out.</Notice>}
            <Button type="submit" loading={busy}>Save password</Button>
          </form>
        </Card>
        <Card delay={0.05}>
          <h2 className="font-display text-base font-semibold">Sign-in details</h2>
          <dl className="mt-4 space-y-2 text-sm">
            <div className="flex justify-between gap-3"><dt className="text-ink-3">Email</dt><dd className="truncate text-ink">{user?.email}</dd></div>
            <div className="flex justify-between gap-3"><dt className="text-ink-3">Email verified</dt><dd className="inline-flex items-center gap-1 text-ink">{user?.email_verified && <BadgeCheck className="h-4 w-4 text-routine" aria-hidden />}{user?.email_verified ? "Yes" : "No"}</dd></div>
            <div className="flex justify-between gap-3"><dt className="text-ink-3">Google sign-in</dt><dd className="text-ink">{user?.google_linked ? "Linked" : "Not linked"}</dd></div>
          </dl>
          <Button variant="ghost" className="mt-5 w-full" onClick={everywhere}><LogOut className="h-4 w-4" aria-hidden />Sign out on every device</Button>
          <p className="mt-2 text-[11px] text-ink-3">Use this if you signed in on a shared computer or think someone else has access.</p>
        </Card>
      </div>
    </>
  );
}
