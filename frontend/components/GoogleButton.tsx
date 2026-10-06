"use client";

import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { useLang } from "@/lib/i18n";

declare global {
  interface Window { google?: any }
}

let scriptPromise: Promise<void> | null = null;
function loadScript(): Promise<void> {
  scriptPromise ??= new Promise((resolve, reject) => {
    const el = document.createElement("script");
    el.src = "https://accounts.google.com/gsi/client?hl=en";
    el.async = true;
    el.onload = () => resolve();
    el.onerror = () => { scriptPromise = null; reject(new Error("Google sign-in could not be loaded.")); };
    document.head.appendChild(el);
  });
  return scriptPromise;
}

/**
 * "Continue with Google". Google returns a signed ID token to this page; we pass it
 * straight to our server, which verifies the signature and audience before trusting it.
 * Always visible. Until the server has a Google client ID, pressing it explains that Google sign-in is not switched on yet.
 */
export function GoogleButton({ onCredential, onError, label = "continue_with" }: { onCredential: (credential: string) => void; onError: (message: string) => void; label?: "continue_with" | "signup_with" }) {
  const { lang } = useLang();
  const holder = useRef<HTMLDivElement>(null);
  const [clientId, setClientId] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);
  const cb = useRef(onCredential);
  cb.current = onCredential;

  useEffect(() => { api("/api/site").then((r) => setClientId(r.google_client_id ?? null)).catch(() => {}).finally(() => setLoaded(true)); }, []);
  useEffect(() => {
    if (!clientId || !holder.current) return;
    let cancelled = false;
    loadScript().then(() => {
      if (cancelled || !holder.current || !window.google) return;
      window.google.accounts.id.initialize({ client_id: clientId, callback: (resp: { credential?: string }) => (resp.credential ? cb.current(resp.credential) : onError("Google sign-in was cancelled.")), ux_mode: "popup" });
      window.google.accounts.id.renderButton(holder.current, { theme: "filled_black", size: "large", shape: "pill", text: label, width: 320, locale: lang });
    }).catch((e) => onError(e.message));
    return () => { cancelled = true; };
  }, [clientId, label, lang]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div>
      <div className="my-4 flex items-center gap-3 text-xs text-ink-3"><span className="h-px flex-1 bg-line" />or<span className="h-px flex-1 bg-line" /></div>
      {clientId ? <div ref={holder} className="flex justify-center" aria-label="Continue with Google" /> : (
        <button type="button" disabled={!loaded}
          onClick={() => onError("Google sign-in is not switched on yet. The site owner needs to add a Google client ID (GOOGLE_CLIENT_ID in backend/.env). Use email and password for now.")}
          className="flex w-full items-center justify-center gap-3 rounded-full border border-line bg-surface-2 px-4 py-2.5 text-sm font-medium text-ink transition hover:brightness-125 disabled:opacity-50">
          <span aria-hidden className="grid h-5 w-5 place-items-center rounded-full bg-white text-[13px] font-bold leading-none text-[#4285F4]">G</span>
          {label === "signup_with" ? "Sign up with Google" : "Continue with Google"}
        </button>
      )}
    </div>
  );
}
