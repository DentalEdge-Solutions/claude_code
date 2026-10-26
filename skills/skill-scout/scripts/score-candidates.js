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
//     source_url: string,         // https://github.com/<org>/<repo>/tree/<commit_hash>[/<path>], <= 500 chars:
//                                 // the ref is exactly commit_hash (tree only, never blob); org in GitHub's login
//                                 // charset, no '.'/'..' segments, no %, ?, #, \, @, port or userinfo
//     commit_hash: string,        // the full commit sha: 40 lowercase hex (PR5-R-20; never a branch name)
//     commit_date?: string,       // optional, informational: YYYY-MM-DD
//     repo_stars: integer >= 0,
//     repo_age_days: integer >= 0,
//     license: string | null,     // <= 100 chars, one line; null when unknown
//     skill_md_lines: integer >= 0,
//     has_scripts: boolean,
//     has_reference: boolean,
//     flags: [ { location, kind, excerpt } ], // <= 20; kind "instruction" | "secret" | "hidden-text";
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
//    a hidden-text code point (HIDDEN_TEXT_RE: controls, format, private use, default-ignorable, noncharacters,
//    U+2028/2029; tab, newline and carriage return allowed) in any string, nesting deeper than 16, an input
//    larger than INPUT_MAX_BYTES (checked before decoding). Invalid UTF-8 or a leading
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
// PR5-R-2: the largest input accepted, checked on the file size before decoding or parsing. Derivation (worst
// case, every character written as JSON escapes: 6 bytes per BMP code point, 12 per astral one):
//   per candidate: description 1024 x 12 = 12,288; flags 20 x (100 + 100 code points x 12 + ~60 syntax)
//   = 49,200; license 100 x 12 = 1,200; name, URL, commit, numbers, booleans, keys, hits ~3,000: ~66 KB;
//   x 6 candidates (CANDIDATES_MAX, enforced) = ~400 KB;
//   caller fields: installed_skill_descriptions, ASSUMED 200 skills x 1024 x 12 = ~2.5 MB (not enforced per item:
//   the caller reads them from local SKILL.md files); keywords and plugins ~0.1 MB.
//   The 4 MiB cap bounds the whole input whatever the assumption; it is checked on stat and on the bytes read.
// Total ~3 MB in a pathological case (real output is plain text, ~0.1-0.3 MB), so 4 MiB. It also stays
// below the ~8 MB single-string size at which a backtracking regex used to overflow V8's stack.
const INPUT_MAX_BYTES = 4 * 1024 * 1024;
const FLAGS_MAX = 20;
const CANDIDATES_MAX = 6;    // PR5-R-18: the agent fetches at most 6 candidates
const AGENT_CANDIDATE_KEYS = [
  'name', 'source_url', 'commit_hash', 'commit_date', 'repo_stars', 'repo_age_days', 'license',
  'skill_md_lines', 'has_scripts', 'has_reference', 'flags', 'description', 'body_keyword_hits',
];
const OPTIONAL_KEYS = new Set(['commit_date']); // informational; commit_hash is required (PR5-R-20)
const AGENT_TOP_KEYS = ['trigger_keywords', 'installed_skill_descriptions', 'plugin_names', 'candidates'];
const FLAG_KEYS = ['location', 'kind', 'excerpt'];
// instruction: text aimed at an AI; secret: something that looks like a secret (excerpt = its kind, never its
// value); hidden-text: invisible characters the agent removed from a field (excerpt = what and how many).
const FLAG_KINDS = ['instruction', 'secret', 'hidden-text'];
// Names that suggest body text, so the message says why the key is refused.
const BODY_LIKE_RE = /content|body|text|markdown|readme|raw|skill_md(?!_lines$)/i;
// PR5-R-6: the only key names ever printed. Any other key is outside text (even an identifier such as
// SYSTEM_do_this) and is described by its length only.
const KNOWN_BODY_KEYS = ['skill_md_content', 'skill_md_body', 'skill_md', 'body', 'content', 'text', 'raw', 'raw_text', 'markdown', 'readme'];

const HELP = `Usage: node score-candidates.js <candidates.json>
       node score-candidates.js --agent-output <agent-input.json>

Score and rank skill candidates against project needs.

Arguments:
  candidates.json        Legacy form: JSON array of candidate objects (schema below)
  --agent-output <file>  Strict form used by skill-scout for skill-scout-agent's output:
                         one JSON object in a regular file (not a pipe or
                         device), validated before scoring (schema below)

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
  candidates: at most ${CANDIDATES_MAX} (the agent's fetch limit)
  candidate (closed key set, all required except commit_date):
    name               string, 1-${NAME_CAP} chars of letters, digits, . _ -
    source_url         string, https://github.com/<org>/<repo>/tree/<commit_hash>[/<path>]
                       (the ref equals commit_hash; tree only, never blob),
                       <= ${URL_CAP} chars; org: GitHub login charset; no '.' or '..'
                       segments; no %, ?, #, \\, @, port or userinfo
    commit_hash        string, the full commit sha: 40 lowercase hex
    commit_date        optional, informational: YYYY-MM-DD
    repo_stars         integer >= 0
    repo_age_days      integer >= 0
    license            string (one line, <= ${LICENSE_CAP} chars) or null
    skill_md_lines     integer >= 0
    has_scripts        boolean
    has_reference      boolean
    flags              array (<= ${FLAGS_MAX}) of { location, kind, excerpt }:
                       kind "instruction" | "secret" | "hidden-text"; location and excerpt
                       one-line strings, <= ${LOCATION_CAP} and <= ${EXCERPT_CAP} chars
    description        string, <= ${DESCRIPTION_CAP} characters (Agent Skills spec maximum)
    body_keyword_hits  array of distinct elements of trigger_keywords (verbatim)
  Never skill_md_content or any other body field. Project fit uses
  description + body_keyword_hits.
  Also rejected, at any depth: a duplicate key, a number not written as
  plain digits (1.0, 1e2, 1e+21, -0, 1e400, beyond 2^53), a lone surrogate
  or a control, format (bidi, zero-width, tag), private-use,
  default-ignorable or noncharacter code point, or U+2028/U+2029, in any
  string (tab, newline and carriage return are allowed), nesting deeper
  than 16 levels, and a file larger than ${INPUT_MAX_BYTES} bytes (checked
  first, before decoding).

Exit codes:
  0  scored
  1  usage error, unreadable file, invalid JSON, or in --agent-output mode
     invalid UTF-8 or a leading byte-order mark (in --agent-output mode the
     parser's message is withheld: it can quote the untrusted input)
  2  --agent-output input rejected: one stderr line per problem, naming the
     candidate index and key, never the offending value (a key outside the
     schema is described by its length, never named)

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

// Source org trust level derived from URL. In agent-output mode the org comes from the validated URL
// (githubOrg); the legacy form keeps its regex.
function scoreSourceReputation(candidate, validatedOrg) {
  if (!candidate.source_url) return 5;
  let org = validatedOrg;
  if (org === undefined) {
    const match = candidate.source_url.match(/github\.com\/([^/]+)\//i);
    org = match ? match[1].toLowerCase() : '';
  }
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

function scoreCandidate(c, validatedOrg) {
  const trigger_precision  = scoreTriggerPrecision(c.description);
  const clarity            = scoreClarity(c);
  const context_footprint  = scoreContextFootprint(c.skill_md_lines || 0);
  const project_fit        = scoreProjectFit(c);
  const provenance         = scoreProvenance(c);
  const source_reputation  = scoreSourceReputation(c, validatedOrg);
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
  const scored = candidates.map(c => scoreCandidate(c)); // not map(scoreCandidate): the index is not an org
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
const KNOWN_KEYS = new Set([...AGENT_TOP_KEYS, ...AGENT_CANDIDATE_KEYS, ...FLAG_KEYS, ...KNOWN_BODY_KEYS]);
const keyLabel = k => (KNOWN_KEYS.has(k) ? k : `<an unknown key of ${codePoints(k)} characters>`);

// PR5-R-1: https://github.com/<org>/<repo>[/<segment>...]. Returns the lower-cased org, or null when the URL
// is not in that shape. Org: GitHub's login charset (letters, digits, single inner hyphens, 1-39). Repo and
// segments: letters, digits, '.', '_', '-' (segments also '~', '+'), never '.' or '..'; no %, ?, #, \\, @, ':'.
const GH_PREFIX = 'https://github.com/';
const ORG_RE = /^[A-Za-z0-9](?:[A-Za-z0-9]|-(?=[A-Za-z0-9])){0,38}$/;
const REPO_RE = /^[A-Za-z0-9._-]{1,100}$/;
const SEGMENT_RE = /^[A-Za-z0-9._~+-]{1,200}$/;
// PR5-R-20: the third and fourth segments are "tree" and exactly the pinned commit.
function refIsPin(url, pin) {
  const segs = url.slice(GH_PREFIX.length).split('/');
  return segs[2] === 'tree' && segs[3] === pin;
}
function githubOrg(url) {
  if (typeof url !== 'string' || !url.startsWith(GH_PREFIX) || url.length > URL_CAP) return null;
  const [org, repo, ...rest] = url.slice(GH_PREFIX.length).split('/');
  if (!ORG_RE.test(org) || repo === undefined || !REPO_RE.test(repo)) return null;
  for (const seg of [repo, ...rest]) if (seg === '.' || seg === '..' || !SEGMENT_RE.test(seg)) return null;
  return org.toLowerCase();
}

// ─── Strict reader for --agent-output (background security review of 908764b: parser differential) ──
// JSON.parse keeps the last of two equal keys, so a first value the main session may have read would never
// be validated. This reader accepts exactly JSON.parse's grammar (it runs only after JSON.parse succeeded,
// and decodes every string and number token with JSON.parse itself) and also reports, by path:
//   - a duplicate key at any depth (keys compared after decoding, so "description" = "description");
//   - a number not written as plain digits (1e400, 1.0, 1e2, 1e+21, -0, beyond 2^53): the token must match
//     -?(0|[1-9][0-9]*), be a safe integer and equal String(value) (PR5-R-11);
//   - text that is not well-formed or not visible as written (HIDDEN_TEXT_RE, by Unicode property, astral
//     planes included): lone surrogates, controls other than tab, newline and carriage return, format
//     characters (bidi controls, zero-width characters, tag characters U+E0000-E007F, musical-symbol format
//     characters, U+FEFF ...), private use, default-ignorable code points (variation selectors, CGJ, Hangul
//     fillers ...), noncharacters, and the line and paragraph separators U+2028/U+2029;
//   - nesting deeper than MAX_DEPTH (the schema needs 4).
// Objects are built without a prototype and with own data properties only, so "__proto__", "constructor"
// and the like are ordinary keys (all outside the schema). Linear time: each character is consumed once;
// strings are scanned by a loop, not a regex, so no string length can overflow the stack (PR5-R-2).
const MAX_DEPTH = 16;
const WS_RE = /[ \t\n\r]*/y;
const NUM_RE = /-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?/y;
const PLAIN_INT_RE = /^-?(?:0|[1-9]\d*)$/;
const LONE_SURROGATE_RE = /[\uD800-\uDBFF](?![\uDC00-\uDFFF])|(?<![\uD800-\uDBFF])[\uDC00-\uDFFF]/;
// One character class with the u flag, so it sees code points (astral ones too); test() on it is linear.
// Property names are ECMA-262 general categories and binary properties (supported since Node 10).
// No exception, not even ZWJ or a variation selector inside an emoji: either can carry text.
const HIDDEN_TEXT_RE = /(?![\t\n\r])[\p{Cc}\p{Cf}\p{Co}\p{Cs}\p{Zl}\p{Zp}\p{Default_Ignorable_Code_Point}\p{Noncharacter_Code_Point}]/u;
// The reason a string is refused, or null. Lone surrogates first, for a precise message.
function hiddenTextProblem(str) {
  if (LONE_SURROGATE_RE.test(str)) return 'text is not well-formed Unicode (lone surrogate)';
  if (HIDDEN_TEXT_RE.test(str)) return 'text contains a control, format, private-use, invisible or noncharacter code point';
  return null;
}
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
  // PR5-R-2: strings are scanned by hand (no regex, no recursion), then decoded by JSON.parse itself.
  const readStringToken = () => {
    if (text[i] !== '"') throw new SyntaxError('unexpected token');
    let j = i + 1;
    for (;;) {
      const c = text.charCodeAt(j);
      if (Number.isNaN(c)) throw new SyntaxError('unterminated string');
      if (c === 0x22) break;
      if (c === 0x5c) { j += 2; continue; } // the escape itself is checked by JSON.parse below
      if (c < 0x20) throw new SyntaxError('control character in a string');
      j++;
    }
    const raw = text.slice(i, j + 1);
    i = j + 1;
    return JSON.parse(raw);
  };
  const badText = hiddenTextProblem;
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
        const key = readStringToken();
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
      const v = readStringToken();
      const problem = badText(v);
      if (problem) errors.push(`${path || 'input'}: ${problem}`);
      return v;
    }
    for (const [lit, v] of [['true', true], ['false', false], ['null', null]]) {
      if (text.startsWith(lit, i)) { i += lit.length; return v; }
    }
    const raw = token(NUM_RE);
    const n = JSON.parse(raw);
    if (!PLAIN_INT_RE.test(raw) || !Number.isSafeInteger(n) || String(n) !== raw) {
      errors.push(`${path || 'input'}: number not written as plain digits within 2^53 (it would be read or shown as another value)`);
    }
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
  if (candidates.length > CANDIDATES_MAX) errors.push(`candidates: more than ${CANDIDATES_MAX} entries (${candidates.length})`);

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
    check('source_url', v => githubOrg(v) !== null,
      `must be https://github.com/<org>/<repo>[/<segment>...], at most ${URL_CAP} characters, without '.' or '..' segments, %, ?, #, \\, @ or a port`);
    check('commit_hash', v => typeof v === 'string' && /^[0-9a-f]{40}$/.test(v),
      'must be the full commit sha: 40 lowercase hex characters (never a branch name or an abbreviated sha)');
    // PR5-R-20: the URL must point at exactly the pinned commit, so what is audited and adapted is what is shown.
    if (githubOrg(c.source_url) !== null && typeof c.commit_hash === 'string' && !refIsPin(c.source_url, c.commit_hash)) {
      errors.push(`${at}.source_url: must be https://github.com/<org>/<repo>/tree/<commit_hash>[/<path>] (the ref must equal commit_hash)`);
    }
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
          if (Object.hasOwn(f, 'kind') && !FLAG_KINDS.includes(f.kind)) errors.push(`${p}.kind: must be one of ${FLAG_KINDS.join(', ')}`);
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
  const scored = input.candidates.map(c => ({ s: scoreCandidate({ ...c, ...caller }, githubOrg(c.source_url) || ''), c }));
  scored.sort((a, b) => b.s.total_score - a.s.total_score);
  return scored.map(({ s, c }) => {
    const out = { ...s };
    if (Object.hasOwn(c, 'commit_date')) out.commit_date = c.commit_date;
    Object.assign(out, { repo_stars: c.repo_stars, license: c.license, description: c.description, flags: c.flags });
    return out;
  });
}

// Reads at most `limit` bytes of a regular file (PR5-R-21: a pipe, FIFO or device is refused, so a read can never
// wait or spin; PR5-R-17: the read stays bounded for a file that grows after stat).
class NotRegularFile extends Error {}
function readBounded(filePath, limit) {
  const fd = fs.openSync(filePath, 'r');
  try {
    if (!fs.fstatSync(fd).isFile()) throw new NotRegularFile('not a regular file');
    const chunks = [];
    let total = 0;
    while (total < limit) {
      const chunk = Buffer.alloc(Math.min(64 * 1024, limit - total));
      const n = fs.readSync(fd, chunk, 0, chunk.length, null);
      if (n === 0) break;
      chunks.push(chunk.subarray(0, n));
      total += n;
    }
    return Buffer.concat(chunks, total);
  } finally {
    fs.closeSync(fd);
  }
}
const oversize = buf => buf.length > INPUT_MAX_BYTES;

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
  const reject = why => {
    console.error(`score-candidates: rejected agent output: ${why}`);
    console.error('score-candidates: nothing scored. Do not repair the input by hand: stop and report this problem.');
    process.exit(2);
  };
  let st;
  try { st = fs.statSync(filePath); } catch (e) { fail(`cannot read the file (${e.code || 'error'})`); }
  // PR5-R-21: only a regular file (checked here before opening, and on the open descriptor in readBounded).
  if (!st.isFile()) reject('input: must be a regular file');
  if (st.size > INPUT_MAX_BYTES) reject(`input: larger than ${INPUT_MAX_BYTES} bytes (${st.size} bytes); the size rule is checked before decoding`);
  // PR5-R-17: stat cannot see a file that grows after it, so the read itself is bounded (at most
  // INPUT_MAX_BYTES + 1 bytes) and the bytes read are checked again.
  let buf;
  try { buf = readBounded(filePath, INPUT_MAX_BYTES + 1); } catch (e) {
    if (e instanceof NotRegularFile) reject('input: must be a regular file');
    fail(`cannot read the file (${e.code || 'error'})`);
  }
  if (oversize(buf)) reject(`input: larger than ${INPUT_MAX_BYTES} bytes (read more than the cap); the size rule is checked before decoding`);
  let text;
  try {
    text = new TextDecoder('utf-8', { fatal: true, ignoreBOM: true }).decode(buf);
  } catch (e) {
    fail(e instanceof TypeError ? 'not valid UTF-8' : `cannot read the file (${e.code || 'error'})`);
  }
  if (text.startsWith('\uFEFF')) fail('the file starts with a byte-order mark');
  let read;
  try {
    JSON.parse(text);
  } catch (e) {
    if (e instanceof RangeError) reject('input: too large or too deeply nested to read');
    fail('not valid JSON');
  }
  try {
    read = strictRead(text);
  } catch (e) {
    // JSON.parse accepted the text, so a failure here is a resource limit or a reader bug, never "invalid JSON".
    reject(e instanceof RangeError ? 'input: too large or too deeply nested to read' : 'input: could not be read strictly');
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
  DESCRIPTION_CAP, EXCERPT_CAP, AGENT_CANDIDATE_KEYS, AGENT_TOP_KEYS, FLAG_KINDS, INPUT_MAX_BYTES,
  hiddenTextProblem, githubOrg, strictRead, oversize, readBounded, CANDIDATES_MAX,
  validateAgentInput, scoreAll, scoreAgentInput,
};
if (require.main === module) main(process.argv.slice(2));
