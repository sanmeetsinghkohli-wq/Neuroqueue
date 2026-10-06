// Collects every user-visible English string in the frontend so it can be translated.
//   node scripts/extract-strings.mjs            -> scripts/strings.frontend.json
// Uses the TypeScript parser, so JSX text, string literals and template strings are found reliably.
import fs from "node:fs";
import path from "node:path";
import ts from "typescript";

const ROOT = path.resolve(import.meta.dirname, "..");
const DIRS = ["app", "components", "lib"];
const SKIP_ATTRS = new Set(["className", "href", "src", "id", "htmlFor", "type", "key", "role", "variant", "size", "tone", "name", "value", "autoComplete",
  "viewBox", "d", "fill", "stroke", "dataKey", "stackId", "layoutId", "poster", "accept", "method", "rel", "target", "style", "x", "y", "kind", "mode",
  "strokeDasharray", "iconType", "position", "ux_mode", "theme", "shape", "text", "locale", "preload", "inputMode", "pattern", "lang", "dir"]);
const TAILWIND = /(^|\s)(px-|py-|p-\d|m[trblxy]?-|text-(ink|xs|sm|base|lg|xl|\[|accent|center|left|right|review|urgent|routine)|bg-|rounded|flex|grid|border|h-\d|w-\d|gap-|items-|justify-|font-(display|mono|medium|semibold|bold|normal)|inline-|absolute|relative|fixed|hidden|block|overflow-|opacity-|transition|shadow|space-[xy]-|min-[hw]-|max-[hw]-|cursor-|tabular-nums|truncate|uppercase|tracking-|leading-|whitespace-|col-span|animate-|sr-only|shrink-0|place-items|z-\d|top-|bottom-|left-|right-|inset-|hover:|sm:|md:|lg:|xl:|rtl:|group|pulse-ring|caret|card|input|label|glass|shimmer)/;
const CODEY = /^(https?:|wss?:|\/|#|\.|@|use |var\(|rgb|M\d|\d|[a-z_]+$|[A-Z_]+$|[a-z]+[A-Z])|\/api\/|=>|\$\{|^[\w.-]+@[\w.-]+$|^[a-z0-9_-]+(\.[a-z0-9_-]+)+$|^\S+\.(mp4|jpg|jpeg|png|pdf|tsx?|js)$/;

const out = new Set();
const templates = new Set();
const clean = (s) => s.replace(/&ldquo;|&rdquo;/g, '"').replace(/&apos;|&rsquo;/g, "'").replace(/&amp;/g, "&").replace(/&bull;/g, "•").replace(/\s+/g, " ").trim();
const wordy = (s) => /[A-Za-z]{2,}/.test(s) && s.length >= 2 && s.length <= 600;

function keepLiteral(s) {
  s = clean(s);
  if (!wordy(s) || TAILWIND.test(s) || CODEY.test(s)) return null;
  if (!/\s/.test(s) && !/^[A-Z][a-z]/.test(s)) return null;          // single lowercase tokens are identifiers
  if (/^[a-z]+(-[a-z0-9]+)+$/.test(s)) return null;                  // kebab-case tokens
  return s;
}

function visit(node, sf) {
  if (ts.isImportDeclaration(node) || ts.isExportDeclaration(node)) return;
  if (ts.isJsxAttribute(node) && SKIP_ATTRS.has(node.name.getText(sf))) return;
  if (ts.isCallExpression(node) && ["cn", "require", "api", "fetch", "useLive", "addModule"].includes(node.expression.getText(sf)) && node.expression.getText(sf) === "cn") return;
  if (ts.isJsxText(node)) {
    const s = clean(node.getText(sf));
    if (wordy(s)) out.add(s);
  } else if (ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node)) {
    if (ts.isPropertyAssignment(node.parent) && node.parent.name === node) return;   // object keys
    const s = keepLiteral(node.text);
    if (s) out.add(s);
  } else if (ts.isTemplateExpression(node)) {
    let i = 0;
    let tpl = node.head.text;
    for (const span of node.templateSpans) tpl += `{${i++}}` + span.literal.text;
    const s = clean(tpl);
    const literal = s.replace(/\{\d+\}/g, "");
    if (wordy(literal) && /[A-Za-z]{3,}/.test(literal) && !TAILWIND.test(s) && !/^(https?:|wss?:|\/|#)|\/api\/|^\{0\}$/.test(s) && /\s/.test(s.trim())) {
      templates.add(s);
      // text around the expressions may also render as separate nodes
      for (const part of s.split(/\{\d+\}/)) { const k = keepLiteral(part.replace(/^[\s:·,.()-]+|[\s:·,(-]+$/g, "")); if (k && k.length > 2) out.add(k); }
    }
  }
  ts.forEachChild(node, (c) => visit(c, sf));
}

function walk(dir) {
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, e.name);
    if (e.isDirectory()) walk(p);
    else if (/\.tsx?$/.test(e.name) && !p.includes(`${path.sep}i18n${path.sep}`)) {
      const sf = ts.createSourceFile(p, fs.readFileSync(p, "utf8"), ts.ScriptTarget.Latest, true, e.name.endsWith("x") ? ts.ScriptKind.TSX : ts.ScriptKind.TS);
      visit(sf, sf);
    }
  }
}
DIRS.forEach((d) => walk(path.join(ROOT, d)));
const result = { strings: [...out].sort(), templates: [...templates].sort() };
fs.writeFileSync(path.join(ROOT, "scripts", "strings.frontend.json"), JSON.stringify(result, null, 1));
console.log(`strings: ${result.strings.length}  templates: ${result.templates.length}`);
