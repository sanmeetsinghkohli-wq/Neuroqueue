"use client";

import { motion } from "framer-motion";
import { CircleAlert, Loader2, MailCheck } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { AuthShell } from "@/components/AuthShell";
import { Button, Notice } from "@/components/ui";
import { api, type ApiError, type User } from "@/lib/api";
import { portalPath, useAuth } from "@/lib/auth";

export default function VerifyEmailPage() {
  const router = useRouter();
  const { setUser } = useAuth();
  const [state, setState] = useState<"working" | "done" | "failed">("working");
  const [error, setError] = useState<ApiError | null>(null);
  const [email, setEmail] = useState("");
  const [resent, setResent] = useState("");
  const ran = useRef(false);

  useEffect(() => {
    if (ran.current) return;
    ran.current = true;
    const token = new URLSearchParams(window.location.search).get("token") ?? "";
    window.history.replaceState(null, "", "/verify-email");   // take the one-time token out of the address bar and history
    api<{ user: User }>("/api/auth/verify-email", { body: { token } })
      .then((r) => { setUser(r.user); setState("done"); setTimeout(() => router.replace(portalPath(r.user.role)), 1800); })
      .catch((e) => { setError(e as ApiError); setState("failed"); });
  }, [router, setUser]);

  const resend = async (e: React.FormEvent) => {
    e.preventDefault();
    try { setResent((await api<{ message: string }>("/api/auth/resend-verification", { body: { email } })).message); }
    catch (err) { setResent((err as ApiError).message); }
  };

  return (
    <AuthShell title="Email verification" sub="Confirming that this email address is yours.">
      {state === "working" && <p className="flex items-center gap-2 text-sm text-ink-2"><Loader2 className="h-4 w-4 animate-spin text-accent" aria-hidden />Verifying your link</p>}
      {state === "done" && (
        <motion.div initial={{ opacity: 0, scale: 0.96 }} animate={{ opacity: 1, scale: 1 }} className="space-y-3 text-center">
          <span className="mx-auto grid h-14 w-14 place-items-center rounded-2xl bg-routine/15 text-routine"><MailCheck className="h-7 w-7" aria-hidden /></span>
          <p className="font-medium text-ink">Your email is verified.</p>
          <p className="text-sm text-ink-2">Taking you to your portal.</p>
        </motion.div>
      )}
      {state === "failed" && (
        <div className="space-y-4">
          <div className="flex items-start gap-2.5 rounded-xl border border-review/50 bg-review/10 px-3.5 py-2.5 text-sm">
            <CircleAlert className="mt-0.5 h-4 w-4 shrink-0 text-review" aria-hidden />
            <div><p className="font-medium text-ink">{error?.message}</p><p className="text-ink-2">{error?.hint}</p></div>
          </div>
          {resent ? <Notice tone="good">{resent}</Notice> : (
            <form onSubmit={resend} className="space-y-3">
              <div><label className="label" htmlFor="ve">Your email address</label><input id="ve" type="email" required className="input" value={email} onChange={(e) => setEmail(e.target.value)} /></div>
              <Button type="submit" variant="subtle" className="w-full">Send a new verification link</Button>
            </form>
          )}
          <Link href="/login" className="block text-center text-sm text-accent hover:underline">Back to sign in</Link>
        </div>
      )}
    </AuthShell>
  );
}
