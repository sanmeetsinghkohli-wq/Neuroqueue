"use client";

import Link from "next/link";
import { useState } from "react";
import { AuthShell } from "@/components/AuthShell";
import { Button, ErrorNote, Notice } from "@/components/ui";
import { api, type ApiError } from "@/lib/api";

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState("");
  const [error, setError] = useState<ApiError | null>(null);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try { setSent((await api<{ message: string }>("/api/auth/forgot-password", { body: { email } })).message); }
    catch (err) { setError(err as ApiError); }
    finally { setBusy(false); }
  };

  return (
    <AuthShell title="Forgot your password?" sub="We will email you a link to set a new one.">
      {sent ? (
        <div className="space-y-4">
          <Notice tone="good">{sent}</Notice>
          <p className="text-sm text-ink-2">The link works once and expires in 30 minutes.</p>
          <Link href="/login" className="block text-center text-sm text-accent hover:underline">Back to sign in</Link>
        </div>
      ) : (
        <form onSubmit={submit} className="space-y-4">
          <div><label className="label" htmlFor="fp">Email</label><input id="fp" type="email" required autoComplete="email" className="input" value={email} onChange={(e) => setEmail(e.target.value)} /></div>
          <ErrorNote error={error} />
          <Button type="submit" loading={busy} className="w-full" size="lg">Send reset link</Button>
          <Link href="/login" className="block text-center text-sm text-accent hover:underline">Back to sign in</Link>
        </form>
      )}
    </AuthShell>
  );
}
