// P1-02: classify the input that set each sampled correction flag. Read-only; never prints message text.
// Usage: node p1-02-trigger-class.js <labels-csv> [<transcripts-dir>]
// The flag is written by scripts/telemetry/log-outcome.js inside the UserPromptSubmit hook with ts = now, so the
// triggering input is the prompt submitted at the event's ts. For each sampled event this looks at transcript
// entries within -1.5 s … +1.8 s of the full timestamp that can carry a submitted prompt: user entries (including
// isMeta ones) with string content, `queued_command` attachments, and `queue-operation` entries with string content. It prints, per row: the source class, whether
// the text contains a word from log-outcome.js REVISION_RE, and whether any of them is owner-typed input.
'use strict';
const fs = require('fs');
const path = require('path');

const [csvPath, tdirArg] = process.argv.slice(2);
if (!csvPath) { console.error('need <labels-csv>'); process.exit(2); }
const tdir = tdirArg || path.join(process.env.HOME, '.claude/projects/-Users-ericksicard-Projects-claude-code');
const REVISION_RE = /\b(fix|fixed|fixing|redo|wrong|instead|actually|change|changed)\b|\bno,/i; // copy of log-outcome.js:38

const rows = fs.readFileSync(csvPath, 'utf8').trim().split('\n').slice(1).map((l) => l.split(','));

function textOf(e) {
  if (e.type === 'queue-operation') return e.content;
  if (e.attachment && e.attachment.type === 'queued_command') {
    const p = e.attachment.prompt;
    return typeof p === 'string' ? p : JSON.stringify(p || '');
  }
  const c = e.message && e.message.content;
  return typeof c === 'string' ? c : null;
}

function classify(t) {
  if (/<task-notification>/.test(t)) return 'task-notification';
  if (/<agent-message|Subagent hand-back/.test(t)) return 'agent-report';
  if (/continued from a previous conversation/.test(t)) return 'summary';
  if (/^\s*<command-name>|<command-message>/.test(t)) return 'owner-slash-command';
  if (/^\s*<system-reminder>/.test(t)) return 'system-reminder';
  return 'owner-typed';
}

console.log('n,trigger_sources,trigger_has_revision_word,owner_input_at_trigger');
for (const [n, ts, session] of rows) {
  const t0 = new Date(ts).getTime();
  const found = [];
  for (const line of fs.readFileSync(path.join(tdir, session + '.jsonl'), 'utf8').split('\n')) {
    if (!line.trim()) continue;
    let e; try { e = JSON.parse(line); } catch { continue; }
    if (!e.timestamp) continue;
    const d = new Date(e.timestamp).getTime() - t0;
    if (d < -1500 || d > 1800) continue;
    const isQueued = e.attachment && e.attachment.type === 'queued_command';
    const isQueueOp = e.type === 'queue-operation' && typeof e.content === 'string';
    if (!isQueued && !isQueueOp && e.type !== 'user') continue;
    const t = textOf(e);
    if (t == null) continue;
    found.push({ cls: classify(t), rev: REVISION_RE.test(t) });
  }
  const sources = found.length ? [...new Set(found.map((f) => f.cls))].join('+') : 'not-in-transcript';
  const rev = found.some((f) => f.rev);
  const owner = found.some((f) => f.cls === 'owner-typed' || f.cls === 'owner-slash-command');
  console.log([n, sources, rev, owner].join(','));
}
