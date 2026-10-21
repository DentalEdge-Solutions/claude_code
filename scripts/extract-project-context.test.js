// scripts/extract-project-context.test.js — the 9-field project-context.json contract of
// skills/skill-eval/scripts/extract-project-context.js, the files each field comes from, and
// preservation of project-audit's fields (P12). Lives in scripts/ for the same reason as
// harvest-evidence.test.js: files under skills/ ship to target projects.
// HOME points at a temp folder, so the test never reads the real ~/.claude/settings.json.
'use strict';
const { spawnSync } = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');
const assert = require('assert');

const SCRIPT = path.join(__dirname, '..', 'skills', 'skill-eval', 'scripts', 'extract-project-context.js');
const TMP = fs.mkdtempSync(path.join(os.tmpdir(), 'extract-context-test-'));
const HOME = path.join(TMP, 'home');
const PROJECT = path.join(TMP, 'my-project');

function write(file, text) {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, text);
}
function extract(root, args = [root]) {
  const r = spawnSync('node', [SCRIPT, ...args], {
    encoding: 'utf8', cwd: root, env: { ...process.env, HOME, USERPROFILE: HOME },
  });
  assert.strictEqual(r.status, 0, r.stderr);
  return { stdout: JSON.parse(r.stdout), file: JSON.parse(fs.readFileSync(path.join(root, 'evals', 'project-context.json'), 'utf8')) };
}

try {
  write(path.join(PROJECT, 'package.json'), JSON.stringify({
    name: 'demo-app', description: 'A demo app for tests',
    dependencies: { react: '18', express: '4' }, devDependencies: { typescript: '5' },
    engines: { node: '>=18' },
  }));
  write(path.join(PROJECT, 'CLAUDE.md'),
    '# Demo\n\nRun TDD with the GSD workflow. Use pnpm for installs.\nArtifacts live in `./dist/out` and `.planning/STATE.md`.\n');
  write(path.join(PROJECT, 'README.md'), '# Demo\n\nThe demo app shows how the pipeline works.\n');
  write(path.join(PROJECT, 'skills', 'skill-a', 'SKILL.md'), 'x');
  write(path.join(PROJECT, 'skills', 'skill-b', 'SKILL.md'), 'x');
  write(path.join(PROJECT, 'skills', 'not-a-dir.md'), 'x');
  write(path.join(PROJECT, '.claude', 'settings.json'), JSON.stringify({ hooks: {
    PreToolUse: [{ matcher: 'Bash', hooks: [{ type: 'command', command: 'bash "$CLAUDE_PROJECT_DIR/hooks/guard.sh"' }] }],
  } }));
  write(path.join(PROJECT, '.mcp.json'), JSON.stringify({ mcpServers: { github: {}, context7: {} } }));
  write(path.join(HOME, '.claude', 'settings.json'), JSON.stringify({
    enabledPlugins: { 'superpowers@claude-plugins-official': true, 'gsd@local': true },
    hooks: { Stop: [{ hooks: [{ type: 'command', command: 'node /x/log-outcome.js --mode stop' }] }] },
  }));
  // A prior file from project-audit: its security fields must survive; the rest is rebuilt.
  write(path.join(PROJECT, 'evals', 'project-context.json'), JSON.stringify({
    project_name: 'stale', security_grade: 'B', security_score: 0, security_last_scanned: '2026-10-01',
    audited_repos: ['github.com/x/y'], audit_signals: { architecture_patterns: ['mvc'], ref_stack_extended: [] },
  }));

  const { stdout, file } = extract(PROJECT);

  // 1. stdout and the written file are the same object.
  assert.deepStrictEqual(stdout, file, 'stdout matches evals/project-context.json');

  // 2. The 9 contract fields, each from its source.
  assert.strictEqual(file.project_name, 'demo-app', 'package.json name wins over the folder name');
  assert.deepStrictEqual(file.stack, ['React', 'Express', 'TypeScript', 'Node.js'], 'deps + engines.node');
  assert.ok(file.workflow_terms.includes('TDD') && file.workflow_terms.includes('GSD'), 'CLAUDE.md acronyms');
  assert.deepStrictEqual(file.installed_skills.sort(), ['skill-a', 'skill-b'], 'skill directories only');
  assert.ok(file.key_phrases.includes('A demo app for tests'), 'package.json description');
  assert.ok(file.key_phrases.includes('pnpm'), 'a "Use X" convention from CLAUDE.md');
  assert.ok(file.key_phrases.includes('The demo app shows how the pipeline works.'), 'README first line');
  assert.deepStrictEqual(file.artifact_paths, ['./dist/out', '.planning/STATE.md'], 'backticked paths');
  assert.deepStrictEqual(file.hooks, [
    { event: 'PreToolUse', matcher: 'Bash', command: 'guard.sh' },
    { event: 'Stop', matcher: null, command: 'log-outcome.js' },
  ], 'project hooks, then global hooks, reduced to the script name');
  assert.deepStrictEqual(file.mcp_servers, ['github', 'context7'], '.mcp.json');
  assert.deepStrictEqual(file.plugins, ['superpowers', 'gsd'], 'enabledPlugins without @marketplace');

  // 3. project-audit's fields survive the rewrite, including a falsy score of 0.
  assert.strictEqual(file.security_grade, 'B');
  assert.strictEqual(file.security_score, 0, 'a score of 0 is preserved');
  assert.strictEqual(file.security_last_scanned, '2026-10-01');
  assert.deepStrictEqual(file.audited_repos, ['github.com/x/y']);
  assert.deepStrictEqual(file.audit_signals.architecture_patterns, ['mvc']);

  // 4. An empty project: folder name, empty arrays, no crash; pyproject.toml supplies name + stack.
  const empty = path.join(TMP, 'bare-proj');
  fs.mkdirSync(empty);
  let out = extract(empty).file;
  assert.strictEqual(out.project_name, 'bare-proj');
  for (const k of ['stack', 'workflow_terms', 'installed_skills', 'key_phrases', 'artifact_paths', 'mcp_servers'])
    assert.deepStrictEqual(out[k], [], `${k} empty`);
  const py = path.join(TMP, 'py-proj');
  write(path.join(py, 'pyproject.toml'), '[project]\nname = "py-svc"\ndependencies = ["fastapi"]\n');
  out = extract(py).file;
  assert.strictEqual(out.project_name, 'py-svc');
  assert.deepStrictEqual(out.stack, ['FastAPI']);

  // 5. Malformed JSON inputs are skipped, not fatal.
  const broken = path.join(TMP, 'broken');
  write(path.join(broken, 'package.json'), '{nope');
  write(path.join(broken, '.mcp.json'), '{nope');
  out = extract(broken).file;
  assert.strictEqual(out.project_name, 'broken');
  assert.deepStrictEqual(out.mcp_servers, []);

  // 6. Other sources (review P12-4): CLAUDE.md under .claude/ when the root has none,
  //    .planning/REQUIREMENTS.md terms and paths, and django from pyproject.toml.
  const alt = path.join(TMP, 'alt-proj');
  write(path.join(alt, '.claude', 'CLAUDE.md'), 'Follow the SPEC rules.\n');
  write(path.join(alt, '.planning', 'REQUIREMENTS.md'), 'The Order Service owns `./orders/db`.\n');
  write(path.join(alt, 'pyproject.toml'), '[project]\nname = "alt"\ndependencies = ["django"]\n');
  out = extract(alt).file;
  assert.ok(out.workflow_terms.includes('SPEC'), '.claude/CLAUDE.md fallback');
  assert.ok(out.key_phrases.includes('The Order Service'), '.planning Title-Case phrase');
  assert.ok(out.artifact_paths.includes('./orders/db'), '.planning backticked path');
  assert.deepStrictEqual(out.stack, ['Django']);
  // artifact_paths is capped at 10, in order of appearance.
  const many = path.join(TMP, 'many-paths');
  write(path.join(many, 'CLAUDE.md'), Array.from({ length: 12 }, (_, i) => `See \`./p${i}\`.`).join('\n'));
  out = extract(many).file;
  assert.deepStrictEqual(out.artifact_paths, Array.from({ length: 10 }, (_, i) => `./p${i}`), 'first 10 paths');

  // 7. A null entry, or a null hook inside an entry, is skipped; the other hooks in the same file
  //    are still read (review G11: the TypeError was caught and the whole file's hooks dropped).
  const nul = path.join(TMP, 'null-hooks');
  write(path.join(nul, '.claude', 'settings.json'), JSON.stringify({ hooks: {
    PreToolUse: [null, { matcher: 'Bash', hooks: [null, { type: 'command', command: 'bash "$CLAUDE_PROJECT_DIR/hooks/guard.sh"' }] }],
    Stop: [{ hooks: [{ type: 'command', command: 'node /x/after-null.js' }] }],
  } }));
  out = extract(nul).file;
  assert.deepStrictEqual(out.hooks, [
    { event: 'PreToolUse', matcher: 'Bash', command: 'guard.sh' },
    { event: 'Stop', matcher: null, command: 'after-null.js' },
    { event: 'Stop', matcher: null, command: 'log-outcome.js' },
  ], 'hooks read past null entries, project then global');

  // 8. --help exits 0 and writes nothing (review P12-3: without the early exit the script
  //    would treat "--help" as the project root and write --help/evals/).
  const helpCwd = path.join(TMP, 'help-cwd');
  fs.mkdirSync(helpCwd);
  const r = spawnSync('node', [SCRIPT, '--help'], { encoding: 'utf8', cwd: helpCwd, env: { ...process.env, HOME } });
  assert.strictEqual(r.status, 0);
  assert.ok(r.stdout.includes('Usage'));
  assert.deepStrictEqual(fs.readdirSync(helpCwd), [], '--help writes nothing');

  console.log('extract-project-context.test.js: all assertions passed');
} finally {
  fs.rmSync(TMP, { recursive: true, force: true });
}
