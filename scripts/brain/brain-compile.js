#!/usr/bin/env node
// scripts/brain/brain-compile.js — extract [decision] and [lesson] entries from
// session logs into candidate files. Notes stay in the log. NEVER writes to
// decisions/active/ or canon/ — that is brain-promote's job, behind --approve.
// An entry whose file name already exists in decisions/active/ or canon/ was
// promoted (promote moves the file, same basename): it is skipped, even with
// --force, so a promoted entry is never resurrected as a candidate.
// Usage: node brain-compile.js [--date YYYY-MM-DD | --all] [--force] [--target <dir>]
// Exit 0 ok (including nothing to do) · 1 structure error.
'use strict';
const fs = require('fs');
const path = require('path');
const {
  getArg, hasFlag, resolveTarget, todayStamp, serializeFrontmatter, slugify,
} = require('./brain-lib');

const target = resolveTarget(process.argv);
// --date is interpolated straight into a filename (sessions/daily/<date>.md); a
// strict YYYY-MM-DD check is simpler and stricter than path-containment here —
// it rejects '../' traversal and any other filename-breaking input outright.
const dateArg = getArg(process.argv, '--date', todayStamp());
if (!hasFlag(process.argv, '--all') && !/^\d{4}-\d{2}-\d{2}$/.test(dateArg)) {
  console.error(`brain-compile: --date must be YYYY-MM-DD (got '${dateArg}')`);
  process.exit(1);
}
const dailyDir = path.join(target, 'sessions', 'daily');
if (!fs.existsSync(dailyDir)) {
  console.error(`brain-compile: not a project brain capsule (missing sessions/daily under ${target})`);
  process.exit(1);
}
const files = hasFlag(process.argv, '--all')
  ? fs.readdirSync(dailyDir).filter(f => f.endsWith('.md')).map(f => path.join(dailyDir, f))
  : [path.join(dailyDir, `${dateArg}.md`)];

const DEST = {
  decision: path.join(target, 'decisions', 'candidates'),
  lesson: path.join(target, 'lessons', 'memories'),
};
const ENTRY_RE = /^## (\d{2}:\d{2}) \[(decision|lesson)\] ?(.*)$/gm;
let written = 0, skipped = 0, alreadyPromoted = 0;
const PROMOTED_DIRS = [path.join(target, 'decisions', 'active'), path.join(target, 'canon')];
const outputs = [];

for (const file of files) {
  if (!fs.existsSync(file)) continue;
  const date = path.basename(file, '.md');
  const text = fs.readFileSync(file, 'utf8');
  let m;
  while ((m = ENTRY_RE.exec(text)) !== null) {
    const [, time, type, titleRaw] = m;
    const bodyStart = text.indexOf('\n', m.index) + 1;
    const nextHeading = text.indexOf('\n## ', bodyStart);
    const body = text.slice(bodyStart, nextHeading === -1 ? undefined : nextHeading).trim();
    const title = titleRaw.trim() || body.split('\n')[0].slice(0, 60);
    const name = `${date}-${slugify(title)}.md`;
    const dest = path.join(DEST[type], name);
    if (PROMOTED_DIRS.some(d => fs.existsSync(path.join(d, name)))) { alreadyPromoted++; continue; }
    if (fs.existsSync(dest) && !hasFlag(process.argv, '--force')) { skipped++; continue; }
    fs.mkdirSync(path.dirname(dest), { recursive: true });
    fs.writeFileSync(dest, serializeFrontmatter({
      type,
      title,
      description: body.split('\n')[0].slice(0, 120),
      tags: [],
      timestamp: `${date}T${time}:00`,
      sources: [`sessions/daily/${date}.md`],
      status: 'candidate',
    }, `${body}\n`));
    outputs.push(path.relative(target, dest));
    written++;
  }
}

// Report — fail open: a report-write failure must not fail the compile.
try {
  const rdir = path.join(target, 'reports', 'compile');
  fs.mkdirSync(rdir, { recursive: true });
  fs.writeFileSync(path.join(rdir, `${todayStamp()}.json`),
    JSON.stringify({ written, skipped, already_promoted: alreadyPromoted, outputs }, null, 2));
} catch { /* fail open */ }

console.log(`brain-compile: ${written} candidate(s) written, ${skipped} skipped, ${alreadyPromoted} already promoted`);
