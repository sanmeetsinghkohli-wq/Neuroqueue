"""Collects user-visible English strings that the API sends to the browser (errors, tier reasons,
stage names, patient-report text, follow-up suggestions) so they can be translated too.

    python frontend/scripts/extract_backend_strings.py   -> frontend/scripts/strings.backend.json

Prompts sent to the language model and the help assistant's knowledge are deliberately excluded.
"""
from __future__ import annotations

import ast
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "backend" / "app"
SKIP_FILES = {"knowledge.py", "qwen.py", "config.py", "pdf.py", "audit.py"}
SKIP_NAMES = {"SYSTEM", "CLINICAL_USER", "SUMMARY_USER", "SYSTEM_PROMPT", "SITE_KNOWLEDGE", "ROLE_HINTS", "WORKLET"}


def ok(s: str) -> bool:
    s = s.strip()
    return bool(re.search(r"[A-Za-z]{3,}", s)) and (" " in s) and 3 <= len(s) <= 500 and not s.startswith(("http", "/", "rpc/", "Supabase", "select ", "{")) \
        and not re.fullmatch(r"[a-z0-9_./:%-]+", s)


def main() -> None:
    strings, templates = set(), set()
    for path in sorted(APP.rglob("*.py")):
        if path.name in SKIP_FILES:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        skip = set()
        for node in ast.walk(tree):
            # docstrings, prompts and log messages never reach the screen
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Module)) and ast.get_docstring(node, clean=False) is not None:
                skip.add(id(node.body[0].value))
            if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id in SKIP_NAMES for t in node.targets):
                skip.update(id(n) for n in ast.walk(node.value))
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name) and node.func.value.id in ("log", "logging"):
                skip.update(id(n) for a in node.args for n in ast.walk(a))
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in ("RuntimeError", "KeyError", "ValueError", "print"):
                skip.update(id(n) for a in node.args for n in ast.walk(a))
        for node in ast.walk(tree):
            if id(node) in skip:
                continue
            if isinstance(node, ast.JoinedStr):
                parts, i = [], 0
                for v in node.values:
                    skip.add(id(v))
                    if isinstance(v, ast.Constant):
                        parts.append(str(v.value))
                    else:
                        parts.append("{%d}" % i)
                        i += 1
                        skip.update(id(n) for n in ast.walk(v))
                t = re.sub(r"\s+", " ", "".join(parts)).strip()
                if ok(re.sub(r"\{\d+\}", "", t)):
                    templates.add(t)
        for node in ast.walk(tree):
            if id(node) in skip:
                continue
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and ok(node.value):
                strings.add(re.sub(r"\s+", " ", node.value).strip())
    out = {"strings": sorted(strings), "templates": sorted(templates)}
    (Path(__file__).parent / "strings.backend.json").write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"backend strings: {len(out['strings'])}  templates: {len(out['templates'])}")


if __name__ == "__main__":
    main()
