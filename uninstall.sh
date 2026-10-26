#!/usr/bin/env bash
# Skill Builder — Uninstall
# Mirrors install.sh: removes all discovered skills from project AND ~/.claude/ runtime.
# Skills and agents are discovered dynamically from the repo — no hardcoded list.
#
# Usage:
#   ./uninstall.sh /path/to/target-project
#   ./uninstall.sh .   (current directory)

set -euo pipefail
# An exported CDPATH makes "cd" print the directory, which corrupts "$(cd … && pwd)".
unset CDPATH

# ── Colours ──────────────────────────────────────────────────────────────────
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RESET='\033[0m'
ok()   { echo -e "  ${GREEN}✓${RESET} $*"; }
skip() { echo -e "  ${YELLOW}–${RESET} $*"; }
warn() { echo -e "  ${YELLOW}!${RESET} $*"; }

# ── Args ─────────────────────────────────────────────────────────────────────
TARGET="${1:-}"
if [ -z "${TARGET}" ]; then
    echo "Usage: ./uninstall.sh /path/to/target-project"
    exit 1
fi
TARGET="$(cd "${TARGET}" && pwd)"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GLOBAL_SKILLS="${HOME}/.claude/skills"

# Every removal below is "${TARGET}/<dir>", so refuse a target where that would hit the
# filesystem root, the home directory, ~/.claude (its skills/ holds every runtime skill) or
# this toolkit itself (P9). -ef compares device and inode, so a symlink or a "//" spelling
# of one of them is refused too.
for forbidden in / "${HOME}" "${HOME}/.claude" "${REPO_DIR}"; do
    if [ "${TARGET}" -ef "${forbidden}" ]; then
        echo "Refusing to uninstall from ${TARGET}: it is the filesystem root, the home directory, ~/.claude or this toolkit itself." >&2
        exit 1
    fi
done
# install.sh never copies this script, so a target that has it is another toolkit clone, where
# the removals would hit its sources and any uncommitted work in them.
if [ -f "${TARGET}/uninstall.sh" ] && grep -qF "# Skill Builder — Uninstall" "${TARGET}/uninstall.sh"; then
    echo "Refusing to uninstall from ${TARGET}: it is a clone of this toolkit, not an installed project." >&2
    exit 1
fi

# ── Discover skills + agents from repo (same source as install.sh) ───────────
SKILL_NAMES=()
while IFS= read -r dir; do
    SKILL_NAMES+=("$(basename "${dir}")")
done < <(find "${REPO_DIR}/skills" -mindepth 1 -maxdepth 1 -type d | sort)

AGENT_FILES=()
while IFS= read -r f; do
    AGENT_FILES+=("$(basename "${f}")")
done < <(find "${REPO_DIR}/.claude/agents" -name "*.md" | sort)

echo "════════════════════════════════════════════"
echo "║   Skill Builder — Uninstall              ║"
echo "════════════════════════════════════════════"
echo "  Project : ${TARGET}"
echo "  Runtime : ${GLOBAL_SKILLS}"
echo ""
echo "  Will remove:"
echo "    • ${TARGET}/skills/  (${#SKILL_NAMES[@]} skills: ${SKILL_NAMES[*]})"
echo "    • ${GLOBAL_SKILLS}/<each skill above>"
echo "    • ${TARGET}/.claude/agents/  (${#AGENT_FILES[@]} agents: ${AGENT_FILES[*]})"
echo ""

read -r -p "Proceed? [y/N] " confirm
[[ "${confirm}" =~ ^[Yy]$ ]] || { echo "Aborted."; exit 0; }
echo ""

# ── 1. Project skills ────────────────────────────────────────────────────────
echo "→ [1/7] Removing project skills"
if [ -d "${TARGET}/skills" ]; then
    rm -rf "${TARGET}/skills"
    ok "removed  ${TARGET}/skills/"
else
    skip "skills/ not found in project"
fi
echo ""

# ── 2. Runtime skills (~/.claude/skills/) ───────────────────────────────────
echo "→ [2/7] Removing runtime skills"
for skill in "${SKILL_NAMES[@]}"; do
    runtime_skill="${GLOBAL_SKILLS}/${skill}"
    if [ -d "${runtime_skill}" ]; then
        rm -rf "${runtime_skill}"
        ok "removed  ${runtime_skill}"
    else
        skip "${skill} not found in runtime"
    fi
done
echo ""

# ── 3. Agents (project-scoped only) ─────────────────────────────────────────
echo "→ [3/7] Removing agents"
for agent_file in "${AGENT_FILES[@]}"; do
    project_agent="${TARGET}/.claude/agents/${agent_file}"
    if [ -f "${project_agent}" ]; then
        rm -f "${project_agent}"
        ok "removed  ${project_agent}"
    else
        skip "${agent_file} not found in project"
    fi
done
echo ""

# ── 4. Codex eval scripts + schemas ─────────────────────────────────────────
echo "→ [4/7] Removing Codex external eval scripts and schemas"
for d in scripts/codex schemas/codex; do
    target_dir="${TARGET}/${d}"
    if [ -d "${target_dir}" ]; then
        rm -rf "${target_dir}"
        ok "removed  ${target_dir}"
    else
        skip "${d} not found in project"
    fi
done
echo ""

# ── 5. CLAUDE.md pipeline section ────────────────────────────────────────────
echo "→ [5/7] Removing pipeline section from CLAUDE.md"
CLAUDE_MD="${TARGET}/CLAUDE.md"
if [ -f "${CLAUDE_MD}" ] && grep -qF "# >>> skill-builder >>>" "${CLAUDE_MD}" 2>/dev/null; then
    # awk, not "sed -i ''": that form is BSD-only and fails with GNU sed (P6). Written back
    # with cat, not mv, so a symlinked CLAUDE.md stays a link and the file keeps its mode.
    if awk '/^# >>> skill-builder >>>/{skip=1} !skip{print} /^# <<< skill-builder <<</{skip=0}' \
        "${CLAUDE_MD}" > "${CLAUDE_MD}.tmp" && cat "${CLAUDE_MD}.tmp" > "${CLAUDE_MD}"; then
        ok "removed pipeline section from CLAUDE.md"
    else
        warn "could not rewrite CLAUDE.md; remove the skill-builder section by hand"
    fi
    rm -f "${CLAUDE_MD}.tmp"
else
    skip "CLAUDE.md pipeline section not found"
fi
echo ""

echo "→ [6/7] Evals workspace"
if [ -d "${TARGET}/evals" ]; then
    echo "  evals/ contains generated data: scenario runs, timing, project-context.json, and refine/adapt safety copies (baselines, backups)."
    read -r -p "  Remove evals/ too? [y/N] " confirm_evals
    if [[ "${confirm_evals}" =~ ^[Yy]$ ]]; then
        rm -rf "${TARGET}/evals"
        ok "removed  ${TARGET}/evals/"
    else
        skip "evals/ kept"
    fi
else
    skip "evals/ not found"
fi
echo ""

# ── 7. Telemetry (Level 4 real-usage hooks) ─────────────────────────────────
echo "→ [7/7] Removing telemetry hooks"
for d in scripts/telemetry schemas/telemetry; do
    target_dir="${TARGET}/${d}"
    if [ -d "${target_dir}" ]; then
        rm -rf "${target_dir}"
        ok "removed  ${target_dir}"
    else
        skip "${d} not found in project"
    fi
done

# Surgical un-merge: remove ONLY the exact matcher/command entries install.sh
# added to .claude/settings.json. Any other hooks (or other settings keys) the
# target project already had are left untouched. Never deletes the file itself.
SETTINGS_FILE="${TARGET}/.claude/settings.json"
if [ -f "${SETTINGS_FILE}" ] && command -v node &>/dev/null; then
    if TELEMETRY_HOOKS_REMOVED="$(node -e '
const fs = require("fs");
const file = process.argv[1];
// A file this cannot read is left as it is: exit non-zero and the shell warns (review N2, N3).
function refuse(why) { process.stderr.write(`Error: ${file}: ${why}.\n`); process.exit(3); }
const plain = (v) => v !== null && typeof v === "object" && !Array.isArray(v);
const raw = fs.readFileSync(file, "utf8");
if (raw.charCodeAt(0) === 0xFEFF) refuse("it starts with a byte-order mark; save it as UTF-8 without one");   // review P6
if (!raw.trim()) { process.stdout.write("0"); process.exit(0); }
let settings;
try { settings = JSON.parse(raw); } catch (e) { refuse(`it is not valid JSON (${e.message})`); }
if (!plain(settings)) refuse("it is not a JSON object");
if (settings.hooks == null) { process.stdout.write("0"); process.exit(0); }
if (!plain(settings.hooks)) refuse("its \"hooks\" is not an object");

const invCmd = "node \"$CLAUDE_PROJECT_DIR/scripts/telemetry/log-invocation.js\"";
const corrCmd = "node \"$CLAUDE_PROJECT_DIR/scripts/telemetry/log-outcome.js\" --mode correction";
const endCmd = "node \"$CLAUDE_PROJECT_DIR/scripts/telemetry/log-outcome.js\" --mode session-end";
const ours = new Set([invCmd, corrCmd, endCmd]);

// Remove our hooks one by one, keeping the owner hooks that share an entry with them; drop an
// entry only when every hook in it was ours (review N8). Anything malformed is kept as found.
let removed = 0;
for (const eventName of Object.keys(settings.hooks)) {
    const list = settings.hooks[eventName];
    if (!Array.isArray(list)) continue;
    const kept = [];
    for (const entry of list) {
        if (!entry || !Array.isArray(entry.hooks)) { kept.push(entry); continue; }
        const rest = entry.hooks.filter((h) => !(h && ours.has(h.command)));
        removed += entry.hooks.length - rest.length;
        if (rest.length === entry.hooks.length) kept.push(entry);
        else if (rest.length) kept.push({ ...entry, hooks: rest });
    }
    if (kept.length) settings.hooks[eventName] = kept;
    else delete settings.hooks[eventName];
}

if (removed) fs.writeFileSync(file, JSON.stringify(settings, null, 2) + "\n");
process.stdout.write(String(removed));
' "${SETTINGS_FILE}")"; then
        if [ "${TELEMETRY_HOOKS_REMOVED}" != "0" ]; then
            ok "removed ${TELEMETRY_HOOKS_REMOVED} telemetry hook$([ "${TELEMETRY_HOOKS_REMOVED}" = "1" ] || echo s) from ${SETTINGS_FILE}"
        else
            skip "no telemetry hook entries found in ${SETTINGS_FILE}"
        fi
    else
        warn "telemetry hooks not removed: ${SETTINGS_FILE} was left unchanged (see the error above); remove them by hand"
    fi
else
    skip "${SETTINGS_FILE} not found"
fi
echo ""

# ── Second Brain removal (mirrors install step 8) ───────────────────────────
if [ -d "${TARGET}/hooks/brain" ] || [ -d "${TARGET}/scripts/brain" ]; then
    # Registrations first. The security guard is registered in the shared settings.json with
    # "onFailure": "block" (P0-09), so a registration that names a deleted script would block every
    # Write, Edit and Bash call: hooks/brain/ goes only once that registration is gone. The other
    # brain hooks are in settings.local.json. Match by "hooks/brain/" in the command or an argument;
    # leave everything else. A file this cannot read is left as it is: exit non-zero and warn
    # (review N2, N3).
    BRAIN_UNMERGE_JS='
const fs = require("fs");
const file = process.argv[1];
function refuse(why) { process.stderr.write(`Error: ${file}: ${why}.\n`); process.exit(3); }
const plain = (v) => v !== null && typeof v === "object" && !Array.isArray(v);
const raw = fs.readFileSync(file, "utf8");
if (raw.charCodeAt(0) === 0xFEFF) refuse("it starts with a byte-order mark; save it as UTF-8 without one");   // review P6
if (!raw.trim()) { process.stdout.write("0"); process.exit(0); }
let s;
try { s = JSON.parse(raw); } catch (e) { refuse(`it is not valid JSON (${e.message})`); }
if (!plain(s)) refuse("it is not a JSON object");
if (s.hooks == null) { process.stdout.write("0"); process.exit(0); }
if (!plain(s.hooks)) refuse("its \"hooks\" is not an object");
const ours = (h) => h && [h.command, ...(Array.isArray(h.args) ? h.args : [])].some((x) => /hooks\/brain\//.test(String(x || "")));
// Remove our hooks one by one, keeping the owner hooks that share an entry with them; drop an
// entry only when every hook in it was ours (review N10). Anything malformed is kept as found.
let removed = 0;
for (const ev of Object.keys(s.hooks)) {
  if (!Array.isArray(s.hooks[ev])) continue;
  const kept = [];
  for (const e of s.hooks[ev]) {
    if (!e || !Array.isArray(e.hooks)) { kept.push(e); continue; }
    const rest = e.hooks.filter((h) => !ours(h));
    removed += e.hooks.length - rest.length;
    if (rest.length === e.hooks.length) kept.push(e);
    else if (rest.length) kept.push({ ...e, hooks: rest });
  }
  if (kept.length) s.hooks[ev] = kept;
  else delete s.hooks[ev];
}
if (removed) fs.writeFileSync(file, JSON.stringify(s, null, 2) + "\n");
process.stdout.write(String(removed));
'
    # unmerge <file>: prints the outcome; returns 1 when the file could not be read or changed.
    unmerge_brain_hooks() {
        local file="$1" n
        if n="$(node -e "${BRAIN_UNMERGE_JS}" "${file}")"; then
            if [ "${n}" != "0" ]; then
                ok "removed ${n} brain hook$([ "${n}" = "1" ] || echo s) from ${file}"
            else
                skip "no brain hook entries found in ${file}"
            fi
            return 0
        fi
        warn "brain hooks not removed: ${file} was left unchanged (see the error above); remove them by hand"
        return 1
    }
    GUARD_REGISTRATION_GONE=true
    SHARED_SETTINGS="${TARGET}/.claude/settings.json"
    if [ -f "${SHARED_SETTINGS}" ]; then
        if ! command -v node &>/dev/null || ! unmerge_brain_hooks "${SHARED_SETTINGS}"; then
            GUARD_REGISTRATION_GONE=false
        fi
    fi
    SETTINGS="${TARGET}/.claude/settings.local.json"
    if [ -f "${SETTINGS}" ] && command -v node &>/dev/null; then
        unmerge_brain_hooks "${SETTINGS}" || true
    fi
    rm -rf "${TARGET}/scripts/brain" "${TARGET}/schemas/brain" "${TARGET}/templates/second-brain"
    if ${GUARD_REGISTRATION_GONE}; then
        rm -rf "${TARGET}/hooks/brain"
        ok "removed brain hooks, scripts, schemas, templates"
    else
        ok "removed brain scripts, schemas, templates"
        warn "kept ${TARGET}/hooks/brain/: the guard may still be registered in ${SHARED_SETTINGS} with onFailure \"block\", and a registration naming a deleted script blocks every Write, Edit and Bash call. Remove the brain-security-guard hook from that file by hand, then delete hooks/brain/."
    fi
    # Remove CLAUDE.md marker section (keep everything outside the markers)
    CLAUDE_MD="${TARGET}/CLAUDE.md"
    if [ -f "${CLAUDE_MD}" ] && grep -qF "# >>> second-brain >>>" "${CLAUDE_MD}"; then
        awk '/# >>> second-brain >>>/{skip=1} !skip{print} /# <<< second-brain <<</{skip=0}' \
            "${CLAUDE_MD}" > "${CLAUDE_MD}.tmp" && mv "${CLAUDE_MD}.tmp" "${CLAUDE_MD}"
        ok "second-brain section removed from CLAUDE.md"
    fi
    if [ -d "${TARGET}/.project-brain" ]; then
        warn ".project-brain/ PRESERVED — it is your project's memory, not tooling."
        warn "Delete manually only if you are certain: rm -rf ${TARGET}/.project-brain"
    fi
fi
echo ""

# ── Done ─────────────────────────────────────────────────────────────────────
echo "════════════════════════════════════════════"
echo ""
echo -e "  ${GREEN}✓ Uninstall complete.${RESET}"
echo ""
echo "  Note: .gitignore entries added during install were not removed."
echo ""
