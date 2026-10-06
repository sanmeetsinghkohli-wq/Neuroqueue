import { timingSafeEqual } from "node:crypto";
import nodemailer from "nodemailer";

// The backend host blocks outgoing SMTP, so it hands verification and password-reset emails to this route,
// which sends them. Only the backend can call it: every request must carry the shared relay secret.
export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const same = (a: string, b: string) => {
  const x = Buffer.from(a), y = Buffer.from(b);
  return x.length === y.length && timingSafeEqual(x, y);
};

export async function POST(req: Request) {
  const secret = process.env.MAIL_RELAY_SECRET ?? "";
  if (!secret || !same(req.headers.get("x-relay-secret") ?? "", secret)) return Response.json({ code: "FORBIDDEN" }, { status: 403 });

  let msg: { to?: unknown; subject?: unknown; body?: unknown };
  try { msg = await req.json(); } catch { return Response.json({ code: "BAD_REQUEST" }, { status: 400 }); }
  const { to, subject, body } = msg;
  if (typeof to !== "string" || typeof subject !== "string" || typeof body !== "string" ||
      !/^[^@\s,;]+@[^@\s,;]+\.[^@\s,;]+$/.test(to) || /[\r\n]/.test(subject) || subject.length > 200 || body.length > 10000)
    return Response.json({ code: "BAD_REQUEST" }, { status: 400 });

  try {
    const transport = nodemailer.createTransport({
      host: process.env.SMTP_HOST, port: Number(process.env.SMTP_PORT ?? 587), secure: false, requireTLS: true,
      auth: { user: process.env.SMTP_USER, pass: process.env.SMTP_PASSWORD },
    });
    await transport.sendMail({ from: process.env.SMTP_FROM, to, subject, text: body });
    return Response.json({ ok: true });
  } catch (e) {
    console.error("mail relay: delivery failed:", (e as Error).name);
    return Response.json({ code: "DELIVERY_FAILED" }, { status: 502 });
  }
}
