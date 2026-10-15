#!/usr/bin/env node
/**
 * The one secret-pattern list for this repo, shared by:
 *   - scripts/brain/brain-lib.js  scanSensitive()  — the brain's refusal gate (capture, promote, lint)
 *   - scripts/telemetry/redact.js redactString()   — telemetry redaction
 *
 * Lives under scripts/telemetry/ because install.sh always installs telemetry (step 7) and only
 * ever installs the brain (opt-in step 8) in the same run, so the brain can always require it.
 *
 * Union of the two lists that had diverged (P1, PR #4 triage). Where they differed, the broader
 * form won: deliberately broad, because a false positive costs a redaction or a refused capture
 * while a false negative leaks a secret. Patterns carry no `g` flag; redact.js adds it.
 * Tests: scripts/telemetry/secret-patterns.test.js.
 *
 * No dependencies.
 */
'use strict';

const SECRET_PATTERNS = Object.freeze([
  { name: 'anthropic-api-key', re: /sk-ant-[A-Za-z0-9_-]{10,}/ },           // api03, admin01, oat… keys
  { name: 'openai-style-key', re: /sk-[A-Za-z0-9]{20,}/ },
  { name: 'github-token', re: /gh[pousr]_[A-Za-z0-9]{20,}/ },               // ghp_ gho_ ghu_ ghs_ ghr_
  { name: 'github-fine-grained-pat', re: /github_pat_[A-Za-z0-9_]{20,}/ },
  { name: 'slack-token', re: /xox[baprs]-[A-Za-z0-9-]{10,}/ },
  { name: 'aws-access-key-id', re: /AKIA[0-9A-Z]{16}/ },
  { name: 'google-api-key', re: /AIza[0-9A-Za-z_-]{20,}/ },
  // A complete block is matched whole (so redaction removes the key body); a lone header still matches.
  { name: 'private-key', re: /-----BEGIN [A-Z ]*PRIVATE KEY-----(?:[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----)?/ },
  { name: 'jwt', re: /eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}/ },
  { name: 'bearer-token', re: /Bearer\s+[A-Za-z0-9._-]{15,}/i },
  { name: 'secret-assignment', re: /(?:api[_-]?key|apikey|secret|token|password|passwd)["']?\s*[:=]\s*["']?[A-Za-z0-9_\-./+]{12,}["']?/i },
  { name: 'password-assignment', re: /\bpassword\s*[:=]\s*['"]?[^\s'"]{4,}/i },
]);

module.exports = { SECRET_PATTERNS };
