#!/usr/bin/env node
// scripts/claude-settings.test.js — tests for this repo's own .claude/settings.json deny rules (HR1).
//
// HR1 (docs/evaluations/2026-10-14-gsd-global-install-audit.md §7): secret files in this repo that the
// global GSD secret-read guard does not cover (the Hermes container home, the credential pool) were
// readable by Claude Code. The project settings now deny Read and Edit on them. A Read deny also covers
// Edit/Write; the Edit rule adds NotebookEdit (code.claude.com/docs/en/permissions, read 2026-10-19).
//
// Project settings load only from the session's starting folder (no parent fallback), and a `/path`
// rule is anchored there (code.claude.com/docs/en/permissions and /settings, read 2026-10-19). So the
// rules are committed twice: at the repo root and in infra/hermes-agent/, where sessions also start
// (independent review H1). Sessions in worktrees reading the main tree by absolute path need the
// user-level rules (layer B in docs/evaluations/2026-10-19-hr1-secret-read-controls.md).
//
// The matcher below covers only `/`-anchored patterns, `**/<name>` and a bare `<name>` (both "any
// depth" in the docs). It refuses every other form, including unanchored patterns with a `/` whose
// anchoring the docs and measured behaviour disagree on (review H5), so a rule it cannot judge fails
// the test instead of passing silently.
'use strict';
const assert = require('assert');
const fs = require('fs');
const path = require('path');
const { spawnSync } = require('child_process');

const REPO = path.join(__dirname, '..');
// Each settings file and the repo folder its `/` rules are anchored at.
const SETTINGS_FILES = [
  { dir: '', file: path.join(REPO, '.claude', 'settings.json'), telemetry: true },
  { dir: 'infra/hermes-agent', file: path.join(REPO, 'infra', 'hermes-agent', '.claude', 'settings.json') },
];

// Secret files (present or expected) that must be unreadable to Claude Code's tools in this repo.
const PROTECTED = [
  'infra/hermes-agent/.env',
  'infra/hermes-agent/.env.ga',
  'infra/hermes-agent/.env.gaw',
  'infra/hermes-agent/.env.pr',
  'infra/hermes-agent/data/auth.json',
  'infra/hermes-agent/data/home/.claude/settings.json',
  'infra/hermes-agent/data/home/.claude/projects/-projects-claude-code/session.jsonl',
  'infra/hermes-agent/data/profiles/architect/.env',
  'infra/hermes-agent/data/.claude/settings.json',
  'infra/hermes-agent/data/.claude/projects/-opt-data/session.jsonl',
  'infra/hermes-agent/data/.claude.json',
  'some/other/dir/.env',
  '.env',
];

// Files sessions must still be able to read.
const READABLE = [
  'infra/hermes-agent/.env.example',
  'infra/hermes-agent/.env.ga.example',
  'infra/hermes-agent/data/config.yaml',
  'infra/hermes-agent/data/logs/gateway.log',
  'infra/hermes-agent/data/profiles/architect/SOUL.md',
  '.claude/settings.json',
];

let ok = true;
function test(label, fn) {
  try { fn(); console.log(`PASS ${label}`); }
  catch (e) { console.error(`FAIL ${label}: ${e.message}`); ok = false; }
}

// Repo-relative path → does the rule's path pattern match it?
function globToRegExp(pattern) {
  if (/[?[\]{}!\\]/.test(pattern) || pattern.startsWith('~') || pattern.startsWith('//') || pattern.startsWith('./')
      || (!pattern.startsWith('/') && pattern.replace(/^\*\*\//, '').includes('/'))) {
    throw new Error(`rule path form not supported by this test: ${pattern}`);
  }
  const anchored = pattern.startsWith('/');
  const body = anchored ? pattern.slice(1) : pattern;
  let re = '';
  for (let i = 0; i < body.length; i++) {
    if (body.startsWith('**/', i)) { re += '(?:.*/)?'; i += 2; }
    else if (body.startsWith('**', i)) { re += '.*'; i += 1; }
    else if (body[i] === '*') re += '[^/]*';
    else re += body[i].replace(/[.+^$()|]/g, '\\$&');
  }
  return new RegExp(`^${anchored ? '' : '(?:.*/)?'}${re}$`);
}

function rulesFor(tool, deny) {
  return deny
    .map(r => r.match(new RegExp(`^${tool}\\((.*)\\)$`)))
    .filter(Boolean)
    .map(m => ({ rule: `${tool}(${m[1]})`, re: globToRegExp(m[1]) }));
}

test('the matcher reads anchored, any-depth and wildcard forms the way the docs describe', () => {
  assert.ok(globToRegExp('/a/b/**').test('a/b/c/d'));
  assert.ok(!globToRegExp('/a/b/**').test('x/a/b/c'));
  assert.ok(globToRegExp('**/.env').test('.env') && globToRegExp('**/.env').test('x/y/.env'));
  assert.ok(globToRegExp('.env').test('x/.env'));
  assert.ok(globToRegExp('/a/*/.env').test('a/p/.env') && !globToRegExp('/a/*/.env').test('a/p/q/.env'));
  assert.ok(!globToRegExp('/a/.env').test('a/.env.example'));
  for (const bad of ['~/x', 'data/home/**', '*/.env', '//abs', './x']) assert.throws(() => globToRegExp(bad), bad);
});

const r = spawnSync('git', ['ls-files', '-z'], { cwd: REPO, encoding: 'utf8' });
const tracked = r.status === 0 ? r.stdout.split('\0').filter(Boolean) : [];
test('git ls-files lists the repo', () => assert.ok(tracked.length > 100, r.stderr));

// Repo-relative paths under `dir`, made relative to it (the paths a session started there sees).
const under = (dir, paths) => paths.filter(p => !dir || p.startsWith(dir + '/')).map(p => (dir ? p.slice(dir.length + 1) : p));

for (const { dir, file, telemetry } of SETTINGS_FILES) {
  const where = path.relative(REPO, file);
  let deny = [];
  test(`${where} parses and holds a deny list`, () => {
    const settings = JSON.parse(fs.readFileSync(file, 'utf8'));
    deny = (settings.permissions && settings.permissions.deny) || [];
    assert.ok(deny.length > 0);
    if (telemetry) assert.ok(settings.hooks && settings.hooks.PostToolUse && settings.hooks.Stop, 'telemetry hooks missing');
  });

  for (const tool of ['Read', 'Edit']) {
    test(`${where}: every protected secret path under ${dir || 'the repo root'} has a ${tool} deny rule`, () => {
      const rules = rulesFor(tool, deny);
      assert.deepStrictEqual(under(dir, PROTECTED).filter(p => !rules.some(x => x.re.test(p))), []);
    });
  }

  test(`${where}: no deny rule matches a path sessions must still read, or a tracked file`, () => {
    const rules = [...rulesFor('Read', deny), ...rulesFor('Edit', deny)];
    const paths = [...under(dir, READABLE), ...under(dir, tracked)];
    assert.deepStrictEqual(paths.flatMap(p => rules.filter(x => x.re.test(p)).map(x => `${p} ← ${x.rule}`)), []);
  });

  test(`${where}: every Read deny rule has a matching Edit rule, and deny holds only Read/Edit rules`, () => {
    const read = deny.filter(x => x.startsWith('Read(')).map(x => x.slice(5));
    const edit = deny.filter(x => x.startsWith('Edit(')).map(x => x.slice(5));
    assert.deepStrictEqual(edit.sort(), read.sort());
    assert.deepStrictEqual(deny.filter(x => !/^(Read|Edit)\(/.test(x)), []);
  });
}

// ── P0-07: ask rules for consequential commands ─────────────────────────────────────────────────────────────
// docs/evaluations/2026-10-26-p0-07-p0-08-ask-rules-staged-deploys.md. The two committed settings files carry the
// same `permissions.ask` list; their deny lists stay exactly the HR1 set above. The checks below read the rule
// strings with a model of the documented Bash matching (code.claude.com/docs/en/permissions, read 2026-10-26):
//   - a `*` matches any text, spaces included, and everything outside a `*` is matched as written;
//   - a trailing ` *` that is the rule's only wildcard also matches the bare command (`git push`);
//   - a deny or ask rule applies when ANY subcommand of a compound command matches (`&&`, `||`, `;`, `|`, `|&`,
//     `&`, newline), and it matches past a leading variable assignment and the stripped wrappers.
// This proves the rule strings cover the intended command texts under that model. It does not prove Claude Code
// prompts: that is the owner's probe in the record (auto mode, fresh session).

// The roadmap list (S5 P0-07), in its order, then the home-variable and no-slash forms the record adds.
const ASK_RULES = [
  'Bash(git push *)', 'Bash(gh pr merge *)', 'Bash(gh pr review *)', 'Bash(gh api *)', 'Bash(gh auth *)',
  'Bash(git push * --delete *)', 'Bash(git branch -D *)', 'Bash(node scripts/brain/brain-promote.js *)',
  'Bash(cp * ~/.claude/skills/*)', 'Bash(cp -r * ~/.claude/skills/*)', 'Bash(cp -R * ~/.claude/skills/*)',
  'Bash(./install.sh*)', 'Bash(bash install.sh*)', 'Bash(./uninstall.sh*)', 'Bash(bash uninstall.sh*)',
  'Bash(cp * ~/.claude/skills)', 'Bash(cp * $HOME/.claude/skills*)', 'Bash(cp * "$HOME/.claude/skills*)',
  'Bash(cp * "$HOME"/.claude/skills*)',
];

// The HR1 deny lists, in their committed order (P0-07 leaves them unchanged): the same names, anchored at the
// Hermes folder from each file's own folder.
const HR1_ANCHOR = { '': '/infra/hermes-agent/', 'infra/hermes-agent': '/' };
function hr1Deny(dir) {
  const anchor = HR1_ANCHOR[dir];
  const names = ['.env.ga', '.env.gaw', '.env.pr', 'data/auth.json', 'data/home/**', 'data/.claude/**', 'data/.claude.json'];
  const one = tool => [`${tool}(**/.env)`, ...names.map(n => `${tool}(${anchor}${n})`)];
  return [...one('Read'), ...one('Edit')];
}

// A Bash rule's specifier → RegExp over one subcommand's text, per the model above.
function bashRuleRe(spec) {
  const stars = (spec.match(/\*/g) || []).length;
  const esc = s => s.replace(/[.+?^${}()|[\]\\]/g, '\\$&');
  if (stars === 1 && spec.endsWith(' *')) return new RegExp(`^${esc(spec.slice(0, -2))}(?: .*)?$`, 's');
  return new RegExp(`^${spec.split('*').map(esc).join('.*')}$`, 's');
}
const WRAPPERS = /^(?:(?:timeout(?: -k \S+)? \S+|time|nice(?: -n \S+)?|nohup|stdbuf(?: -\S+)*|command|builtin|noglob) )/;
// The subcommands a deny or ask rule is checked against (not quote-aware: fixtures only).
function subcommands(cmd) {
  return cmd.split(/\|&|&&|\|\||[;|&\n]/).map(s => {
    let t = s.trim().replace(/^[({]\s*/, '').replace(/^\$\(\s*/, '');
    for (let prev = ''; prev !== t;) { prev = t; t = t.replace(/^[A-Za-z_][A-Za-z0-9_]*=\S*\s+/, '').replace(WRAPPERS, ''); }
    return t.replace(/\s*[)}]$/, '');
  }).filter(Boolean);
}
const bashSpecs = rules => rules.map(r => r.match(/^Bash\((.*)\)$/)).filter(Boolean).map(m => ({ rule: m[0], re: bashRuleRe(m[1]) }));
const askedBy = (rules, cmd) => bashSpecs(rules).filter(x => subcommands(cmd).some(s => x.re.test(s))).map(x => x.rule);

// Commands that must prompt: each consequential action in the S5 P0-07 list, in the forms Claude usually writes.
const MUST_ASK = [
  'git push', 'git push origin main', 'git push -u origin fix/x', 'git push --force-with-lease origin fix/x',
  'git push origin --delete fix/x', 'git add -A && git commit -m x && git push', 'timeout 60 git push origin fix/x',
  'GIT_TRACE=1 git push origin fix/x', 'cd /tmp/repo; git push',
  'gh pr merge 12 --squash', 'gh pr merge', 'gh pr review 12 --approve', 'gh api repos/o/r/pulls/12/merge -X PUT',
  'gh api repos/o/r/pulls/12', 'gh auth status', 'gh auth token', 'gh auth login --with-token',
  'git branch -D fix/x', 'node scripts/brain/brain-promote.js --approve x',
  'cp -r skills/skill-refine ~/.claude/skills/', 'cp -R skills/skill-refine/. ~/.claude/skills/skill-refine/',
  'cp -R skills/skill-adapt ~/.claude/skills', 'cp skills/x/SKILL.md ~/.claude/skills/x/SKILL.md',
  'cp -R skills/x/. $HOME/.claude/skills/x/', 'cp -R skills/x "$HOME/.claude/skills/x/"', 'cp -R skills/x "$HOME"/.claude/skills/',
  './install.sh /tmp/target', './install.sh', 'bash install.sh /tmp/target', './uninstall.sh /tmp/target', 'bash uninstall.sh',
];
// Routine commands that must not prompt because of these rules (other rules and the mode still decide them).
const MUST_NOT_ASK = [
  'git status', 'git commit -m "push the fix"', 'git log --oneline origin/main..HEAD', 'git branch -d fix/x',
  'git checkout -b fix/x', 'gh pr view 12', 'gh pr create --draft --title x --body y', 'gh pr list',
  'node scripts/run-all-tests.js', 'node scripts/check-skill-deploy.js', 'bash -n install.sh uninstall.sh',
  'cp -R skills/x/. evals/x/adapt-backup-1/', 'cp evals/x/refine/pre-iter-3/SKILL.md skills/x/SKILL.md',
  'cp ~/.claude/skills/x/SKILL.md /tmp/x.md', 'node scripts/brain/brain-search.js promote',
];
// Forms the record lists as residuals (rules are not a security boundary). Pinned so the residual list stays true.
const KNOWN_ESCAPES = [
  'git -C . push origin main', 'git -c push.default=current push', "git 'push' origin main",
  'rsync -a skills/x/ ~/.claude/skills/x/', 'cp -R skills/x ${HOME}/.claude/skills/', 'cp -R skills/x /Users/u/.claude/skills/',
  'node -e "require(\'https\').request(\'https://api.github.com\')"', 'bash ./install.sh /tmp/t', 'sh install.sh /tmp/t',
  'node ./scripts/brain/brain-promote.js --approve x',
];

test('the Bash rule model reads the documented examples the way the docs table does', () => {
  const m = (spec, cmd) => bashRuleRe(spec).test(cmd);
  assert.ok(m('npm run build', 'npm run build') && !m('npm run build', 'npm run build --watch'));
  assert.ok(m('npm run *', 'npm run build') && m('npm run *', 'npm run') && !m('npm run *', 'npm install'));
  assert.ok(m('git log * main', 'git log --oneline main') && !m('git log * main', 'git log main'));
  assert.ok(m('* --version', 'node --version') && !m('* --version', 'node -v'));
  assert.ok(m('ls *', 'ls -la') && m('ls *', 'ls') && !m('ls *', 'lsof') && m('ls*', 'lsof'));
  assert.ok(m('* --help *', 'npm --help x') && !m('* --help *', 'npm --help'));
  assert.ok(m('git push *', 'git push origin main') && !m('git push *', 'git -C . push origin main'));
  assert.deepStrictEqual(subcommands('cd /tmp && git clean -f'), ['cd /tmp', 'git clean -f']);
  assert.deepStrictEqual(subcommands('FOO=bar timeout 30 rm -rf tmp/'), ['rm -rf tmp/']);
});

for (const { dir, file } of SETTINGS_FILES) {
  const where = path.relative(REPO, file);
  let settings = {};
  try { settings = JSON.parse(fs.readFileSync(file, 'utf8')); } catch { /* reported by the parse test above */ }
  const perms = settings.permissions || {};
  const ask = perms.ask || [];

  test(`${where}: permissions.ask holds exactly the P0-07 list, in order, without duplicates (P0-07)`, () => {
    assert.deepStrictEqual(ask, ASK_RULES);
  });

  test(`${where}: the deny list is the HR1 set, unchanged, and permissions holds only deny and ask (P0-07)`, () => {
    assert.deepStrictEqual(perms.deny, hr1Deny(dir));
    assert.deepStrictEqual(Object.keys(perms).sort(), ['ask', 'deny']);
  });

  test(`${where}: every consequential command matches an ask rule (P0-07)`, () => {
    assert.deepStrictEqual(MUST_ASK.filter(c => askedBy(ask, c).length === 0), []);
  });

  test(`${where}: routine commands match no ask rule (P0-07)`, () => {
    assert.deepStrictEqual(MUST_NOT_ASK.flatMap(c => askedBy(ask, c).map(r => `${c} ← ${r}`)), []);
  });

  test(`${where}: the recorded residual forms still escape the ask rules (P0-07; update the record if one is caught)`, () => {
    assert.deepStrictEqual(KNOWN_ESCAPES.flatMap(c => askedBy(ask, c).map(r => `${c} ← ${r}`)), []);
  });

  test(`${where}: every ask rule is a Bash rule this test can read, and each one is reached by a fixture (P0-07)`, () => {
    for (const r of ask) assert.match(r, /^Bash\(.+\)$/, r);
    const reached = new Set(MUST_ASK.flatMap(c => askedBy(ask, c)));
    assert.deepStrictEqual(ask.filter(r => !reached.has(r)), []);
  });
}

test('the two committed settings files carry identical ask lists (P0-07)', () => {
  const [a, b] = SETTINGS_FILES.map(({ file }) => {
    try { return (JSON.parse(fs.readFileSync(file, 'utf8')).permissions || {}).ask; } catch { return undefined; }
  });
  assert.ok(Array.isArray(a) && a.length > 0, 'root ask list missing');
  assert.deepStrictEqual(b, a);
});

if (!ok) process.exit(1);
console.log('\nAll claude-settings tests passed.');
