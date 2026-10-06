"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { AuthShell, ROLE_META, RoleTabs } from "@/components/AuthShell";
import { GoogleButton } from "@/components/GoogleButton";
import { Button, ErrorNote, Notice } from "@/components/ui";
import { api, type ApiError, type Role } from "@/lib/api";
import { portalPath, useAuth } from "@/lib/auth";

function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  const { user, ready, login, google } = useAuth();
  const initial = (["patient", "doctor", "admin"].includes(params.get("role") ?? "") ? params.get("role") : "patient") as Role;
  const [role, setRole] = useState<Role>(initial);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | { message: string; hint?: string; code?: string } | null>(null);
  const [resent, setResent] = useState("");

  useEffect(() => { if (ready && user) router.replace(portalPath(user.role)); }, [ready, user, router]);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setResent("");
    try {
      const u = await login(email, password, role);
      router.replace(portalPath(u.role));
    } catch (err) {
      setError(err as ApiError);
      setBusy(false);
    }
  };

  const resend = async () => {
    try { setResent((await api<{ message: string }>("/api/auth/resend-verification", { body: { email } })).message); }
    catch (err) { setError(err as ApiError); }
  };

  const withGoogle = async (credential: string) => {
    setError(null);
    try { router.replace(portalPath((await google(credential, { role })).role)); }
    catch (err) {
      const e = err as ApiError;
      setError(e.code === "MISSING_CREDENTIALS" || e.code === "INVALID_ADMIN_CODE"
        ? { message: "No account exists for this Google address yet.", hint: `Create a ${role} account on the Register page first; you can use Google there too.` } : e);
    }
  };

  const unverified = (error as ApiError | null)?.code === "EMAIL_NOT_VERIFIED";
  return (
    <AuthShell title="Sign in" sub={ROLE_META[role].blurb}>
      <form onSubmit={submit} className="space-y-4">
        <RoleTabs role={role} onChange={(r) => { setRole(r); setError(null); }} />
        <div><label className="label" htmlFor="email">Email</label><input id="email" type="email" autoComplete="email" required className="input" value={email} onChange={(e) => setEmail(e.target.value)} /></div>
        <div>
          <div className="flex items-baseline justify-between"><label className="label" htmlFor="password">Password</label><Link href="/forgot-password" className="text-xs text-accent hover:underline">Forgot password?</Link></div>
          <input id="password" type="password" autoComplete="current-password" required className="input" value={password} onChange={(e) => setPassword(e.target.value)} />
        </div>
        <ErrorNote error={error} />
        {unverified && !resent && <Button type="button" variant="subtle" className="w-full" onClick={resend}>Resend verification email</Button>}
        {resent && <Notice tone="good">{resent}</Notice>}
        <Button type="submit" loading={busy} className="w-full" size="lg">Sign in as {ROLE_META[role].label.toLowerCase()}</Button>
      </form>
      <GoogleButton onCredential={withGoogle} onError={(m) => setError({ message: m })} />
      <p className="mt-5 text-center text-sm text-ink-2">New here? <Link href={`/register?role=${role}`} className="text-accent hover:underline">Create an account</Link></p>
    </AuthShell>
  );
}

export default function LoginPage() {
  return <Suspense><LoginForm /></Suspense>;
}
