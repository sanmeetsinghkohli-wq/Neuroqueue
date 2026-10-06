"use client";

import { AnimatePresence, motion } from "framer-motion";
import { Bot, LifeBuoy, Mail, Mic, MicOff, Phone, Send, Square, Volume2, VolumeX, X } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, streamTokens } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { cn } from "@/lib/format";
import { useLang } from "@/lib/i18n";
import { Speaker, VoiceSession } from "@/lib/voice";

export const SUPPORT_EMAIL = "2200031362csehh@gmail.com";
export const SUPPORT_PHONE = "+971 528813637";

interface Msg { role: "user" | "assistant"; content: string; streaming?: boolean; error?: boolean }

const SUGGESTIONS: Record<string, string[]> = {
  visitor: ["What does NeuroQueue do?", "What do Urgent, Review and Routine mean?", "How do I register as a doctor?", "Is this a diagnosis?"],
  patient: ["Where can I see my report?", "What does 'awaiting doctor review' mean?", "Can I upload my own scan?", "Who decides my result?"],
  doctor: ["Why is a scan in Review?", "How do I finalize a report?", "What does the report check block?", "What is in the queue right now?"],
  admin: ["How do I approve a doctor?", "How do I load the demo scans?", "What does the audit chain prove?", "What is in the queue right now?"],
};

export function HelpAssistant() {
  const { user } = useAuth();
  const { lang } = useLang();
  const langRef = useRef(lang);
  langRef.current = lang;
  const [open, setOpen] = useState(false);
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [voiceOn, setVoiceOn] = useState(false);
  const [voiceState, setVoiceState] = useState<"idle" | "connecting" | "listening" | "thinking" | "speaking">("idle");
  const [partial, setPartial] = useState("");
  const [level, setLevel] = useState(0);
  const [speak, setSpeak] = useState(true);
  const [voiceError, setVoiceError] = useState("");

  const scroller = useRef<HTMLDivElement>(null);
  const abort = useRef<AbortController | null>(null);
  const session = useRef<VoiceSession | null>(null);
  const speaker = useRef<Speaker | null>(null);
  const msgsRef = useRef<Msg[]>([]);
  const speakRef = useRef(speak);
  msgsRef.current = msgs;
  speakRef.current = speak;

  useEffect(() => { scroller.current?.scrollTo({ top: scroller.current.scrollHeight, behavior: "smooth" }); }, [msgs, partial]);

  const ask = useCallback(async (text: string, spoken = false) => {
    const q = text.trim();
    if (!q) return;
    abort.current?.abort();
    speaker.current?.cancel();
    const history = [...msgsRef.current.filter((m) => !m.error), { role: "user" as const, content: q }];
    setMsgs([...history, { role: "assistant", content: "", streaming: true }]);
    setInput("");
    setPartial("");
    setBusy(true);
    if (spoken) setVoiceState("thinking");
    const ctrl = new AbortController();
    abort.current = ctrl;
    const talk = (spoken || session.current) && speakRef.current ? speaker.current : null;
    const patch = (fn: (m: Msg) => Msg) => setMsgs((prev) => prev.map((m, i) => (i === prev.length - 1 ? fn(m) : m)));
    try {
      await streamTokens("/api/assist/chat", { messages: history.slice(-10).map(({ role, content }) => ({ role, content })), lang: langRef.current }, (t) => {
        patch((m) => ({ ...m, content: m.content + t }));
        talk?.feed(t);
      }, ctrl.signal);
      patch((m) => ({ ...m, streaming: false }));
      if (talk) talk.flush();
      else if (session.current) { session.current.muted = false; setVoiceState("listening"); }
    } catch (e) {
      const err = e as ApiError;
      patch(() => ({ role: "assistant", content: `${err.message} ${err.hint ?? ""}`.trim(), error: true }));
      if (session.current) { session.current.muted = false; setVoiceState("listening"); }
    } finally {
      setBusy(false);
    }
  }, []);

  const stopVoice = useCallback(() => {
    session.current?.stop();
    session.current = null;
    speaker.current?.cancel();
    setVoiceOn(false);
    setVoiceState("idle");
    setPartial("");
    setLevel(0);
  }, []);

  const startVoice = useCallback(async () => {
    setVoiceError("");
    setVoiceOn(true);
    setVoiceState("connecting");
    speaker.current = new Speaker(langRef.current,
      () => { if (session.current) { session.current.muted = false; setVoiceState("listening"); } },   // finished speaking: listen again
      () => { if (session.current) { session.current.muted = true; setVoiceState("speaking"); } },     // do not transcribe our own voice
    );
    const s = new VoiceSession({
      onPartial: (t) => { if (speaker.current) speaker.current.cancel(); setPartial(t); },
      onFinal: (t) => { setPartial(""); ask(t, true); },
      onLevel: setLevel,
      onError: (m) => { setVoiceError(m); stopVoice(); },
    });
    try {
      await s.start();
      session.current = s;
      setVoiceState("listening");
    } catch (e) {
      setVoiceError((e as Error).message);
      setVoiceOn(false);
      setVoiceState("idle");
    }
  }, [ask, stopVoice]);

  useEffect(() => () => { session.current?.stop(); speaker.current?.cancel(); abort.current?.abort(); }, []);
  useEffect(() => { if (!open && voiceOn) stopVoice(); }, [open, voiceOn, stopVoice]);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const role = user?.role ?? "visitor";
  const voiceLabel = { idle: "", connecting: "Connecting microphone", listening: "Listening", thinking: "Thinking", speaking: "Speaking" }[voiceState];

  return (
    <>
      <AnimatePresence>
        {!open && (
          <motion.button initial={{ opacity: 0, scale: 0.8, y: 20 }} animate={{ opacity: 1, scale: 1, y: 0 }} exit={{ opacity: 0, scale: 0.8 }}
            whileHover={{ scale: 1.05 }} whileTap={{ scale: 0.95 }} onClick={() => setOpen(true)} aria-label="Open help assistant"
            className="fixed bottom-5 right-5 z-40 flex items-center gap-2 rounded-full bg-accent px-4 py-3 text-sm font-semibold text-accent-ink shadow-[0_10px_40px_-8px_rgb(56_189_248/0.7)]">
            <LifeBuoy className="h-5 w-5" aria-hidden /> Help
          </motion.button>
        )}
      </AnimatePresence>

      <AnimatePresence>
        {open && (
          <motion.aside role="dialog" aria-label="NeuroQueue help assistant" initial={{ x: "100%" }} animate={{ x: 0 }} exit={{ x: "100%" }}
            transition={{ type: "spring", stiffness: 320, damping: 34 }}
            className="glass fixed bottom-0 right-0 top-0 z-[60] flex w-full max-w-[420px] flex-col !border-y-0 !border-r-0 shadow-2xl">
            <header className="flex items-center justify-between gap-3 border-b border-line px-4 py-3">
              <div className="flex items-center gap-2.5">
                <span className="grid h-9 w-9 place-items-center rounded-xl bg-accent/15 text-accent"><Bot className="h-5 w-5" aria-hidden /></span>
                <div>
                  <p className="font-display text-sm font-semibold text-ink">NeuroQueue Help</p>
                  <p className="text-[11px] text-ink-3">Answers about this website. Not medical advice.</p>
                </div>
              </div>
              <div className="flex items-center gap-1">
                <button onClick={() => { setSpeak((v) => !v); speaker.current?.cancel(); }} aria-label={speak ? "Turn spoken answers off" : "Turn spoken answers on"}
                  aria-pressed={speak} className="rounded-lg p-2 text-ink-2 hover:bg-surface-2">
                  {speak ? <Volume2 className="h-4 w-4" /> : <VolumeX className="h-4 w-4" />}
                </button>
                <button onClick={() => setOpen(false)} aria-label="Close help" className="rounded-lg p-2 text-ink-2 hover:bg-surface-2"><X className="h-4 w-4" /></button>
              </div>
            </header>

            <div ref={scroller} className="flex-1 space-y-3 overflow-y-auto px-4 py-4" aria-live="polite">
              {msgs.length === 0 && (
                <div className="space-y-4">
                  <div className="rounded-2xl bg-surface-2 p-4 text-sm leading-relaxed text-ink">
                    Hi{user ? `, ${user.full_name.split(" ")[0]}` : ""}. I can explain how NeuroQueue works, what the tiers mean and how to use each page.
                    Type a question, or tap the microphone and just talk.
                  </div>
                  <div className="space-y-2">
                    <p className="text-[11px] font-medium uppercase tracking-wider text-ink-3">Try asking</p>
                    {SUGGESTIONS[role].map((s, i) => (
                      <motion.button key={s} initial={{ opacity: 0, x: 12 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: 0.05 * i }} onClick={() => ask(s)}
                        className="block w-full rounded-xl border border-line px-3 py-2 text-left text-sm text-ink-2 transition hover:border-accent hover:text-ink">{s}</motion.button>
                    ))}
                  </div>
                  <Link href="/help" onClick={() => setOpen(false)} className="block text-sm text-accent hover:underline">Open the full help guide</Link>
                </div>
              )}
              {msgs.map((m, i) => (
                <motion.div key={i} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} className={cn("flex", m.role === "user" ? "justify-end" : "justify-start")}>
                  <div translate="no" dir="auto" className={cn("max-w-[86%] whitespace-pre-wrap rounded-2xl px-3.5 py-2.5 text-sm leading-relaxed",
                    m.role === "user" ? "rounded-br-md bg-accent text-accent-ink" : m.error ? "rounded-bl-md border border-urgent/50 bg-urgent/10 text-ink" : "rounded-bl-md bg-surface-2 text-ink",
                    m.streaming && "caret")}>
                    {m.content || (m.streaming ? "" : "…")}
                  </div>
                </motion.div>
              ))}
              {partial && <div className="flex justify-end"><div className="max-w-[86%] rounded-2xl rounded-br-md border border-dashed border-accent/60 px-3.5 py-2.5 text-sm italic text-ink-2">{partial}</div></div>}
            </div>

            <AnimatePresence>
              {voiceOn && (
                <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }} exit={{ height: 0, opacity: 0 }} className="overflow-hidden border-t border-line">
                  <div className="flex items-center gap-3 px-4 py-3">
                    <div className="relative grid h-11 w-11 shrink-0 place-items-center">
                      <motion.span className="absolute inset-0 rounded-full bg-accent/25" animate={{ scale: voiceState === "listening" ? 1 + Math.min(level * 3, 0.9) : voiceState === "speaking" ? [1, 1.25, 1] : 1 }}
                        transition={voiceState === "speaking" ? { repeat: Infinity, duration: 0.9 } : { duration: 0.08 }} />
                      <span className="relative grid h-8 w-8 place-items-center rounded-full bg-accent text-accent-ink"><Mic className="h-4 w-4" aria-hidden /></span>
                    </div>
                    <div className="min-w-0 flex-1">
                      <p className="text-sm font-medium text-ink">{voiceLabel}</p>
                      <p className="truncate text-xs text-ink-3">{voiceState === "listening" ? "Ask your question out loud. I answer when you pause." : "Voice agent is on."}</p>
                      <p className="text-[10px] text-ink-3">Audio is streamed for transcription only while this is on. It is not stored.</p>
                    </div>
                    <button onClick={stopVoice} className="inline-flex items-center gap-1.5 rounded-lg border border-line px-2.5 py-1.5 text-xs text-ink-2 hover:bg-surface-2"><Square className="h-3 w-3" aria-hidden />End</button>
                  </div>
                </motion.div>
              )}
            </AnimatePresence>
            {voiceError && <p role="alert" className="border-t border-line bg-review/10 px-4 py-2.5 text-xs leading-relaxed text-ink">{voiceError}</p>}

            <form onSubmit={(e) => { e.preventDefault(); ask(input); }} className="flex items-center gap-2 border-t border-line p-3">
              <button type="button" onClick={voiceOn ? stopVoice : startVoice} aria-label={voiceOn ? "Stop voice agent" : "Start voice agent"} aria-pressed={voiceOn}
                className={cn("grid h-10 w-10 shrink-0 place-items-center rounded-xl transition", voiceOn ? "bg-urgent text-white" : "bg-surface-2 text-ink hover:brightness-125")}>
                {voiceOn ? <MicOff className="h-4 w-4" /> : <Mic className="h-4 w-4" />}
              </button>
              <input value={input} onChange={(e) => setInput(e.target.value)} placeholder="Ask about NeuroQueue" aria-label="Your question" className="input !py-2.5" maxLength={500} />
              <button type="submit" disabled={busy || !input.trim()} aria-label="Send" className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-accent text-accent-ink disabled:opacity-40">
                <Send className="h-4 w-4" />
              </button>
            </form>
            <footer className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 border-t border-line px-4 py-2.5 text-[11px] text-ink-3">
              <a href={`mailto:${SUPPORT_EMAIL}`} className="inline-flex items-center gap-1.5 hover:text-ink"><Mail className="h-3 w-3" aria-hidden />{SUPPORT_EMAIL}</a>
              <a href={`tel:${SUPPORT_PHONE.replace(/\s/g, "")}`} className="inline-flex items-center gap-1.5 hover:text-ink"><Phone className="h-3 w-3" aria-hidden />{SUPPORT_PHONE}</a>
            </footer>
          </motion.aside>
        )}
      </AnimatePresence>
    </>
  );
}
