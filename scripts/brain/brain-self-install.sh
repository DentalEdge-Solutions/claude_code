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

# 2. Hook registration → .claude/settings.local.json (merge, never clobber —
#    same ensureHookEntry pattern as install.sh's telemetry step). A file it cannot
#    read stops the install here, unchanged (set -e).
mkdir -p "${TARGET}/.claude"
ADDED="$(node -e '
const fs = require("fs");
const file = process.argv[1] + "/.claude/settings.local.json";
// Never write a file this cannot read: it would replace the owner settings with ours (review N2,
// N3). Stop instead, so the guard hook is never silently missing. An empty file counts as {}.
function refuse(why) {
  process.stderr.write(`Error: ${file} was not changed: ${why}. Fix it, then re-run this installer.\n`);
  process.exit(3);
}
const plain = (v) => v !== null && typeof v === "object" && !Array.isArray(v);
const raw = fs.existsSync(file) ? fs.readFileSync(file, "utf8") : "";
let settings = {};
if (raw.trim()) { try { settings = JSON.parse(raw); } catch (e) { refuse(`it is not valid JSON (${e.message})`); } }
if (!plain(settings)) refuse("it is not a JSON object");
if (settings.hooks != null && !plain(settings.hooks)) refuse("its \"hooks\" is not an object");
for (const ev of ["PreCompact", "SessionEnd", "Stop", "PreToolUse", "PostToolUse", "SessionStart"])
  if (settings.hooks && settings.hooks[ev] != null && !Array.isArray(settings.hooks[ev])) refuse(`its "hooks.${ev}" is not a list`);
settings.hooks = settings.hooks || {};
function ensureHookEntry(eventName, matcher, command, timeout) {
  settings.hooks[eventName] = settings.hooks[eventName] || [];
  const list = settings.hooks[eventName];
  const already = list.some((entry) => entry &&
    (entry.matcher || null) === (matcher || null) &&
    Array.isArray(entry.hooks) && entry.hooks.some((h) => h && h.command === command));
  if (already) return false;
  list.push({ ...(matcher ? { matcher } : {}), hooks: [{ type: "command", command, ...(timeout !== undefined ? { timeout } : {}) }] });
  return true;
}
// Give every hook that runs command on eventName the timeout (seconds) if it has none, whatever
// its matcher: matching hooks run in parallel, so one untimed copy keeps the default. A timeout
// the owner already set is kept. Returns how many hooks it updated.
function ensureTimeout(eventName, command, timeout) {
  let n = 0;
  for (const entry of settings.hooks[eventName] || [])
    for (const h of Array.isArray(entry && entry.hooks) ? entry.hooks : [])
      if (h && h.command === command && h.timeout === undefined) { h.timeout = timeout; n++; }
  return n;
}
const H = (name) => `bash "$CLAUDE_PROJECT_DIR/hooks/brain/${name}"`;
let added = 0;
if (ensureHookEntry("PreCompact", null, H("brain-pre-compact.sh"))) added++;
if (ensureHookEntry("SessionEnd", null, H("brain-session-end.sh"))) added++;
if (ensureHookEntry("Stop", null, H("brain-session-end.sh"))) added++;
// 30 s, not the 600 s default: a PreToolUse hook that times out does not block the call, so a
// stalled guard would freeze every Write/Edit/Bash for 10 minutes and then let it through.
// A normal check takes well under 1 s, even on a 1 MB command under load (triage F1).
if (ensureHookEntry("PreToolUse", "Write|Edit|NotebookEdit|Bash", H("brain-security-guard.sh"), 30)) added++;
added += ensureTimeout("PreToolUse", H("brain-security-guard.sh"), 30);
if (ensureHookEntry("PostToolUse", "Write|Edit", H("brain-post-lint.sh"))) added++;
if (ensureHookEntry("SessionStart", null, H("brain-load.sh"))) added++;
fs.writeFileSync(file, JSON.stringify(settings, null, 2) + "\n");
process.stdout.write(String(added));
' "${TARGET}")"
echo "✓ hook entries merged (${ADDED} added or updated)"

# 3. .gitignore — session logs are local-only by default
touch "${TARGET}/.gitignore"
grep -qxF '.project-brain/sessions/' "${TARGET}/.gitignore" \
  || echo '.project-brain/sessions/' >> "${TARGET}/.gitignore"
echo "✓ .gitignore covers .project-brain/sessions/"

# 4. Acceptance: structural verify (fails loudly on a bad install)
node "${REPO_DIR}/scripts/brain/brain-verify.js" --target "${BRAIN}"
