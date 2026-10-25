#!/usr/bin/env node
// score-candidates.js <candidates.json>
// score-candidates.js --agent-output <agent-input.json>
// Scores skill candidates against project needs.
// Output: sorted JSON array with scores and STRONG/GOOD/MARGINAL/SKIP recommendation.
//
// Two input forms.
//
// 1. Legacy form (unchanged): a JSON array of candidate objects.
// {
//   name: string,
//   source_url: string,
//   commit_hash: string,
//   description: string,
//   skill_md_content?: string,           // full SKILL.md text — used for body matching
//   body_keyword_hits?: string[],        // used instead of the body when skill_md_content is absent
//   skill_md_lines: number,
//   has_scripts: boolean,
//   has_reference: boolean,
//   repo_age_days: number,
//   repo_stars: number,
//   trigger_keywords: string[],          // user-supplied: words describing the needed capability
//   installed_skill_descriptions: string[] // descriptions of currently installed skills
//   plugin_names: string[]                 // names of installed plugins (from project-context.json:plugins)
// }
//
// 2. Agent-output form (--agent-output, P0-05): what skill-scout writes after skill-scout-agent returns.
//    The agent is a read-only fetcher of untrusted pages; it returns fields, never the SKILL.md body.
//    The input is validated strictly before anything is scored. One JSON object, exactly these keys:
// {
//   trigger_keywords: string[],              // caller-supplied (skill-scout), the same list the agent got
//   installed_skill_descriptions: string[],  // caller-supplied
//   plugin_names: string[],                  // caller-supplied
//   candidates: [ {                          // the agent's JSON array, verbatim; closed key set:
//     name: string,               // 1-64 chars, letters/digits/._- only, no spaces
//     source_url: string,         // https://github.com/..., no whitespace, <= 500 chars
//     commit_hash?: string,       // 7-40 hex chars; or, when no hash is resolvable:
//     commit_date?: string,       // YYYY-MM-DD (at least one of the two; never a branch name)
//     repo_stars: integer >= 0,
//     repo_age_days: integer >= 0,
//     license: string | null,     // <= 100 chars, one line; null when unknown
//     skill_md_lines: integer >= 0,
//     has_scripts: boolean,
//     has_reference: boolean,
//     flags: [ { location, kind, excerpt } ], // <= 20; kind "instruction" | "secret";
//                                 // location and excerpt one-line strings <= 100 chars
//                                 // (for a secret the excerpt names its kind, never its value)
//     description: string,        // <= 1024 characters (code points): the Agent Skills spec maximum
//     body_keyword_hits: string[] // each element one of trigger_keywords, verbatim, no duplicates
//   } ]
// }
//    Any key outside the set (skill_md_content or any other body field among them), a description over the
//    cap, a wrong type, a hit outside trigger_keywords or an excerpt over 100 characters rejects the whole
//    input: exit 2, one stderr line per problem naming the candidate index and key, never the offending value,
//    nothing on stdout. So does anything where the validated value could differ from the raw text (see
//    strictRead): a duplicate key at any depth, a number not written as a plain integer, a lone surrogate or
//    a control, bidi or invisible character in any string, nesting deeper than 16. Invalid UTF-8 or a leading
//    byte-order mark exit 1. Project fit then uses description + body_keyword_hits (the body is absent), which
//    gives the same score as the body form when the hits were computed by the same substring rule.
//    The shortlist is presented from this script's stdout (the validated values), never from the agent's reply.

const fs = require('fs');

// Agent-output contract (P0-05). DESCRIPTION_CAP: the Agent Skills specification's maximum for a skill
// `description` ("Max 1024 characters", agentskills.io/specification, accessed 2026-10-25), so no conforming
// description is ever truncated.
const DESCRIPTION_CAP = 1024;
const EXCERPT_CAP = 100;       // the untrusted-content rule's excerpt limit (P0-06)
const LOCATION_CAP = 100;
const LICENSE_CAP = 100;
const NAME_CAP = 64;           // the spec's `name` maximum
const URL_CAP = 500;
const FLAGS_MAX = 20;
const AGENT_CANDIDATE_KEYS = [
  'name', 'source_url', 'commit_hash', 'commit_date', 'repo_stars', 'repo_age_days', 'license',
  'skill_md_lines', 'has_scripts', 'has_reference', 'flags', 'description', 'body_keyword_hits',
];
const OPTIONAL_KEYS = new Set(['commit_hash', 'commit_date']); // at least one of the two is required
const AGENT_TOP_KEYS = ['trigger_keywords', 'installed_skill_descriptions', 'plugin_names', 'candidates'];
const FLAG_KEYS = ['location', 'kind', 'excerpt'];
const FLAG_KINDS = new Set(['instruction', 'secret']);
// Names that suggest body text, so the message says why the key is refused.
const BODY_LIKE_RE = /content|body|text|markdown|readme|raw|skill_md(?!_lines$)/i;

const HELP = `Usage: node score-candidates.js <candidates.json>
       node score-candidates.js --agent-output <agent-input.json>

Score and rank skill candidates against project needs.

Arguments:
  candidates.json        Legacy form: JSON array of candidate objects (schema below)
  --agent-output <file>  Strict form used by skill-scout for skill-scout-agent's output:
                         one JSON object, validated before scoring (schema below)

Output:
  Sorted JSON array written to stdout. Each entry adds: total_score,
  recommendation (STRONG|GOOD|MARGINAL|SKIP), and per-dimension scores.
  In --agent-output mode each entry also carries the validated commit_date
  (if given), repo_stars, license, description and flags.

Legacy candidate schema:
  name, source_url, commit_hash, description, skill_md_content?,
  body_keyword_hits?, skill_md_lines, has_scripts, has_reference,
  repo_age_days, repo_stars, trigger_keywords[],
  installed_skill_descriptions[], plugin_names[]

--agent-output input (exactly these keys):
  { "trigger_keywords": [string], "installed_skill_descriptions": [string],
    "plugin_names": [string], "candidates": [candidate] }
  candidate (closed key set, all required except one of commit_hash/commit_date):
    name               string, 1-${NAME_CAP} chars of letters, digits, . _ -
    source_url         string, https://github.com/..., no whitespace, <= ${URL_CAP} chars
    commit_hash        string, 7-40 hex chars   } at least one; never a
    commit_date        string, YYYY-MM-DD       } branch name
    repo_stars         integer >= 0
    repo_age_days      integer >= 0
    license            string (one line, <= ${LICENSE_CAP} chars) or null
    skill_md_lines     integer >= 0
    has_scripts        boolean
    has_reference      boolean
    flags              array (<= ${FLAGS_MAX}) of { location, kind, excerpt }:
                       kind "instruction" | "secret"; location and excerpt
                       one-line strings, <= ${LOCATION_CAP} and <= ${EXCERPT_CAP} chars
    description        string, <= ${DESCRIPTION_CAP} characters (Agent Skills spec maximum)
    body_keyword_hits  array of distinct elements of trigger_keywords (verbatim)
  Never skill_md_content or any other body field. Project fit uses
  description + body_keyword_hits.
  Also rejected, at any depth: a duplicate key, a number not written as a
  plain integer (1.0, 1e2, -0, 1e400, beyond 2^53), a lone surrogate or a
  control, bidi or invisible format character in any string (tab and
  newline are allowed), nesting deeper than 16 levels.

Exit codes:
  0  scored
  1  usage error, unreadable file, invalid JSON, or in --agent-output mode
     invalid UTF-8 or a leading byte-order mark (in --agent-output mode the
     parser's message is withheld: it can quote the untrusted input)
  2  --agent-output input rejected: one stderr line per problem, naming the
     candidate index and key, never the offending value

Examples:
  node skills/skill-scout/scripts/score-candidates.js candidates.json
  node skills/skill-scout/scripts/score-candidates.js --agent-output "$SCRATCH/scout-input.json"
  node skills/skill-scout/scripts/score-candidates.js candidates.json | jq '.[0]'`;

// Orgs with established track records in the Claude Code skills ecosystem.
// Tier 1 — Canonical: maintained by Anthropic or official tooling partners
const TRUSTED_ORGS_T1 = new Set([
  'anthropics', 'anthropic',        // Anthropic official (github.com/anthropics)
  'vercel-labs', 'vercel',          // Vercel skills registry
]);

// Tier 2 — Ecosystem builders: registries, frameworks, and high-quality skill collections
const TRUSTED_ORGS_T2 = new Set([
  'multica-ai',                     // Karpathy-style skills registry
  'composiohq',                     // awesome-claude-skills registry
  'evol-ai',                        // SkillCompass registry
  'affaan-m',                       // ECC ecosystem (AgentShield, security guides)
  'mattpocock',                     // Grilling skill; TypeScript educator, quality patterns
  'chriswiles',                     // claude-code-showcase; comprehensive CC reference
  'thedotmack',                     // claude-mem plugin; CC memory ecosystem
  'mksglu',                         // context-mode plugin
]);

// Tier 3 — Known good: project-owner org; skills here should always be trusted
const TRUSTED_ORGS_T3 = new Set([
  'dentaledgesolutions',
  'microsoft', 'google',            // large platform orgs; rarely publish CC skills but trusted
]);

// Union used for scoring — all tiers treated equally in the binary trusted/untrusted check.
// Callers that need tier-aware scoring can inspect the individual sets directly.
const TRUSTED_ORGS = new Set([
  ...TRUSTED_ORGS_T1,
  ...TRUSTED_ORGS_T2,
  ...TRUSTED_ORGS_T3,
]);

function scoreTriggerPrecision(desc) {
  if (!desc) return 0;
  let score = 0;
  if (/use when/i.test(desc)) score += 5;
  if (desc.split(/[,;]/).length >= 2) score += 3;
  if (/when (user|asked|request)/i.test(desc)) score += 2;
  return Math.min(score, 10);
}

// Scripts presence is neutral — they add power but also attack surface.
// has_reference is the primary structural quality signal.
function scoreClarity(candidate) {
  let score = 0;
  if (candidate.has_reference) score += 4;
  if (candidate.skill_md_lines >= 20) score += 3;
  if (candidate.skill_md_lines >= 40) score += 3;
  return Math.min(score, 10);
}

function scoreContextFootprint(lines) {
  if (lines <= 50)  return 10;
  if (lines <= 100) return 7;
  if (lines <= 150) return 5;
  if (lines <= 200) return 3;
  return 1;
}

// Match against the description and the full SKILL.md body when available. When the body is absent
// (agent-output form), the body's matches come from body_keyword_hits: the trigger keywords the
// fetcher found in the body by the same rule (case-insensitive substring). A keyword found in both
// counts once.
function scoreProjectFit(candidate) {
  if (!candidate.trigger_keywords || candidate.trigger_keywords.length === 0) return 5;
  const hasBody = typeof candidate.skill_md_content === 'string';
  const searchText = [
    candidate.description || '',
    hasBody ? candidate.skill_md_content : '',
  ].join(' ').toLowerCase();
  const bodyHits = new Set(!hasBody && Array.isArray(candidate.body_keyword_hits) ? candidate.body_keyword_hits : []);
  const hits = candidate.trigger_keywords.filter(kw => searchText.includes(kw.toLowerCase()) || bodyHits.has(kw));
  return Math.round((hits.length / candidate.trigger_keywords.length) * 10);
}

// Repo age and stars as a combined maturity signal.
function scoreProvenance(candidate) {
  let score = 5;
  const stars = candidate.repo_stars || 0;
  const age   = candidate.repo_age_days || 0;
  if (stars >= 1000)     score += 3;
  else if (stars >= 100) score += 2;
  else if (stars >= 10)  score += 1;
  if (age < 7)           score -= 4;
  else if (age < 30)     score -= 2;
  else if (age >= 180)   score += 2;
  return Math.max(0, Math.min(score, 10));
}

// Source org trust level derived from URL.
function scoreSourceReputation(candidate) {
  if (!candidate.source_url) return 5;
  const match = candidate.source_url.match(/github\.com\/([^/]+)\//i);
  const org = match ? match[1].toLowerCase() : '';
  if (TRUSTED_ORGS.has(org))                                                return 10;
  if ((candidate.repo_stars || 0) >= 500)                                   return 7;
  if ((candidate.repo_stars || 0) >= 100)                                   return 5;
  if ((candidate.repo_stars || 0) === 0 && (candidate.repo_age_days || 0) < 30) return 1;
  return 4;
}

function scoreConflictRisk(candidate) {
  const words = (candidate.description || '').toLowerCase().split(/\W+/).filter(w => w.length > 4);

  // Exact name match with an installed plugin → full conflict (score 0)
  const pluginNames = (candidate.plugin_names || []).map(p => p.toLowerCase());
  if (candidate.name && pluginNames.includes(candidate.name.toLowerCase())) return 0;

  // Keyword overlap with installed skill descriptions
  const descriptions = candidate.installed_skill_descriptions || [];
  if (!descriptions.length && !pluginNames.length) return 10;

  let maxOverlap = 0;
  for (const installed of descriptions) {
    const iWords = installed.toLowerCase().split(/\W+/).filter(w => w.length > 4);
    const overlap = words.filter(w => iWords.includes(w)).length;
    maxOverlap = Math.max(maxOverlap, overlap / Math.max(words.length, 1));
  }
  // Plugin names as weak keyword signals (name-level overlap, not description-level)
  for (const plugin of pluginNames) {
    const pWords = plugin.split(/[-_]/).filter(w => w.length > 3);
    const overlap = words.filter(w => pWords.includes(w)).length;
    maxOverlap = Math.max(maxOverlap, (overlap / Math.max(words.length, 1)) * 0.7); // 70% weight vs full description
  }
  return Math.round((1 - maxOverlap) * 10);
}

const WEIGHTS = {
  trigger_precision:  0.25,
  clarity:            0.20,
  context_footprint:  0.15,
  project_fit:        0.15,
  provenance:         0.10,
  source_reputation:  0.10,
  conflict_risk:      0.05,
};

function scoreCandidate(c) {
  const trigger_precision  = scoreTriggerPrecision(c.description);
  const clarity            = scoreClarity(c);
  const context_footprint  = scoreContextFootprint(c.skill_md_lines || 0);
  const project_fit        = scoreProjectFit(c);
  const provenance         = scoreProvenance(c);
  const source_reputation  = scoreSourceReputation(c);
  const conflict_risk      = scoreConflictRisk(c);

  const total = Math.round(
    trigger_precision  * WEIGHTS.trigger_precision  +
    clarity            * WEIGHTS.clarity            +
    context_footprint  * WEIGHTS.context_footprint  +
    project_fit        * WEIGHTS.project_fit        +
    provenance         * WEIGHTS.provenance         +
    source_reputation  * WEIGHTS.source_reputation  +
    conflict_risk      * WEIGHTS.conflict_risk,
  );

  return {
    name:          c.name,
    source_url:    c.source_url,
    commit_hash:   c.commit_hash,
    total_score:   total,
    breakdown:     { trigger_precision, clarity, context_footprint, project_fit, provenance, source_reputation, conflict_risk },
    recommendation: total >= 8 ? 'STRONG' : total >= 6 ? 'GOOD' : total >= 4 ? 'MARGINAL' : 'SKIP',
  };
}

function scoreAll(candidates) {
  const scored = candidates.map(scoreCandidate);
  scored.sort((a, b) => b.total_score - a.total_score);
  return scored;
}

// ─── Agent-output validation ────────────────────────────────────────────────────────────────
// Messages name a path (candidates[2].flags[0].excerpt) and a rule, never a value. A key is itself
// untrusted text, so an unknown key is named only if it is a short identifier; otherwise by its length.
const codePoints = s => Array.from(s).length;
const isObj = v => v !== null && typeof v === 'object' && !Array.isArray(v);
const isCount = v => Number.isInteger(v) && v >= 0;
const isOneLine = (v, max) => typeof v === 'string' && v.length > 0 && !/[\r\n]/.test(v) && codePoints(v) <= max;
const keyLabel = k => (/^[A-Za-z0-9_]{1,40}$/.test(k) ? k : `<a key of ${codePoints(k)} characters>`);

// ─── Strict reader for --agent-output (background security review of 908764b: parser differential) ──
// JSON.parse keeps the last of two equal keys, so a first value the main session may have read would never
// be validated. This reader accepts exactly JSON.parse's grammar (it runs only after JSON.parse succeeded,
// and decodes every string and number token with JSON.parse itself) and also reports, by path:
//   - a duplicate key at any depth (keys compared after decoding, so "description" = "description");
//   - a number whose raw token is not what would be shown (1e400, 1.0, 1e2, -0, beyond 2^53): the token
//     must equal String(value);
//   - text that is not well-formed or not visible as written: lone surrogates, C0 controls other than tab,
//     newline and carriage return, DEL, C1 controls, bidi controls, zero-width and invisible format
//     characters, U+2028/U+2029 and U+FEFF;
//   - nesting deeper than MAX_DEPTH (the schema needs 4).
// Objects are built without a prototype and with own data properties only, so "__proto__", "constructor"
// and the like are ordinary keys (all outside the schema). Linear time: each character is consumed once.
const MAX_DEPTH = 16;
const WS_RE = /[ \t\n\r]*/y;
const STR_RE = /"(?:[^"\\\u0000-\u001f]|\\["\\/bfnrt]|\\u[0-9a-fA-F]{4})*"/y;
const NUM_RE = /-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?/y;
const LONE_SURROGATE_RE = /[\uD800-\uDBFF](?![\uDC00-\uDFFF])|(?<![\uD800-\uDBFF])[\uDC00-\uDFFF]/;
const HIDDEN_CHAR_RE = /[\u0000-\u0008\u000B\u000C\u000E-\u001F\u007F-\u009F\u00AD\u061C\u180E\u200B\u200C\u200E\u200F\u2028-\u202E\u2060-\u2064\u2066-\u206F\uFEFF\uFFF9-\uFFFB]/;
class DepthError extends Error {}

function strictRead(text) {
  const errors = [];
  let i = 0;
  const skipWs = () => { WS_RE.lastIndex = i; WS_RE.exec(text); i = WS_RE.lastIndex; };
  const token = re => {
    re.lastIndex = i;
    const m = re.exec(text);
    if (!m) throw new SyntaxError('unexpected token');
    i = re.lastIndex;
    return m[0];
  };
  const expect = ch => { if (text[i] !== ch) throw new SyntaxError('unexpected token'); i++; };
  const badText = s => LONE_SURROGATE_RE.test(s) ? 'text is not well-formed Unicode (lone surrogate)'
    : HIDDEN_CHAR_RE.test(s) ? 'text contains a control, bidi or invisible format character' : null;
  const at = (path, key) => (path ? `${path}.${keyLabel(key)}` : keyLabel(key));
  function readValue(path, depth) {
    if (depth > MAX_DEPTH) throw new DepthError(path || 'input');
    skipWs();
    const ch = text[i];
    if (ch === '{') {
      i++;
      const obj = Object.create(null);
      skipWs();
      if (text[i] === '}') { i++; return obj; }
      for (;;) {
        skipWs();
        const key = JSON.parse(token(STR_RE));
        const p = at(path, key);
        const keyProblem = badText(key);
        if (keyProblem) errors.push(`${p}: key ${keyProblem}`);
        skipWs(); expect(':');
        const v = readValue(p, depth + 1);
        if (Object.hasOwn(obj, key)) errors.push(`${p}: duplicate key`);
        else Object.defineProperty(obj, key, { value: v, enumerable: true, writable: true, configurable: true });
        skipWs();
        if (text[i] === ',') { i++; continue; }
        expect('}');
        return obj;
      }
    }
    if (ch === '[') {
      i++;
      const arr = [];
      skipWs();
      if (text[i] === ']') { i++; return arr; }
      for (;;) {
        arr.push(readValue(`${path}[${arr.length}]`, depth + 1));
        skipWs();
        if (text[i] === ',') { i++; continue; }
        expect(']');
        return arr;
      }
    }
    if (ch === '"') {
      const v = JSON.parse(token(STR_RE));
      const problem = badText(v);
      if (problem) errors.push(`${path || 'input'}: ${problem}`);
      return v;
    }
    for (const [lit, v] of [['true', true], ['false', false], ['null', null]]) {
      if (text.startsWith(lit, i)) { i += lit.length; return v; }
    }
    const raw = token(NUM_RE);
    const n = JSON.parse(raw);
    if (String(n) !== raw) errors.push(`${path || 'input'}: number not written as a plain integer (it would be read as another value)`);
    return n;
  }
  let value;
  try {
    value = readValue('', 0);
  } catch (e) {
    if (e instanceof DepthError) return { value: undefined, errors: [`${e.message}: nested deeper than ${MAX_DEPTH} levels`] };
    throw e;
  }
  skipWs();
  if (i !== text.length) throw new SyntaxError('trailing data');
  return { value, errors };
}

function validateAgentInput(input) {
  const errors = [];
  if (!isObj(input)) {
    return ['input: must be one JSON object with the keys trigger_keywords, installed_skill_descriptions, plugin_names, candidates (a bare array is the legacy form)'];
  }
  for (const k of Object.keys(input)) {
    if (!AGENT_TOP_KEYS.includes(k)) errors.push(`${keyLabel(k)}: key not in the schema`);
  }
  for (const k of AGENT_TOP_KEYS) {
    if (!Object.hasOwn(input, k)) errors.push(`${k}: missing`);
  }
  for (const k of ['trigger_keywords', 'installed_skill_descriptions', 'plugin_names']) {
    if (!Object.hasOwn(input, k)) continue;
    if (!Array.isArray(input[k])) { errors.push(`${k}: must be an array of strings`); continue; }
    input[k].forEach((v, i) => { if (typeof v !== 'string' || (k !== 'installed_skill_descriptions' && v.length === 0)) errors.push(`${k}[${i}]: must be a non-empty string`); });
  }
  const keywords = Array.isArray(input.trigger_keywords) ? input.trigger_keywords : [];
  if (Object.hasOwn(input, 'candidates') && !Array.isArray(input.candidates)) errors.push('candidates: must be an array');
  const candidates = Array.isArray(input.candidates) ? input.candidates : [];

  candidates.forEach((c, i) => {
    const at = `candidates[${i}]`;
    if (!isObj(c)) { errors.push(`${at}: must be an object`); return; }
    for (const k of Object.keys(c)) {
      if (AGENT_CANDIDATE_KEYS.includes(k)) continue;
      errors.push(BODY_LIKE_RE.test(k)
        ? `${at}.${keyLabel(k)}: body field not allowed (the agent never returns SKILL.md text)`
        : `${at}.${keyLabel(k)}: key not in the schema`);
    }
    for (const k of AGENT_CANDIDATE_KEYS) {
      if (!OPTIONAL_KEYS.has(k) && !Object.hasOwn(c, k)) errors.push(`${at}.${k}: missing`);
    }
    const check = (k, ok, rule) => { if (Object.hasOwn(c, k) && !ok(c[k])) errors.push(`${at}.${k}: ${rule}`); };
    check('name', v => typeof v === 'string' && /^[A-Za-z0-9][A-Za-z0-9._-]*$/.test(v) && v.length <= NAME_CAP,
      `must be 1-${NAME_CAP} characters of letters, digits, '.', '_' or '-'`);
    check('source_url', v => typeof v === 'string' && /^https:\/\/github\.com\/[^\s]+$/.test(v) && v.length <= URL_CAP,
      `must be an https://github.com/ URL without whitespace, at most ${URL_CAP} characters`);
    if (!Object.hasOwn(c, 'commit_hash') && !Object.hasOwn(c, 'commit_date')) {
      errors.push(`${at}.commit_hash: missing (give commit_hash, or commit_date when no hash is resolvable)`);
    }
    check('commit_hash', v => typeof v === 'string' && /^[0-9a-f]{7,40}$/i.test(v), 'must be 7-40 hex characters (a commit, never a branch name)');
    check('commit_date', v => typeof v === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(v), 'must be a date in YYYY-MM-DD form');
    for (const k of ['repo_stars', 'repo_age_days', 'skill_md_lines']) check(k, isCount, 'must be an integer >= 0');
    for (const k of ['has_scripts', 'has_reference']) check(k, v => typeof v === 'boolean', 'must be true or false');
    check('license', v => v === null || isOneLine(v, LICENSE_CAP), `must be null or one line of at most ${LICENSE_CAP} characters`);
    check('description', v => typeof v === 'string', 'must be a string');
    if (typeof c.description === 'string' && codePoints(c.description) > DESCRIPTION_CAP) {
      errors.push(`${at}.description: longer than the ${DESCRIPTION_CAP}-character cap (${codePoints(c.description)} characters)`);
    }

    if (Object.hasOwn(c, 'body_keyword_hits')) {
      if (!Array.isArray(c.body_keyword_hits)) errors.push(`${at}.body_keyword_hits: must be an array`);
      else {
        const seen = new Set();
        c.body_keyword_hits.forEach((h, j) => {
          const p = `${at}.body_keyword_hits[${j}]`;
          if (typeof h !== 'string' || !keywords.includes(h)) errors.push(`${p}: not one of trigger_keywords (verbatim)`);
          else if (seen.has(h)) errors.push(`${p}: duplicate`);
          else seen.add(h);
        });
      }
    }

    if (Object.hasOwn(c, 'flags')) {
      if (!Array.isArray(c.flags)) errors.push(`${at}.flags: must be an array`);
      else {
        if (c.flags.length > FLAGS_MAX) errors.push(`${at}.flags: more than ${FLAGS_MAX} entries (${c.flags.length})`);
        c.flags.forEach((f, j) => {
          const p = `${at}.flags[${j}]`;
          if (!isObj(f)) { errors.push(`${p}: must be an object { location, kind, excerpt }`); return; }
          for (const k of Object.keys(f)) if (!FLAG_KEYS.includes(k)) errors.push(`${p}.${keyLabel(k)}: key not in the schema`);
          for (const k of FLAG_KEYS) if (!Object.hasOwn(f, k)) errors.push(`${p}.${k}: missing`);
          if (Object.hasOwn(f, 'kind') && !FLAG_KINDS.has(f.kind)) errors.push(`${p}.kind: must be "instruction" or "secret"`);
          if (Object.hasOwn(f, 'location') && !isOneLine(f.location, LOCATION_CAP)) errors.push(`${p}.location: must be one line of at most ${LOCATION_CAP} characters`);
          if (Object.hasOwn(f, 'excerpt') && !isOneLine(f.excerpt, EXCERPT_CAP)) errors.push(`${p}.excerpt: must be one line of at most ${EXCERPT_CAP} characters`);
        });
      }
    }
  });
  return errors;
}

function scoreAgentInput(input) {
  const caller = {
    trigger_keywords: input.trigger_keywords,
    installed_skill_descriptions: input.installed_skill_descriptions,
    plugin_names: input.plugin_names,
  };
  // Same order as scoreAll: by total, ties in input order (Array.prototype.sort is stable).
  const scored = input.candidates.map(c => ({ s: scoreCandidate({ ...c, ...caller }), c }));
  scored.sort((a, b) => b.s.total_score - a.s.total_score);
  return scored.map(({ s, c }) => {
    const out = { ...s };
    if (!Object.hasOwn(c, 'commit_hash')) delete out.commit_hash;
    if (Object.hasOwn(c, 'commit_date')) out.commit_date = c.commit_date;
    Object.assign(out, { repo_stars: c.repo_stars, license: c.license, description: c.description, flags: c.flags });
    return out;
  });
}

function main(argv) {
  const agentMode = argv[0] === '--agent-output';
  const filePath = agentMode ? argv[1] : argv[0];
  if (filePath === '--help' || filePath === '-h') {
    console.log(HELP);
    process.exit(0);
  }
  if (!filePath) {
    console.error('Usage: node score-candidates.js <candidates.json> | --agent-output <agent-input.json> (see --help)');
    process.exit(1);
  }

  if (!agentMode) {
    let input;
    try {
      input = JSON.parse(fs.readFileSync(filePath, 'utf8'));
    } catch (e) {
      console.error(`Failed to parse input: ${e.message}`);
      process.exit(1);
    }
    console.log(JSON.stringify(scoreAll(input), null, 2));
    return;
  }

  // Agent mode: the bytes must be valid UTF-8 (never silently replaced), with no leading byte-order mark,
  // valid JSON, then the strict reader. Parser messages are withheld: V8's JSON errors can quote the input.
  const fail = why => { console.error(`Failed to parse input: ${why}`); process.exit(1); };
  let text;
  try {
    text = new TextDecoder('utf-8', { fatal: true, ignoreBOM: true }).decode(fs.readFileSync(filePath));
  } catch (e) {
    fail(e instanceof TypeError ? 'not valid UTF-8' : `cannot read the file (${e.code || 'error'})`);
  }
  if (text.startsWith('\uFEFF')) fail('the file starts with a byte-order mark');
  let read;
  try {
    JSON.parse(text);
    read = strictRead(text);
  } catch (e) {
    fail('not valid JSON');
  }
  const errors = read.errors.length ? read.errors : validateAgentInput(read.value);
  const input = read.value;
  if (errors.length) {
    for (const e of errors) console.error(`score-candidates: rejected agent output: ${e}`);
    console.error(`score-candidates: ${errors.length} problem(s); nothing scored. Do not repair the input by hand: stop and report these problems.`);
    process.exit(2);
  }
  console.log(JSON.stringify(scoreAgentInput(input), null, 2));
}

module.exports = {
  DESCRIPTION_CAP, EXCERPT_CAP, AGENT_CANDIDATE_KEYS, AGENT_TOP_KEYS,
  validateAgentInput, scoreAll, scoreAgentInput,
};
if (require.main === module) main(process.argv.slice(2));
