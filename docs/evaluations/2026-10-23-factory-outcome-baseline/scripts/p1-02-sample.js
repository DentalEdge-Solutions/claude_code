// P1-02: draw the seeded sample of 20 correction-flag outcome events for owner labelling. Read-only.
// Usage: node p1-02-sample.js <repo-dir> <before-ISO-UTC> [<transcripts-dir>]
// The B0 draw used before = 2026-10-23T16:08:04Z (telemetry keeps growing, so a cut-off is needed to redraw).
// Population: every "outcome" event in <repo-dir>/evals/telemetry/events-*.jsonl (files in name order).
// Frame: events whose session transcript still exists in <transcripts-dir>. Sample: seeded shuffle
// (mulberry32, seed 20261023) over the frame in file order, first 20, sorted by time.
// Prints one CSV line per sampled event: n,ts,session_id,kind,name. Never reads or prints message text.
'use strict';
const fs = require('fs');
const path = require('path');

const repo = process.argv[2] || process.cwd();
const before = process.argv[3];
if (!before) { console.error('need <before-ISO-UTC>'); process.exit(2); }
const tdir = process.argv[4] || path.join(process.env.HOME, '.claude/projects/-Users-ericksicard-Projects-claude-code');
const tel = path.join(repo, 'evals/telemetry');

const all = [];
for (const f of fs.readdirSync(tel).filter((f) => f.startsWith('events-')).sort()) {
  for (const l of fs.readFileSync(path.join(tel, f), 'utf8').split('\n')) {
    if (!l.trim()) continue;
    try { const e = JSON.parse(l); if (e.event === 'outcome' && e.ts < before) all.push(e); } catch { /* skip malformed line */ }
  }
}
const frame = all.filter((e) => fs.existsSync(path.join(tdir, e.session_id + '.jsonl')));

let s = 20261023;
const rnd = () => { s |= 0; s = s + 0x6D2B79F5 | 0; let t = Math.imul(s ^ s >>> 15, 1 | s); t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t; return ((t ^ t >>> 14) >>> 0) / 4294967296; };
const idx = [...frame.keys()];
for (let i = idx.length - 1; i > 0; i--) { const j = Math.floor(rnd() * (i + 1)); [idx[i], idx[j]] = [idx[j], idx[i]]; }
const pick = idx.slice(0, 20).map((i) => frame[i]).sort((a, b) => (a.ts < b.ts ? -1 : 1));

console.error(`population ${all.length}, frame ${frame.length}, sample ${pick.length}`);
console.log('n,ts,session_id,kind,name');
pick.forEach((e, i) => console.log([i + 1, e.ts, e.session_id, e.kind, e.name].join(',')));
