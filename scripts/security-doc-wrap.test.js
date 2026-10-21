// scripts/security-doc-wrap.test.js — docs/SECOND_BRAIN_SECURITY.md keeps its prose wrapped:
// the text wraps at about 90 characters, and edits that appended a sentence to a line left
// lines of 104 to 122 (review G12). No line may pass 100 characters.
'use strict';
const assert = require('assert');
const fs = require('fs');
const path = require('path');

const FILE = path.join(__dirname, '..', 'docs', 'SECOND_BRAIN_SECURITY.md');
const MAX = 100;

const long = fs.readFileSync(FILE, 'utf8').split('\n')
  .map((line, i) => ({ n: i + 1, len: [...line].length }))
  .filter(l => l.len > MAX);
assert.deepStrictEqual(long, [], `lines over ${MAX} characters: ${long.map(l => `${l.n} (${l.len})`).join(', ')}`);
console.log('security-doc-wrap.test.js: all assertions passed');
