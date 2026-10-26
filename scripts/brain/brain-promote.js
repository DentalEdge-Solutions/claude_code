#!/usr/bin/env node
// scripts/brain/brain-promote.js — the ONLY writer to canon/ and decisions/active/.
// Requires explicit --approve; without it, refuses and writes NOTHING (exit 2).
// Usage: node brain-promote.js <capsule-relative-file> --approve
//        [--to active|canon|superseded] [--force] [--target <dir>]
// --to superseded moves a file from decisions/active/ to decisions/superseded/ (weekly review).
// Exit 0 ok · 1 usage/overwrite/traversal refusal · 2 missing --approve · 3 sensitive content.
'use strict';
const fs = require('fs');
const path = require('path');
const {
  getArg, hasFlag, positional, resolveTarget, todayStamp,
  parseFrontmatter, serializeFrontmatter, scanSensitive, resolveCapsuleRelative,
} = require('./brain-lib');

const target = resolveTarget(process.argv);
const rel = positional(process.argv)[0];
if (!rel) {
  console.error('brain-promote: usage: brain-promote.js <capsule-relative-file> --approve [--to active|canon]');
  process.exit(1);
}
// Containment check BEFORE any filesystem access: '../' segments or absolute
// paths must never let a promote reach outside the capsule (read, delete, or write).
const src = resolveCapsuleRelative(target, rel);
if (src === null) {
  console.error(`brain-promote: path escapes the capsule: ${rel}`);
  process.exit(1);
}
if (!hasFlag(process.argv, '--approve')) {
  console.error('brain-promote: REFUSED — promotion to canon/active requires explicit --approve (human decision, never autonomous)');
  process.exit(2);
}
const to = getArg(process.argv, '--to', 'active');
if (!['active', 'canon', 'superseded'].includes(to)) {
  console.error(`brain-promote: --to must be 'active', 'canon' or 'superseded' (got '${to}')`);
  process.exit(1);
}
// --to superseded retires an active decision (the weekly review's "superseded" verdict). It moves
// only a file in decisions/active/: never a candidate, never canon.
const activeDir = path.resolve(target, 'decisions', 'active');
if (to === 'superseded' && path.dirname(src) !== activeDir) {
  console.error(`brain-promote: --to superseded moves an active decision; ${rel} is not in decisions/active/`);
  process.exit(1);
}
if (!fs.existsSync(src)) {
  console.error(`brain-promote: candidate not found: ${rel}`);
  process.exit(1);
}
const text = fs.readFileSync(src, 'utf8');
const hits = scanSensitive(text);
if (hits.length) {
  console.error(`brain-promote: REFUSED — sensitive content in candidate (${hits.join(', ')}); clean it before promoting`);
  process.exit(3);
}
const destDir = to === 'canon' ? path.resolve(target, 'canon')
  : to === 'superseded' ? path.resolve(target, 'decisions', 'superseded') : activeDir;
const dest = path.join(destDir, path.basename(src));
// Writing a file onto itself and then removing the source would delete it. Compared by file
// identity, not path text: on a case-insensitive disk decisions/ACTIVE/x.md is decisions/active/x.md
// (PR7-R-3). A destination that cannot be compared counts as the same file.
const sameFile = (() => {
  if (dest === src) return true;
  if (!fs.existsSync(dest)) return false;
  try {
    const a = fs.statSync(src), b = fs.statSync(dest);
    if (a.dev === b.dev && a.ino === b.ino) return true;
    return fs.realpathSync.native(src) === fs.realpathSync.native(dest);
  } catch { return true; }
})();
if (sameFile) {
  console.error(`brain-promote: source and destination are the same file: ${rel}`);
  process.exit(1);
}
if (fs.existsSync(dest) && !hasFlag(process.argv, '--force')) {
  console.error(`brain-promote: destination exists (pass --force to overwrite): ${path.relative(target, dest)}`);
  process.exit(1);
}
const { fields, body } = parseFrontmatter(text);
const stamp = to === 'superseded'
  ? { status: 'superseded', superseded_at: todayStamp() }
  : { status: to === 'canon' ? 'canon' : 'active', promoted_at: todayStamp() };
const updated = serializeFrontmatter({ ...(fields || {}), ...stamp }, body);
fs.mkdirSync(destDir, { recursive: true });
fs.writeFileSync(dest, updated);
fs.unlinkSync(src);
// Lifecycle log — fail open: a log-write failure must not undo the promotion.
const verb = to === 'superseded' ? 'superseded' : 'promoted';
try {
  fs.appendFileSync(path.join(target, 'log.md'),
    `- ${todayStamp()} ${verb} ${rel} → ${path.relative(target, dest)}\n`);
} catch { /* fail open */ }
console.log(`brain-promote: ${rel} → ${path.relative(target, dest)}`);
