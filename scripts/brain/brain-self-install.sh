#!/usr/bin/env bash
# scripts/brain/brain-self-install.sh — capsule + hook registration + .gitignore,
# ending with brain-verify. Idempotent.
# Used by install.sh step 8 (--with-second-brain); also runnable standalone.
# Usage: bash scripts/brain/brain-self-install.sh [target-dir]   (default: this repo)
set -euo pipefail
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TARGET="$(cd "${1:-${REPO_DIR}}" && pwd)"
BRAIN="${TARGET}/.project-brain"
T="${REPO_DIR}/templates/second-brain"

# 1. Capsule from template (install recipe from templates/second-brain/README.md)
if [ ! -d "${BRAIN}" ]; then
  cp -R "${T}/project-brain" "${BRAIN}"
  cp "${T}/BRAIN.md" "${T}/MEMORY.md" "${T}/README.md" "${BRAIN}/"
  cp "${T}/brain-profile.json" "${BRAIN}/context/brain-profile.json"
  NAME="$(basename "${TARGET}")"
  TODAY="$(date -u +%F)"
  node -e '
const fs = require("fs");
const [brain, name, today] = process.argv.slice(1);
const bm = brain + "/BRAIN.md";
fs.writeFileSync(bm, fs.readFileSync(bm, "utf8")
  .replaceAll("{{PROJECT_NAME}}", name).replaceAll("{{CREATED_AT}}", today));
const pf = brain + "/context/brain-profile.json";
const p = JSON.parse(fs.readFileSync(pf, "utf8"));
p.project_name = name;
p.project_slug = name.toLowerCase().replace(/[^a-z0-9]+/g, "-");
p.created_at = today;
fs.writeFileSync(pf, JSON.stringify(p, null, 2) + "\n");
' "${BRAIN}" "${NAME}" "${TODAY}"
  echo "✓ capsule created at ${BRAIN}"
else
  echo "✓ capsule already present — skipping template copy"
fi

# 2. Hook registration (merge, never clobber — same ensureHookEntry pattern as install.sh's
#    telemetry step). P0-09: the security guard goes into the SHARED .claude/settings.json, in
#    exec form with "onFailure": "block" and a 30 s timeout, so a guard that cannot start, fails or
#    times out blocks the call (commit hooks/brain/ with it: a registration whose script is missing
#    blocks every Write/Edit/Bash). The five other brain hooks stay fail-open in
#    .claude/settings.local.json, where an old shell-form guard registration (fail-open, before
#    P0-09) is removed. Both files are read and checked before either is written; a file it cannot
#    read stops the install here, both files unchanged (set -e). A file is written only if it changed.
mkdir -p "${TARGET}/.claude"
MERGED="$(node -e '
const fs = require("fs");
const dir = process.argv[1] + "/.claude";
// Never write a file this cannot read: it would replace the owner settings with ours (review N2,
// N3). Stop instead, so the guard hook is never silently missing. An empty file counts as {}.
function refuse(file, why) {
  process.stderr.write(`Error: ${file} was not changed: ${why}. Fix it, then re-run this installer.\n`);
  process.exit(3);
}
const plain = (v) => v !== null && typeof v === "object" && !Array.isArray(v);
function load(file, events) {
  const raw = fs.existsSync(file) ? fs.readFileSync(file, "utf8") : "";
  if (raw.charCodeAt(0) === 0xFEFF) refuse(file, "it starts with a byte-order mark; save it as UTF-8 without one");   // review P6
  let settings = {};
  if (raw.trim()) { try { settings = JSON.parse(raw); } catch (e) { refuse(file, `it is not valid JSON (${e.message})`); } }
  if (!plain(settings)) refuse(file, "it is not a JSON object");
  if (settings.hooks != null && !plain(settings.hooks)) refuse(file, "its \"hooks\" is not an object");
  for (const ev of events)
    if (settings.hooks && settings.hooks[ev] != null && !Array.isArray(settings.hooks[ev])) refuse(file, `its "hooks.${ev}" is not a list`);
  settings.hooks = settings.hooks || {};
  return { file, raw, settings };
}
const local = load(dir + "/settings.local.json", ["PreCompact", "SessionEnd", "Stop", "PreToolUse", "PostToolUse", "SessionStart"]);
const shared = load(dir + "/settings.json", ["PreToolUse"]);
const same = (h, want) => h && h.command === want.command && JSON.stringify(h.args || null) === JSON.stringify(want.args || null);
function ensureHookEntry(settings, eventName, matcher, handler) {
  settings.hooks[eventName] = settings.hooks[eventName] || [];
  const list = settings.hooks[eventName];
  const already = list.some((entry) => entry &&
    (entry.matcher || null) === (matcher || null) &&
    Array.isArray(entry.hooks) && entry.hooks.some((h) => same(h, handler)));
  if (already) return false;
  list.push({ ...(matcher ? { matcher } : {}), hooks: [{ ...handler }] });
  return true;
}
// Give every copy of handler on eventName, whatever its matcher, each default field it lacks
// (matching hooks run in parallel, so one copy without them would still fail open). A value the
// owner set is kept. Returns how many hooks it updated.
function ensureDefaults(settings, eventName, handler, defaults) {
  let n = 0;
  for (const entry of settings.hooks[eventName] || [])
    for (const h of Array.isArray(entry && entry.hooks) ? entry.hooks : []) {
      if (!same(h, handler)) continue;
      let changed = false;
      for (const [k, v] of Object.entries(defaults)) if (h[k] === undefined) { h[k] = v; changed = true; }
      if (changed) n++;
    }
  return n;
}
// Remove every hook running command, keeping the other hooks of its entry (nulls included); drop an
// entry only when every hook in it was one of these. Returns how many hooks it removed.
function removeCommand(settings, command) {
  let removed = 0;
  for (const ev of Object.keys(settings.hooks)) {
    const list = settings.hooks[ev];
    if (!Array.isArray(list)) continue;
    const kept = [];
    for (const e of list) {
      if (!e || !Array.isArray(e.hooks)) { kept.push(e); continue; }
      const rest = e.hooks.filter((h) => !(h && h.command === command));
      removed += e.hooks.length - rest.length;
      if (rest.length === e.hooks.length) kept.push(e);
      else if (rest.length) kept.push({ ...e, hooks: rest });
    }
    if (kept.length) settings.hooks[ev] = kept;
    else delete settings.hooks[ev];
  }
  return removed;
}
const H = (name) => ({ type: "command", command: `bash "$CLAUDE_PROJECT_DIR/hooks/brain/${name}"` });
const L = local.settings;
let added = 0;
if (ensureHookEntry(L, "PreCompact", null, H("brain-pre-compact.sh"))) added++;
if (ensureHookEntry(L, "SessionEnd", null, H("brain-session-end.sh"))) added++;
if (ensureHookEntry(L, "Stop", null, H("brain-session-end.sh"))) added++;
if (ensureHookEntry(L, "PostToolUse", "Write|Edit", H("brain-post-lint.sh"))) added++;
if (ensureHookEntry(L, "SessionStart", null, H("brain-load.sh"))) added++;
// The old fail-open registration of the guard (shell form, before P0-09) leaves the local file.
const removed = removeCommand(L, H("brain-security-guard.sh").command);
// The guard: exec form, so the project path is one argument with no shell quoting; 30 s, not the
// 600 s default, and "block", so a stall or a crash blocks the call instead of letting it through.
const GUARD = { type: "command", command: "bash", args: ["${CLAUDE_PROJECT_DIR}/hooks/brain/brain-security-guard.sh"] };
const GUARD_DEFAULTS = { timeout: 30, onFailure: "block" };
if (ensureHookEntry(shared.settings, "PreToolUse", "Write|Edit|NotebookEdit|Bash", { ...GUARD, ...GUARD_DEFAULTS })) added++;
added += ensureDefaults(shared.settings, "PreToolUse", GUARD, GUARD_DEFAULTS);
for (const f of [local, shared]) {
  const text = JSON.stringify(f.settings, null, 2) + "\n";
  if (text !== f.raw) fs.writeFileSync(f.file, text);
}
process.stdout.write(added + " " + removed);
' "${TARGET}")"
ADDED="${MERGED%% *}"
REMOVED="${MERGED##* }"
echo "✓ hook entries merged (${ADDED} added or updated)"
if [ "${REMOVED}" != "0" ]; then
  echo "✓ removed ${REMOVED} old fail-open guard registration$([ "${REMOVED}" = "1" ] || echo s) from ${TARGET}/.claude/settings.local.json"
fi

# 3. .gitignore — session logs are local-only by default
touch "${TARGET}/.gitignore"
grep -qxF '.project-brain/sessions/' "${TARGET}/.gitignore" \
  || echo '.project-brain/sessions/' >> "${TARGET}/.gitignore"
echo "✓ .gitignore covers .project-brain/sessions/"

# 4. Acceptance: structural verify (fails loudly on a bad install)
node "${REPO_DIR}/scripts/brain/brain-verify.js" --target "${BRAIN}"
