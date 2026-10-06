"use client";

import { ShieldAlert } from "lucide-react";
import { AuthProvider } from "@/lib/auth";
import { LangProvider } from "@/lib/i18n";
import { RealtimeProvider } from "@/lib/realtime";
import { HelpAssistant } from "./HelpAssistant";

export const BANNER_TEXT = "Decision support only, not a diagnosis. Every scan is read by a radiologist.";

/** Persistent on every page. */
export function SafetyBanner() {
  return (
    <div role="note" className="sticky top-0 z-50 flex items-center justify-center gap-2 border-b border-review/40 bg-[#1d1a0b] px-4 py-1.5 text-center text-xs font-medium text-[#fde9a8]">
      <ShieldAlert className="h-3.5 w-3.5 shrink-0" aria-hidden />
      {BANNER_TEXT}
    </div>
  );
}

export function Providers({ children }: { children: React.ReactNode }) {
  return (
    <LangProvider>
      <AuthProvider>
        <RealtimeProvider>
          <SafetyBanner />
          {children}
          <HelpAssistant />
        </RealtimeProvider>
      </AuthProvider>
    </LangProvider>
  );
}
