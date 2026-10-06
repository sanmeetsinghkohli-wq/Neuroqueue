"use client";

import { api } from "./api";

/**
 * Realtime voice input. Microphone audio is streamed to AssemblyAI over a
 * WebSocket (short-lived token from our server; the API key never reaches the
 * browser) and partial transcripts come back while the user is still talking.
 * Falls back to the browser's own speech recognition if the service is unavailable.
 */
export interface VoiceHandlers {
  onPartial: (text: string) => void;
  onFinal: (text: string) => void;
  onLevel?: (level: number) => void;
  onError: (message: string) => void;
}

const BLOCKED = "The microphone is blocked for this site. Click the lock or camera icon in the address bar, set Microphone to Allow, then reload and try again. "
  + "If you are using the preview pane inside the Claude desktop app, open http://localhost:3000 in Chrome or Edge instead: that pane does not allow microphone access. You can always type your question.";
const NO_MIC = "No microphone was found. Plug one in or enable it in your system sound settings, then try again. You can also type your question.";

/** Turn a getUserMedia failure into something the user can act on. Returns null if the error is not about the microphone. */
export function micErrorMessage(e: unknown): string | null {
  switch ((e as Error)?.name) {
    case "NotAllowedError": case "SecurityError": return BLOCKED;
    case "NotFoundError": case "OverconstrainedError": return NO_MIC;
    case "NotReadableError": case "AbortError": return "The microphone is in use by another application or could not be started. Close other apps that use it (a call, a recorder) and try again.";
    default: return null;
  }
}

/** Checks that can be made without prompting, so we never ask for a permission that cannot be granted. */
async function preflight(): Promise<void> {
  if (!window.isSecureContext) throw new Error("Voice needs a secure page. Open the site at https:// or at http://localhost, not through an IP address.");
  if (!navigator.mediaDevices?.getUserMedia) throw new Error("This browser does not support microphone input. You can type your question instead.");
  try {
    const status = await navigator.permissions.query({ name: "microphone" as PermissionName });
    if (status.state === "denied") throw new Error(BLOCKED);   // already refused: the browser would not show a prompt again
  } catch (e) {
    if ((e as Error).message === BLOCKED) throw e;   // Permissions API not available for microphone here: fall through to the normal prompt
  }
}

const WORKLET = `
class PcmTap extends AudioWorkletProcessor {
  process(inputs) {
    const ch = inputs[0] && inputs[0][0];
    if (ch) this.port.postMessage(ch.slice(0));
    return true;
  }
}
registerProcessor("pcm-tap", PcmTap);`;

export class VoiceSession {
  provider: "assemblyai" | "browser" | null = null;
  muted = false;
  private ws: WebSocket | null = null;
  private ctx: AudioContext | null = null;
  private stream: MediaStream | null = null;
  private recog: any = null;
  private stopped = false;

  constructor(private h: VoiceHandlers) {}

  async start(): Promise<void> {
    await preflight();
    let cfg: { provider: string; token: string | null; url?: string; sample_rate?: number };
    try {
      cfg = await api("/api/assist/voice-token");
    } catch {
      cfg = { provider: "browser", token: null };
    }
    if (cfg.provider === "assemblyai" && cfg.token) {
      try {
        await this.startAssembly(cfg.url!, cfg.token, cfg.sample_rate ?? 16000);
        this.provider = "assemblyai";
        return;
      } catch (e) {
        this.cleanupAudio();
        this.ws?.close();
        const mic = micErrorMessage(e);
        if (mic) throw new Error(mic);   // a microphone problem: asking again through another API would only prompt twice
      }
    }
    this.startBrowser();
    this.provider = "browser";
  }

  private async startAssembly(url: string, token: string, rate: number): Promise<void> {
    this.stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, channelCount: 1 } });
    if (this.stopped) { this.cleanupAudio(); return; }   // the panel was closed while the permission prompt was open
    this.ctx = new AudioContext({ sampleRate: rate });
    await this.ctx.audioWorklet.addModule(URL.createObjectURL(new Blob([WORKLET], { type: "application/javascript" })));
    const ws = new WebSocket(`${url}?sample_rate=${rate}&encoding=pcm_s16le&format_turns=true&token=${encodeURIComponent(token)}`);
    ws.binaryType = "arraybuffer";
    this.ws = ws;
    await new Promise<void>((resolve, reject) => {
      ws.onopen = () => resolve();
      ws.onerror = () => reject(new Error("voice service unreachable"));
    });
    ws.onmessage = (ev) => {
      if (typeof ev.data !== "string") return;
      const m = JSON.parse(ev.data);
      if (m.type !== "Turn" || !m.transcript) return;
      if (m.end_of_turn && (m.turn_is_formatted ?? true)) this.h.onFinal(m.transcript);
      else if (!m.end_of_turn) this.h.onPartial(m.transcript);
    };
    ws.onclose = () => { if (!this.stopped) this.h.onError("The voice connection closed. Tap the microphone to start again."); };

    const node = new AudioWorkletNode(this.ctx, "pcm-tap");
    const chunk = Math.round(rate / 10); // 100 ms frames
    let buf = new Float32Array(0);
    node.port.onmessage = (ev: MessageEvent<Float32Array>) => {
      const f = ev.data;
      let peak = 0;
      for (let i = 0; i < f.length; i++) peak = Math.max(peak, Math.abs(f[i]));
      this.h.onLevel?.(this.muted ? 0 : peak);
      if (this.muted || ws.readyState !== 1) { buf = new Float32Array(0); return; }
      const merged = new Float32Array(buf.length + f.length);
      merged.set(buf);
      merged.set(f, buf.length);
      buf = merged;
      while (buf.length >= chunk) {
        const pcm = new Int16Array(chunk);
        for (let i = 0; i < chunk; i++) pcm[i] = Math.max(-1, Math.min(1, buf[i])) * 0x7fff;
        ws.send(pcm.buffer);
        buf = buf.slice(chunk);
      }
    };
    this.ctx.createMediaStreamSource(this.stream).connect(node);
  }

  private startBrowser(): void {
    const SR = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
    if (!SR) throw new Error("Voice input is not supported in this browser. You can type your question instead.");
    const r = new SR();
    r.continuous = true;
    r.interimResults = true;
    r.lang = document.documentElement.lang === "ar" ? "ar-SA" : "en-US";
    r.onresult = (ev: any) => {
      if (this.muted) return;
      const res = ev.results[ev.results.length - 1];
      (res.isFinal ? this.h.onFinal : this.h.onPartial)(res[0].transcript.trim());
    };
    r.onerror = (ev: any) => {
      if (ev.error === "no-speech" || ev.error === "aborted") return;
      this.stopped = true;   // do not auto-restart into the same error (which would ask for permission again)
      this.h.onError(ev.error === "not-allowed" || ev.error === "service-not-allowed" ? BLOCKED : ev.error === "audio-capture" ? NO_MIC : "Voice input stopped: " + ev.error);
    };
    r.onend = () => { if (!this.stopped) try { r.start(); } catch { /* already running */ } };
    r.start();
    this.recog = r;
  }

  private cleanupAudio(): void {
    this.stream?.getTracks().forEach((t) => t.stop());
    this.ctx?.close().catch(() => {});
    this.stream = null;
    this.ctx = null;
  }

  stop(): void {
    this.stopped = true;
    try { if (this.ws?.readyState === 1) this.ws.send(JSON.stringify({ type: "Terminate" })); } catch { /* closing anyway */ }
    this.ws?.close();
    this.recog?.stop();
    this.cleanupAudio();
  }
}

/** Speaks streamed text sentence by sentence, so the answer starts before it has finished generating. */
export class Speaker {
  private buf = "";
  private pending = 0;
  constructor(private lang: string, private onIdle: () => void, private onStart: () => void) {}

  static get supported() { return typeof window !== "undefined" && "speechSynthesis" in window; }

  feed(token: string): void {
    this.buf += token;
    const m = this.buf.match(/^([\s\S]*?[.!?])\s+([\s\S]*)$/);
    if (m) { this.say(m[1]); this.buf = m[2]; }
  }

  flush(): void {
    if (this.buf.trim()) this.say(this.buf);
    this.buf = "";
    if (this.pending === 0) this.onIdle();
  }

  private say(text: string): void {
    if (!Speaker.supported || !text.trim()) return;
    const u = new SpeechSynthesisUtterance(text.trim());
    u.rate = 1.03;
    u.lang = this.lang === "ar" ? "ar-SA" : "en-US";
    const done = () => { if (--this.pending <= 0) { this.pending = 0; this.onIdle(); } };
    u.onend = done;
    u.onerror = done;
    if (this.pending++ === 0) this.onStart();
    window.speechSynthesis.speak(u);
  }

  cancel(): void {
    this.buf = "";
    this.pending = 0;
    if (Speaker.supported) window.speechSynthesis.cancel();
  }
}
