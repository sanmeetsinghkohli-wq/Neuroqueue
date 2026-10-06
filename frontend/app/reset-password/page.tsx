"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { AuthShell } from "@/components/AuthShell";
import { Button, ErrorNote, Notice } from "@/components/ui";
import { api, type ApiError } from "@/lib/api";

export default function ResetPasswordPage() {
  const [token, setToken] = useState("");
  const [password, setPassword] = useState("");
  const [again, setAgain] = useState("");
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState("");
  const [error, setError] = useState<ApiError | { message: string; hint?: string } | null>(null);

  useEffect(() => {
    setToken(new URLSearchParams(window.location.search).get("token") ?? "");
    window.history.replaceState(null, "", "/reset-password");   // keep the one-time token out of the address bar and history
  }, []);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (password !== again) { setError({ message: "The two passwords do not match." }); return; }
    setBusy(true);
    setError(null);
    try { setDone((await api<{ message: string }>("/api/auth/reset-password", { body: { token, password } })).message); }
    catch (err) { setError(err as ApiError); }
    finally { setBusy(false); }
  };

  return (
    <AuthShell title="Set a new password" sub="Choose a password you do not use anywhere else.">
      {done ? (
        <div className="space-y-4">
          <Notice tone="good">{done} You have been signed out on every device.</Notice>
          <Link href="/login"><Button className="w-full" size="lg">Sign in</Button></Link>
        </div>
      ) : (
        <form onSubmit={submit} className="space-y-4">
          <div><label className="label" htmlFor="np">New password (8 characters or more)</label><input id="np" type="password" required minLength={8} autoComplete="new-password" className="input" value={password} onChange={(e) => setPassword(e.target.value)} /></div>
          <div><label className="label" htmlFor="np2">Repeat the new password</label><input id="np2" type="password" required minLength={8} autoComplete="new-password" className="input" value={again} onChange={(e) => setAgain(e.target.value)} /></div>
          <ErrorNote error={error} />
          <Button type="submit" loading={busy} disabled={!token} className="w-full" size="lg">Change password</Button>
          {!token && <p className="text-center text-xs text-ink-3">Open this page from the link in your email.</p>}
          <Link href="/forgot-password" className="block text-center text-sm text-accent hover:underline">Request a new link</Link>
        </form>
      )}
    </AuthShell>
  );
}
