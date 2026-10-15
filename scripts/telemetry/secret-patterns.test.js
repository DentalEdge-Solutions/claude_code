#!/usr/bin/env node
// Tests for scripts/telemetry/secret-patterns.js — the one secret-pattern list shared by the
// brain's sensitive-content gate (scripts/brain/brain-lib.js scanSensitive) and telemetry
// redaction (scripts/telemetry/redact.js redactString). P1 of the PR #4 triage: the two
// lists had diverged, so each missed token formats the other caught.
//
// Fake tokens are assembled from pieces at runtime so no token-shaped literal sits in the
// source (keeps GitHub secret scanning and the repo's own scanners quiet).
'use strict';
const path = require('path');

let ok = true;
function test(label, fn) {
  try { fn(); console.log(`PASS ${label}`); }
  catch (e) { console.error(`FAIL ${label}: ${e.message}`); ok = false; }
}

const brain = require(path.join(__dirname, '..', 'brain', 'brain-lib.js'));
const redact = require(path.join(__dirname, 'redact.js'));

const rep = (c, n) => c.repeat(n);
const SAMPLES = {
  'anthropic-api-key':   'sk-' + 'ant-' + 'api03-' + rep('q', 40),
  'anthropic-admin-key': 'sk-' + 'ant-' + 'admin01-' + rep('w', 40),
  'openai-style-key':    'sk-' + rep('A', 24),
  'github-token':        'gh' + 'p_' + rep('r', 36),
  'github-server-token': 'gh' + 's_' + rep('t', 36),
  'github-fine-grained': 'github' + '_pat_' + rep('Z', 30),
  'slack-token':         'xox' + 'b-' + rep('1', 12) + '-' + rep('2', 12) + '-' + rep('a', 24),
  'aws-access-key-id':   'AK' + 'IA' + rep('Q', 16),
  'google-api-key':      'AI' + 'za' + rep('X', 35),
  'private-key-header':  '-----BEGIN ' + 'PRIVATE KEY-----',
  'jwt':                 'ey' + 'J' + rep('a', 20) + '.ey' + 'J' + rep('b', 20) + '.' + rep('c', 20),
  'bearer-token':        'Authorization: Bear' + 'er ' + rep('z', 32),
  'secret-assignment':   'api_' + 'key = ' + rep('k', 24),
  'short-password':      'pass' + 'word = hunter22',
};
const BENIGN = [
  'we decided to use pipeline() here',
  'the task-runner and risk-assessment steps run in order',
  'tokens are counted per scenario; see the token budget table',
  'Bearer of bad news: the eval failed',
];

test('brain scanSensitive catches every shared token format', () => {
  const missed = Object.entries(SAMPLES).filter(([, s]) => brain.scanSensitive(`text ${s} text`).length === 0);
  if (missed.length) throw new Error(`missed: ${missed.map(([k]) => k).join(', ')}`);
});

test('telemetry redactString removes every shared token format', () => {
  const leaked = Object.entries(SAMPLES).filter(([, s]) => {
    const out = redact.redactString(`text ${s} text`);
    return !out.includes('[REDACTED]') || out.includes(s.slice(-12));
  });
  if (leaked.length) throw new Error(`not redacted: ${leaked.map(([k]) => k).join(', ')}`);
});

test('a complete private-key block is redacted from BEGIN through END', () => {
  const block = '-----BEGIN RSA ' + 'PRIVATE KEY-----\n' + rep('M', 64) + '\n-----END RSA ' + 'PRIVATE KEY-----';
  const out = redact.redactString(`before\n${block}\nafter`);
  if (out.includes(rep('M', 64)) || out.includes('END RSA')) throw new Error(`block not fully redacted: ${out}`);
});

test('benign prose is not flagged by the brain gate', () => {
  const flagged = BENIGN.filter((s) => brain.scanSensitive(s).length > 0);
  if (flagged.length) throw new Error(`false positives: ${flagged.join(' | ')}`);
});

test('brain and telemetry use the single shared list', () => {
  const shared = require(path.join(__dirname, 'secret-patterns.js'));
  if (brain.SENSITIVE_CONTENT_PATTERNS !== shared.SECRET_PATTERNS) throw new Error('brain-lib does not use the shared list');
  const names = shared.SECRET_PATTERNS.map((p) => p.name);
  if (new Set(names).size !== names.length) throw new Error('duplicate pattern names');
  if (redact.SECRET_PATTERNS.length !== shared.SECRET_PATTERNS.length) throw new Error('redact.js does not derive from the shared list');
});

process.exit(ok ? 0 : 1);
