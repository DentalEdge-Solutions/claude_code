#!/usr/bin/env node
// scripts/check-skill-deploy.js — compares every project skill (skills/<name>/) with its installed
// copy (~/.claude/skills/<name>/), file by file. Claude Code loads skills from ~/.claude/skills, not
// from this repo's skills/ folder, so an edit takes effect only once it is deployed. On 2026-10-22,
// 14 installed skills were still running versions from June and July and one had never been
// installed: deploys copied only the skills each change touched, and nothing compared the whole set.
//
// Usage: node scripts/check-skill-deploy.js [--source <dir>] [--installed <dir>]
//   --source     project skills folder (default: this repo's skills/)
//   --installed  installed skills folder (default: ~/.claude/skills)
// Skills are discovered from the source folder (every subfolder), never from a fixed list; a
// symlinked folder in the source is skipped, as install.sh's `find -type d` skips it. Installed
// skills that are not in the project are ignored: other tools install skills there too. A skill
// root that is a symlink is followed, as Claude Code follows it; links inside a skill are compared
// by target and never followed. .DS_Store files are ignored. File modes are not compared.
// Prints skill and file names only, never file contents.
// Exit 0 every skill matches · 1 a skill is missing or differs · 2 the check could not be completed
// (usage error, no source folder, or a file or folder that cannot be read).
'use strict';
const fs = require('fs');
const os = require('os');
const path = require('path');

const args = process.argv.slice(2);
if (args.includes('--help') || args.includes('-h')) {
  console.log('usage: node scripts/check-skill-deploy.js [--source <dir>] [--installed <dir>]\n' +
    'Compares each project skill with its installed copy. Exit 0 all match, 1 a mismatch,\n' +
    '2 the check could not be completed (usage error, missing source, unreadable file).');
  process.exit(0);
}
function usage(msg) {
  console.error(`check-skill-deploy: ${msg}`);
  process.exit(2);
}
const opts = {};
for (let i = 0; i < args.length; i += 2) {
  const flag = args[i];
  if (flag !== '--source' && flag !== '--installed') usage(`unknown argument ${flag}`);
  if (flag in opts) usage(`${flag} given more than once`);
  const value = args[i + 1];
  if (value === undefined || value.startsWith('--')) usage(`${flag} needs a value`);
  opts[flag] = value;
}
const source = path.resolve(opts['--source'] || path.join(__dirname, '..', 'skills'));
const installed = path.resolve(opts['--installed'] || path.join(os.homedir(), '.claude', 'skills'));

// Absent means not there (missing, a dangling or looping link, a file in the path); any other error
// is a folder that cannot be read, which ends in exit 2, never in a false "not installed" (review C12).
const ABSENT = new Set(['ENOENT', 'ENOTDIR', 'ELOOP']);
let sourceEntries;
try {
  if (!fs.statSync(source).isDirectory()) usage(`no project skills folder at ${source}`);
  sourceEntries = fs.readdirSync(source, { withFileTypes: true });
} catch (err) {
  if (ABSENT.has(err.code)) usage(`no project skills folder at ${source}`);
  usage(`cannot read the project skills folder ${source} (${err.code})`);
}

const IGNORED = new Set(['.DS_Store']);
// Every entry under dir, as relative path → { kind, link } (lstat: a symlink is compared as a link).
function listTree(dir, base = dir, out = new Map()) {
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    if (IGNORED.has(e.name)) continue;
    const p = path.join(dir, e.name);
    const rel = path.relative(base, p).split(path.sep).join('/');
    const st = fs.lstatSync(p);
    if (st.isSymbolicLink()) out.set(rel, { kind: 'link', link: fs.readlinkSync(p) });
    else if (st.isDirectory()) { out.set(rel, { kind: 'dir' }); listTree(p, base, out); }
    else if (st.isFile()) out.set(rel, { kind: 'file' });
    else out.set(rel, { kind: 'other' });
  }
  return out;
}
// Each read is tagged with its side, so an error names the right folder whatever the layout.
function onSide(side, fn) {
  try { return fn(); } catch (err) { if (err.code && !err.side) err.side = side; throw err; }
}
function sameEntry(rel, a, b, srcRoot, instRoot) {
  if (a.kind !== b.kind) return false;
  if (a.kind === 'link') return a.link === b.link;
  if (a.kind === 'file') {
    const x = onSide('project', () => fs.readFileSync(path.join(srcRoot, rel)));
    const y = onSide('installed', () => fs.readFileSync(path.join(instRoot, rel)));
    return x.equals(y);
  }
  return true;
}
function installedDir(p) {
  try { return fs.statSync(p).isDirectory(); } catch (err) {
    if (ABSENT.has(err.code)) return false;
    err.side = 'installed';
    throw err;
  }
}
// A read error names its side and path, relative to that side's skills folder, never a stack trace.
function where(err) {
  const root = err.side === 'project' ? source : installed;
  const rel = path.relative(root, path.resolve(err.path)).split(path.sep).join('/');
  return `${err.side} ${rel}`;
}

const skills = sourceEntries.filter(e => e.isDirectory()).map(e => e.name).sort();
const problems = [];
let unreadable = 0;
for (const name of skills) {
  const srcRoot = path.join(source, name);
  const instRoot = path.join(installed, name);
  try {
    if (!installedDir(instRoot)) { problems.push(`${name}: not installed`); continue; }
    const a = onSide('project', () => listTree(srcRoot));
    const b = onSide('installed', () => listTree(instRoot));
    for (const [rel, entry] of a) {
      if (!b.has(rel)) problems.push(`${name}: not deployed: ${rel}`);
      else if (!sameEntry(rel, entry, b.get(rel), srcRoot, instRoot)) problems.push(`${name}: differs: ${rel}`);
    }
    for (const rel of b.keys()) if (!a.has(rel)) problems.push(`${name}: only installed: ${rel}`);
  } catch (err) {
    if (!err.code) throw err;
    unreadable++;
    problems.push(`${name}: cannot read: ${err.path && err.side ? where(err) : name} (${err.code})`);
  }
}

const n = skills.length;
console.log(`check-skill-deploy: ${n} skill${n === 1 ? '' : 's'} checked against ${installed}`);
if (problems.length === 0) {
  console.log('check-skill-deploy: all match');
  process.exit(0);
}
for (const p of problems) console.log(p);
if (unreadable) {
  console.log(`check-skill-deploy: ${unreadable} skill(s) could not be read, so the check is incomplete.`);
  process.exit(2);
}
console.log(`check-skill-deploy: ${problems.length} problem(s). Deploy each listed skill with ` +
  '`cp -R skills/<name>/. ~/.claude/skills/<name>/`; a file listed as "only installed" is not removed by ' +
  'that copy, so check it and remove it by hand.');
process.exit(1);
