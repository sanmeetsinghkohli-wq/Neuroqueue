import type { NextConfig } from "next";

// Where the FastAPI backend lives. The browser never calls it directly for HTTP: every /api request goes to this
// site's own origin and is forwarded here, so the session cookie is first-party on any host (localhost, Vercel, ...).
const backend = (process.env.BACKEND_URL ?? "http://localhost:8000").replace(/\/$/, "");
// The live connection (WebSocket) cannot be forwarded by Vercel, so it goes straight to the backend.
const ws = (process.env.NEXT_PUBLIC_WS_URL ?? backend.replace(/^http/, "ws") + "/ws");
const wsOrigin = ws.replace(/\/ws$/, "");
const dev = process.env.NODE_ENV !== "production";

// Only our own code, our API, the voice transcription socket and Google sign-in may be loaded or contacted.
const csp = [
  "default-src 'self'",
  `script-src 'self' 'unsafe-inline' blob: https://accounts.google.com${dev ? " 'unsafe-eval'" : ""}`,
  "style-src 'self' 'unsafe-inline' https://accounts.google.com",
  "img-src 'self' data: blob:",
  "media-src 'self'",
  "font-src 'self' data:",
  `connect-src 'self' ${wsOrigin} wss://streaming.assemblyai.com https://accounts.google.com`,
  "frame-src https://accounts.google.com",
  "worker-src 'self' blob:",
  "object-src 'none'",
  "base-uri 'self'",
  "form-action 'self'",
  "frame-ancestors 'self'",
].join("; ");

const nextConfig: NextConfig = {
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "Content-Security-Policy", value: csp },
          { key: "X-Frame-Options", value: "SAMEORIGIN" },
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          // The help assistant's voice mode is the only feature that needs a device permission.
          { key: "Permissions-Policy", value: "microphone=(self), camera=(), geolocation=(), payment=()" },
          ...(dev ? [] : [{ key: "Strict-Transport-Security", value: "max-age=31536000; includeSubDomains" }]),
        ],
      },
    ];
  },
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${backend}/api/:path*` }];
  },
  env: { NEXT_PUBLIC_WS_URL: ws },
  compress: true,
  poweredByHeader: false,
};

export default nextConfig;
