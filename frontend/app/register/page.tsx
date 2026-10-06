"use client";

import { AnimatePresence, motion } from "framer-motion";
import { MailCheck } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { AuthShell, ROLE_META, RoleTabs } from "@/components/AuthShell";
import { GoogleButton } from "@/components/GoogleButton";
import { Button, ErrorNote, Notice } from "@/components/ui";
import { api, type ApiError, type Role } from "@/lib/api";
import { portalPath, useAuth } from "@/lib/auth";

function Field({ id, label, ...rest }: { id: string; label: string } & React.InputHTMLAttributes<HTMLInputElement>) {
  return <div><label className="label" htmlFor={id}>{label}</label><input id={id} className="input" {...rest} /></div>;
}

function RegisterForm() {
  const router = useRouter();
  const params = useSearchParams();
  const { register, google } = useAuth();
  const initial = (["patient", "doctor", "admin"].includes(params.get("role") ?? "") ? params.get("role") : "patient") as Role;
  const [role, setRole] = useState<Role>(initial);
  const [f, setF] = useState({ full_name: "", email: "", password: "", phone: "", date_of_birth: "", gender: "", specialty: "", license_no: "", hospital: "", admin_code: "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | { message: string; hint?: string } | null>(null);
  const [sent, setSent] = useState("");
  const [resent, setResent] = useState(false);
  const [delivery, setDelivery] = useState("smtp");
  useEffect(() => { api("/api/site").then((r) => setDelivery(r.email_delivery ?? "smtp")).catch(() => {}); }, []);
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setF({ ...f, [k]: e.target.value });

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const body = Object.fromEntries(Object.entries({ ...f, role }).filter(([, v]) => v !== ""));
      setSent(await register(body));
    } catch (err) {
      setError(err as ApiError);
    } finally {
      setBusy(false);
    }
  };

  const withGoogle = async (credential: string) => {
    setError(null);
    try {
      const extra = Object.fromEntries(Object.entries({ role, specialty: f.specialty, license_no: f.license_no, hospital: f.hospital, admin_code: f.admin_code }).filter(([, v]) => v !== ""));
      router.replace(portalPath((await google(credential, extra)).role));
    } catch (err) { setError(err as ApiError); }
  };

  if (sent) {
    return (
      <AuthShell title="Check your email" sub="One more step before you can sign in.">
        <motion.div initial={{ opacity: 0, scale: 0.96 }} animate={{ opacity: 1, scale: 1 }} className="space-y-4 text-center">
          <span className="mx-auto grid h-14 w-14 place-items-center rounded-2xl bg-accent/15 text-accent"><MailCheck className="h-7 w-7" aria-hidden /></span>
          <p className="text-sm leading-relaxed text-ink-2">{sent}</p>
          <p className="text-sm text-ink-2">Open the link in the email sent to <b className="text-ink">{f.email}</b>. It works once and expires in 24 hours.</p>
          {delivery !== "smtp" && <Notice tone="warn">This server does not have email sending set up yet, so the message was not delivered to your inbox. An administrator can find your verification link under Admin → Users.</Notice>}
          {resent ? <Notice tone="good">If the address can be verified, a new link is on its way.</Notice>
            : <Button variant="subtle" className="w-full" onClick={async () => { await api("/api/auth/resend-verification", { body: { email: f.email } }).catch(() => {}); setResent(true); }}>Resend the email</Button>}
          <Link href={`/login?role=${role}`} className="block text-sm text-accent hover:underline">Back to sign in</Link>
        </motion.div>
      </AuthShell>
    );
  }

  return (
    <AuthShell title="Create your account" sub={ROLE_META[role].blurb}>
      <form onSubmit={submit} className="space-y-4">
        <RoleTabs role={role} onChange={(r) => { setRole(r); setError(null); }} />
        <Field id="name" label="Full name" required minLength={2} autoComplete="name" value={f.full_name} onChange={set("full_name")} />
        <Field id="email" label="Email" type="email" required autoComplete="email" value={f.email} onChange={set("email")} />
        <Field id="password" label="Password (8 characters or more)" type="password" required minLength={8} autoComplete="new-password" value={f.password} onChange={set("password")} />
        <AnimatePresence mode="wait" initial={false}>
          <motion.div key={role} initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: "auto" }} exit={{ opacity: 0, height: 0 }} transition={{ duration: 0.25 }} className="space-y-4 overflow-hidden">
            {role === "patient" && (
              <div className="grid grid-cols-2 gap-3">
                <Field id="dob" label="Date of birth" type="date" value={f.date_of_birth} onChange={set("date_of_birth")} />
                <div>
                  <label className="label" htmlFor="gender">Gender</label>
                  <select id="gender" className="input" value={f.gender} onChange={set("gender")}><option value="">Prefer not to say</option><option>Female</option><option>Male</option><option>Other</option></select>
                </div>
                <div className="col-span-2"><Field id="phone" label="Phone (optional)" type="tel" value={f.phone} onChange={set("phone")} /></div>
              </div>
            )}
            {role === "doctor" && (
              <>
                <div className="grid grid-cols-2 gap-3">
                  <Field id="lic" label="Medical licence number" required value={f.license_no} onChange={set("license_no")} />
                  <Field id="spec" label="Specialty" required placeholder="Neuroradiology" value={f.specialty} onChange={set("specialty")} />
                </div>
                <Field id="hosp" label="Hospital or clinic" value={f.hospital} onChange={set("hospital")} />
                <Notice tone="warn">After you verify your email, an administrator reviews your registration. The clinical pages unlock the moment you are approved.</Notice>
              </>
            )}
            {role === "admin" && (
              <>
                <Field id="code" label="Administrator access code" required type="password" autoComplete="off" value={f.admin_code} onChange={set("admin_code")} />
                <Notice>Admin registration needs the access code held by the system owner.</Notice>
              </>
            )}
          </motion.div>
        </AnimatePresence>
        <ErrorNote error={error} />
        <Button type="submit" loading={busy} className="w-full" size="lg">Create {ROLE_META[role].label.toLowerCase()} account</Button>
        <p className="text-center text-[11px] text-ink-3">We will email you a link to verify your address before you can sign in.</p>
      </form>
      <GoogleButton label="signup_with" onCredential={withGoogle} onError={(m) => setError({ message: m })} />
      <p className="mt-5 text-center text-sm text-ink-2">Already registered? <Link href={`/login?role=${role}`} className="text-accent hover:underline">Sign in</Link></p>
    </AuthShell>
  );
}

export default function RegisterPage() {
  return <Suspense><RegisterForm /></Suspense>;
}
