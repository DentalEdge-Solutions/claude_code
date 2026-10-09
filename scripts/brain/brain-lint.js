#!/usr/bin/env node
// scripts/brain/brain-lint.js — quality + safety gate over brain content.
// Quality (frontmatter schema, stale timestamps, orphan [[links]]) → warnings,
// exit 0 (fail open). Sensitive content anywhere → SECURITY findings, exit 3.
// Stale: not superseded or retired, and neither timestamp nor reviewed_at within 90 days.
// Usage: node scripts/brain/brain-lint.js [--target <dir>]
'use strict';
const fs = require('fs');
const path = require('path');
const {
  resolveTarget, todayStamp, parseFrontmatter, scanSensitive, walkMarkdown,
} = require('./brain-lib');

const REQUIRED_FIELDS = ['type', 'title', 'description', 'tags', 'timestamp', 'sources'];
const GOVERNED_DIRS = ['decisions', 'lessons', 'canon', 'synthesis'];
const STALE_DAYS = 90;
const CLOSED_STATUSES = ['superseded', 'retired'];

const target = resolveTarget(process.argv);
const warnings = [];
const security = [];

const allFiles = walkMarkdown(target);
const allNames = new Set(allFiles.map(p => path.basename(p, '.md')));

for (const dir of GOVERNED_DIRS) {
  for (const file of walkMarkdown(path.join(target, dir))) {
    const rel = path.relative(target, file);
    const text = fs.readFileSync(file, 'utf8');
    const { fields } = parseFrontmatter(text);
    if (!fields) {
      warnings.push(`${rel}: missing frontmatter`);
    } else {
      for (const f of REQUIRED_FIELDS) {
        if (!(f in fields)) warnings.push(`${rel}: missing frontmatter field '${f}'`);
      }
      // A superseded or retired item has had its review. Otherwise the 90 days run from
      // the later of timestamp and reviewed_at (an unreadable or future date counts as absent).
      const bare = v => String(v || '').trim().replace(/^["']|["']$/g, '');
      const dates = [fields.timestamp, fields.reviewed_at].map(d => Date.parse(bare(d)))
        .filter(d => !Number.isNaN(d) && d <= Date.now() + 86400000);
      const closed = CLOSED_STATUSES.includes(bare(fields.status));
      if (!closed && dates.length && (Date.now() - Math.max(...dates)) / 86400000 > STALE_DAYS) {
        warnings.push(`${rel}: stale (timestamp and reviewed_at older than ${STALE_DAYS} days — review or supersede)`);
      }
    }
    for (const m of text.matchAll(/\[\[([^\]]+)\]\]/g)) {
      const name = m[1].trim();
      if (!allNames.has(name)) warnings.push(`${rel}: orphan link [[${name}]]`);
    }
  }
}
for (const file of allFiles) {
  for (const hit of scanSensitive(fs.readFileSync(file, 'utf8'))) {
    security.push(`${path.relative(target, file)}: sensitive content (${hit})`);
  }
}

// Report — fail open on write errors.
try {
  const rdir = path.join(target, 'reports', 'lint');
  fs.mkdirSync(rdir, { recursive: true });
  const fmt = xs => xs.map(x => `- ${x}`).join('\n') || '- none';
  fs.writeFileSync(path.join(rdir, `${todayStamp()}.md`),
    `# brain-lint — ${todayStamp()}\n\n## Security (${security.length})\n${fmt(security)}\n\n## Warnings (${warnings.length})\n${fmt(warnings)}\n`);
} catch { /* fail open */ }

for (const s of security) console.error(`SECURITY ${s}`);
for (const w of warnings) console.error(`warn ${w}`);
console.log(`brain-lint: ${security.length} security finding(s), ${warnings.length} warning(s)`);
process.exit(security.length ? 3 : 0);
