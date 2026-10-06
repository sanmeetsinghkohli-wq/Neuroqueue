"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { api, type Role, type User } from "./api";

interface AuthState {
  user: User | null;
  ready: boolean;
  login: (email: string, password: string, role: Role) => Promise<User>;
  /** Creates an unverified account and sends a verification email. Does not sign in. */
  register: (body: Record<string, unknown>) => Promise<string>;
  google: (credential: string, extra?: Record<string, unknown>) => Promise<User>;
  logout: () => Promise<void>;
  refresh: () => Promise<void>;
  setUser: (u: User | null) => void;
}

const Ctx = createContext<AuthState | null>(null);
export const portalPath = (role: Role) => `/${role}`;

/**
 * The session lives in an HttpOnly cookie set by the server. This code never
 * sees, stores or sends a token itself, so a script injected into the page
 * could not steal the session.
 */
export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [ready, setReady] = useState(false);

  const refresh = useCallback(async () => {
    try {
      setUser((await api<{ user: User }>("/api/auth/me")).user);
    } catch {
      setUser(null);
    }
  }, []);

  useEffect(() => {
    try { window.localStorage.removeItem("nq_token"); } catch { /* storage unavailable */ }   // left over from older builds
    refresh().finally(() => setReady(true));
  }, [refresh]);

  const value = useMemo<AuthState>(() => ({
    user, ready, refresh, setUser,
    async login(email, password, role) {
      const r = await api<{ user: User }>("/api/auth/login", { body: { email, password, role } });
      setUser(r.user);
      return r.user;
    },
    async register(body) {
      return (await api<{ message: string }>("/api/auth/register", { body })).message;
    },
    async google(credential, extra = {}) {
      const r = await api<{ user: User }>("/api/auth/google", { body: { credential, ...extra } });
      setUser(r.user);
      return r.user;
    },
    async logout() {
      try { await api("/api/auth/logout", { method: "POST" }); } finally { setUser(null); }
    },
  }), [user, ready, refresh]);

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAuth(): AuthState {
  const v = useContext(Ctx);
  if (!v) throw new Error("useAuth must be used inside AuthProvider");
  return v;
}
