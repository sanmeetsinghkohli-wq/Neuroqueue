"""Build the Arabic dictionary for the site with Qwen (Alibaba Cloud Model Studio).

    node frontend/scripts/extract-strings.mjs
    python frontend/scripts/extract_backend_strings.py
    python frontend/scripts/translate_ar.py          -> frontend/lib/i18n/ar.json

Only fixed interface text is sent (button labels, headings, messages). No patient data.
Re-running translates only strings that are new, so earlier (possibly hand-corrected) entries are kept.
"""
from __future__ import annotations

import asyncio
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.services.qwen import QwenClient, parse_json  # noqa: E402

OUT = HERE.parent / "lib" / "i18n" / "ar.json"
MODEL = "qwen3.8-max"
BATCH = 30

PROMPT = """You are localising a medical web application called NeuroQueue (AI-assisted brain MRI reporting) into Modern Standard Arabic.
Translate each English interface string into natural, professional Arabic as used in hospital software in the Gulf region.

Rules:
- Keep placeholders such as {0}, {1} exactly as they are, placed where they read naturally in Arabic.
- Keep these unchanged in Latin letters: NeuroQueue, Qwen, MRI, PDF, AI, ID, Google, Chrome, Edge, SMTP, URL, ECE, Ctrl, Enter, and any code-like text.
- Use this glossary consistently:
  Urgent = عاجل | Review (queue tier) = مراجعة | Routine = اعتيادي | Glioma = ورم دبقي | Meningioma = ورم سحائي |
  Pituitary tumor = ورم الغدة النخامية | No tumor = لا يوجد ورم | Doctor = الطبيب | Patient = المريض | Admin = المسؤول |
  Radiologist = أخصائي الأشعة | Scan = فحص | Report = تقرير | Queue = قائمة الانتظار | Dashboard = لوحة التحكم |
  Sign in = تسجيل الدخول | Sign out = تسجيل الخروج | Register = إنشاء حساب | Upload = رفع | Heatmap = الخريطة الحرارية |
  Audit = سجل التدقيق | Metrics = المقاييس | Confidence = نسبة الثقة | Finalize = اعتماد نهائي | Draft = مسودة
- Do not add explanations, quotes or extra punctuation. Do not translate meaning differently for medical statements; stay literal and precise.
- Short labels stay short. Keep sentence punctuation equivalent (use ، and ؟ where Arabic needs them).

Return JSON only: an object mapping each id to its Arabic translation.

Strings:
{items}"""


def placeholders(s: str) -> list[str]:
    return sorted(re.findall(r"\{\d+\}", s))


async def translate_batch(q: QwenClient, batch: list[str]) -> dict[str, str]:
    items = json.dumps({str(i): s for i, s in enumerate(batch)}, ensure_ascii=False, indent=0)
    for attempt in range(3):
        try:
            text = await q.complete([{"role": "user", "content": PROMPT.replace("{items}", items)}], model=MODEL, temperature=0.0, max_tokens=6000)
            data = parse_json(text)
            out = {}
            for i, s in enumerate(batch):
                t = data.get(str(i))
                if isinstance(t, str) and t.strip() and placeholders(t) == placeholders(s):
                    out[s] = t.strip()
            if len(out) >= len(batch) * 0.8 or attempt == 2:
                return out
        except Exception as e:  # noqa: BLE001
            print("  retry:", type(e).__name__, flush=True)
            await asyncio.sleep(2)
    return {}


async def main() -> None:
    strings, templates = set(), set()
    for name in ("strings.frontend.json", "strings.backend.json"):
        d = json.loads((HERE / name).read_text(encoding="utf-8"))
        strings |= set(d["strings"])
        templates |= set(d["templates"])
    existing = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {"strings": {}, "templates": {}}
    done = {**existing.get("strings", {}), **existing.get("templates", {})}
    todo = sorted((strings | templates) - set(done))
    print(f"{len(strings)} strings, {len(templates)} templates, {len(todo)} to translate", flush=True)

    q = QwenClient()
    sem = asyncio.Semaphore(5)
    batches = [todo[i:i + BATCH] for i in range(0, len(todo), BATCH)]

    async def run(b, n):
        async with sem:
            r = await translate_batch(q, b)
            print(f"  batch {n + 1}/{len(batches)}: {len(r)}/{len(b)}", flush=True)
            return r

    for r in await asyncio.gather(*(run(b, n) for n, b in enumerate(batches))):
        done.update(r)
    overrides = {k: v for k, v in json.loads((HERE / "ar_overrides.json").read_text(encoding="utf-8")).items() if not k.startswith("_")}
    templates |= {k for k in overrides if "{0}" in k}
    strings |= {k for k in overrides if "{0}" not in k}
    done.update(overrides)   # hand-checked wording always wins
    # the fallback clinical-report template is report content, not interface text: it is never auto-translated
    templates = {t for t in templates if not t.startswith(("FINDINGS:", "Hello "))}
    result = {"strings": {k: v for k, v in sorted(done.items()) if k in strings}, "templates": {k: v for k, v in sorted(done.items()) if k in templates}}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    missing = sorted((strings | templates) - set(done))
    print(f"written {OUT.name}: {len(result['strings'])} strings, {len(result['templates'])} templates, {len(missing)} missing")
    for m in missing[:15]:
        print("  missing:", m[:90])


if __name__ == "__main__":
    asyncio.run(main())
