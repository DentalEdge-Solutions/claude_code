// scripts/brain/brain-lib.js — shared helpers for brain-kernel scripts.
// Zero dependencies, no network, deterministic (UTC timestamps).
'use strict';
const fs = require('fs');
const path = require('path');

const SENSITIVE_CONTENT_PATTERNS = [
  { name: 'anthropic-api-key', re: /\bsk-ant-[A-Za-z0-9_-]{10,}/ },
  { name: 'generic-sk-key', re: /\bsk-[A-Za-z0-9]{20,}\b/ },
  { name: 'aws-access-key-id', re: /\bAKIA[0-9A-Z]{16}\b/ },
  { name: 'github-token', re: /\bgh[pousr]_[A-Za-z0-9]{20,}\b/ },
  { name: 'private-key-block', re: /-----BEGIN [A-Z ]*PRIVATE KEY-----/ },
  { name: 'password-assignment', re: /\bpassword\s*[:=]\s*['"]?[^\s'"]{4,}/i },
];

function getArg(argv, name, def = null) {
  const i = argv.indexOf(name);
  return i !== -1 && argv[i + 1] !== undefined ? argv[i + 1] : def;
}
function hasFlag(argv, name) { return argv.includes(name); }
function positional(argv) {
  const flagsWithValue = new Set(['--target', '--to', '--message', '--title', '--type', '--date']);
  const out = [];
  for (let i = 2; i < argv.length; i++) {
    if (flagsWithValue.has(argv[i])) { i++; continue; }
    if (String(argv[i]).startsWith('--')) continue;
    out.push(argv[i]);
  }
  return out;
}
function resolveTarget(argv) { return path.resolve(getArg(argv, '--target', '.project-brain')); }
function todayStamp(d = new Date()) { return d.toISOString().slice(0, 10); }
function timeStamp(d = new Date()) { return d.toISOString().slice(11, 16); }
function scanSensitive(text) {
  return SENSITIVE_CONTENT_PATTERNS.filter(p => p.re.test(text)).map(p => p.name);
}
// Frontmatter: leading '---' block of `key: value` lines. Values are scalars,
// inline lists like [a, b], or block lists (`key:` then `  - item` lines). Enough
// for brain files; deliberately not full YAML.
function unquoteItem(s) {
  const q = s[0];
  if (s.length >= 2 && (q === '"' || q === "'") && s[s.length - 1] === q) {
    const inner = s.slice(1, -1);
    // Only double quotes carry escapes (the serializer writes \\ and \").
    return q === '"' ? inner.replace(/\\(["\\])/g, '$1') : inner;
  }
  return s;
}
function parseFrontmatter(text) {
  if (!text.startsWith('---\n')) return { fields: null, body: text };
  const end = text.indexOf('\n---', 4);
  if (end === -1) return { fields: null, body: text };
  const fields = {};
  const lines = text.slice(4, end).split('\n');
  for (let i = 0; i < lines.length; i++) {
    const m = lines[i].match(/^([A-Za-z_][\w-]*):\s*(.*)$/);
    if (!m) continue;
    let v = m[2].trim();
    if (v === '') {
      // `key:` with nothing after it: collect following `- item` lines, if any.
      const items = [];
      while (i + 1 < lines.length) {
        const im = lines[i + 1].match(/^\s*-\s+(.*)$/);
        if (!im) break;
        items.push(unquoteItem(im[1].trim()));
        i++;
      }
      if (items.length) v = items;
    } else if (v.startsWith('[') && v.endsWith(']')) {
      v = v.slice(1, -1).split(',').map(s => s.trim()).filter(Boolean);
    }
    fields[m[1]] = v;
  }
  return { fields, body: text.slice(end + 4).replace(/^\n+/, '') };
}
// An item the inline `[a, b]` form cannot carry safely.
const NEEDS_QUOTING = /,|: |#|^ | $|[\[\]]|^["']/;
function serializeFrontmatter(fields, body) {
  const lines = Object.entries(fields).map(([k, v]) => {
    if (!Array.isArray(v)) return `${k}: ${v}`;
    if (!v.some(item => NEEDS_QUOTING.test(String(item)))) return `${k}: [${v.join(', ')}]`;
    // Block list; quote only the items that need it so plain ones stay readable.
    const items = v.map(item => {
      const t = String(item);
      return NEEDS_QUOTING.test(t) ? `  - "${t.replace(/[\\"]/g, '\\$&')}"` : `  - ${t}`;
    });
    return `${k}:\n${items.join('\n')}`;
  });
  return `---\n${lines.join('\n')}\n---\n\n${body}`;
}
function walkMarkdown(dir) {
  const out = [];
  if (!fs.existsSync(dir)) return out;
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, entry.name);
    if (entry.isDirectory()) out.push(...walkMarkdown(p));
    else if (entry.name.endsWith('.md')) out.push(p);
  }
  return out;
}
function slugify(s) {
  return s.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '').slice(0, 60);
}
// Resolves `rel` against `target` and returns the absolute path ONLY if it stays
// strictly inside the capsule — rejects `../` escapes and absolute-path args.
// Callers must treat a null return as a hard refusal, never fall back to path.join.
function resolveCapsuleRelative(target, rel) {
  const base = path.resolve(target);
  const resolved = path.resolve(base, rel);
  return resolved.startsWith(base + path.sep) ? resolved : null;
}

module.exports = {
  getArg, hasFlag, positional, resolveTarget, todayStamp, timeStamp,
  scanSensitive, parseFrontmatter, serializeFrontmatter, walkMarkdown, slugify,
  resolveCapsuleRelative, SENSITIVE_CONTENT_PATTERNS,
};
