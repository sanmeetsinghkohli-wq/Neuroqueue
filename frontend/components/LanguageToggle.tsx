"use client";

import { Languages } from "lucide-react";
import { useLang } from "@/lib/i18n";
import { cn } from "@/lib/format";

/** One button, the whole site switches between English and Arabic (right-to-left). The choice is remembered. */
export function LanguageToggle({ className }: { className?: string }) {
  const { lang, toggle } = useLang();
  return (
    <button type="button" onClick={toggle} translate="no" lang={lang === "ar" ? "en" : "ar"}
      aria-label={lang === "ar" ? "Switch to English" : "التبديل إلى العربية"}
      className={cn("inline-flex items-center gap-1.5 rounded-xl border border-line px-3 py-2 text-sm font-medium text-ink transition hover:bg-surface-2", className)}>
      <Languages className="h-4 w-4 text-accent" aria-hidden />
      {lang === "ar" ? "English" : "العربية"}
    </button>
  );
}
