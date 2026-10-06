"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import dict from "./ar.json";

export type Lang = "en" | "ar";
const KEY = "nq_lang";

interface LangState { lang: Lang; setLang: (l: Lang) => void; toggle: () => void; t: (s: string) => string }
const Ctx = createContext<LangState>({ lang: "en", setLang: () => {}, toggle: () => {}, t: (s) => s });
export const useLang = () => useContext(Ctx);

// ---------- dictionary ----------
const STRINGS = dict.strings as Record<string, string>;
const norm = (s: string) => s.replace(/\s+/g, " ").trim();
const LOWER = new Map(Object.entries(STRINGS).map(([k, v]) => [k.toLowerCase(), v]));

/** Templates such as "{0} of {1} scans classified" become patterns that capture the variable parts. */
const PATTERNS = Object.entries(dict.templates as Record<string, string>)
  .map(([en, ar]) => {
    const literal = en.replace(/\{\d+\}/g, "");
    const order: number[] = [];
    const src = en.split(/(\{\d+\})/).map((part) => {
      const m = part.match(/^\{(\d+)\}$/);
      if (m) { order.push(Number(m[1])); return "(.+?)"; }
      return part.replace(/[.*+?^${}()|[\]\\]/g, "\\$&").replace(/ /g, "\\s+");
    }).join("");
    return { re: new RegExp(`^${src}$`), ar, order, weight: literal.length };
  })
  .filter((p) => p.weight >= 2)
  .sort((a, b) => b.weight - a.weight);

const cache = new Map<string, string | null>();

/** English -> Arabic for one piece of text, or null when there is no translation (it then stays as it is). */
export function translate(text: string): string | null {
  const key = norm(text);
  if (!key || !/[A-Za-z]{2,}/.test(key)) return null;
  const hit = cache.get(key);
  if (hit !== undefined) return hit;
  let out: string | null = STRINGS[key] ?? LOWER.get(key.toLowerCase()) ?? null;
  if (out === null) {
    for (const p of PATTERNS) {
      const m = key.match(p.re);
      if (!m) continue;
      // very short patterns ("{0} of {1}", "{0} min") only apply to numbers, so they can never rewrite a real sentence
      if (p.weight < 6 && !m.slice(1).every((g) => /^[\d.,:%\s-]+$/.test(g))) continue;
      // captured values (names, numbers, labels) are translated too when they are known phrases
      out = p.ar.replace(/\{(\d+)\}/g, (_, n) => { const v = m[p.order.indexOf(Number(n)) + 1] ?? ""; return translate(v) ?? v; });
      break;
    }
  }
  if (out === null) {
    // "Label:" and "Label (hint)" style leftovers
    const m = key.match(/^(.*?)([:.,!?]|\s*\(.*\))$/);
    if (m && m[1] && m[1] !== key) { const inner = translate(m[1]); if (inner) out = inner + m[2]; }
  }
  cache.set(key, out);
  return out;
}

// ---------- live page translation ----------
const ATTRS = ["placeholder", "aria-label", "title", "alt"] as const;
const SKIP = new Set(["SCRIPT", "STYLE", "TEXTAREA", "CODE", "PRE", "NOSCRIPT"]);
interface Saved { en: string; ar: string }

/**
 * Translates what is on screen without touching the components that render it: every text node and
 * label attribute is looked up in the dictionary, and a MutationObserver keeps up with updates
 * (live queue changes, streamed text, page navigation). Only node text changes, never the element
 * tree, so React keeps working normally. Anything marked translate="no" (names, a doctor's own words,
 * clinical text, file names) is left exactly as written.
 */
function useDomTranslation(lang: Lang) {
  const texts = useRef(new WeakMap<Text, Saved>());
  const attrs = useRef(new WeakMap<Element, Record<string, Saved>>());

  useEffect(() => {
    const T = texts.current, A = attrs.current;
    const blocked = (el: Element | null) => !el || SKIP.has(el.tagName) || !!el.closest('[translate="no"]');

    const doText = (node: Text) => {
      const cur = node.nodeValue ?? "";
      const saved = T.get(node);
      if (lang === "en") {
        if (saved && cur === saved.ar) node.nodeValue = saved.en;
        return;
      }
      if (saved && cur === saved.ar) return;                 // already translated
      if (blocked(node.parentElement)) return;
      const ar = translate(cur);
      if (!ar) return;
      const lead = cur.match(/^\s*/)![0], trail = cur.match(/\s*$/)![0];
      const next = lead + ar + trail;
      T.set(node, { en: cur, ar: next });
      node.nodeValue = next;
    };
    const doAttrs = (el: Element) => {
      for (const name of ATTRS) {
        const cur = el.getAttribute(name);
        if (cur == null) continue;
        const rec = A.get(el) ?? {};
        const saved = rec[name];
        if (lang === "en") { if (saved && cur === saved.ar) el.setAttribute(name, saved.en); continue; }
        if ((saved && cur === saved.ar) || blocked(el)) continue;
        const ar = translate(cur);
        if (!ar) continue;
        rec[name] = { en: cur, ar };
        A.set(el, rec);
        el.setAttribute(name, ar);
      }
    };
    const sweep = (root: Node) => {
      if (root.nodeType === Node.TEXT_NODE) { doText(root as Text); return; }
      if (root.nodeType !== Node.ELEMENT_NODE) return;
      const el = root as Element;
      doAttrs(el);
      const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT | NodeFilter.SHOW_ELEMENT);
      for (let n = walker.nextNode(); n; n = walker.nextNode()) (n.nodeType === Node.TEXT_NODE ? doText(n as Text) : doAttrs(n as Element));
    };

    sweep(document.body);
    if (lang === "en") return;   // originals restored; nothing more to watch
    const obs = new MutationObserver((list) => {
      for (const m of list) {
        if (m.type === "characterData") doText(m.target as Text);
        else if (m.type === "attributes") doAttrs(m.target as Element);
        else m.addedNodes.forEach(sweep);
      }
    });
    obs.observe(document.body, { subtree: true, childList: true, characterData: true, attributes: true, attributeFilter: [...ATTRS] });
    return () => obs.disconnect();
  }, [lang]);
}

export function LangProvider({ children }: { children: React.ReactNode }) {
  const [lang, setLangState] = useState<Lang>("en");

  useEffect(() => {
    try { if (window.localStorage.getItem(KEY) === "ar") setLangState("ar"); } catch { /* storage unavailable */ }
  }, []);
  useEffect(() => {
    document.documentElement.lang = lang;
    document.documentElement.dir = lang === "ar" ? "rtl" : "ltr";
  }, [lang]);
  useDomTranslation(lang);

  const setLang = useCallback((l: Lang) => {
    setLangState(l);
    try { window.localStorage.setItem(KEY, l); } catch { /* storage unavailable */ }
  }, []);
  const value = useMemo<LangState>(() => ({
    lang, setLang, toggle: () => setLang(lang === "ar" ? "en" : "ar"), t: (s) => (lang === "ar" ? translate(s) ?? s : s),
  }), [lang, setLang]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}
