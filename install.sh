#!/usr/bin/env bash
# Skill Builder — Install
# Copies all skills to a target project AND syncs to ~/.claude/skills/ runtime.
# Claude Code reads skills from ~/.claude/skills/ — both locations must be populated.
# Skills are discovered dynamically from the skills/ directory — no hardcoded list.
#
# Usage:
#   ./install.sh /path/to/target-project
#   ./install.sh .   (current directory)
#   ./install.sh --dry-run /path/to/target-project

set -euo pipefail

# ── Colours ──────────────────────────────────────────────────────────────────
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; RESET='\033[0m'
ok()      { echo -e "  ${GREEN}✓${RESET} $*"; }
warn()    { echo -e "  ${YELLOW}!${RESET} $*"; }
dryrun()  { echo -e "  ${CYAN}~${RESET} [dry-run] $*"; }

# ── Args ─────────────────────────────────────────────────────────────────────
DRY_RUN=false
WITH_BRAIN=false
BRAIN_MODE="standard"
ARGS=()
while [ $# -gt 0 ]; do
    case "$1" in
        --dry-run)           DRY_RUN=true ;;
        --with-second-brain) WITH_BRAIN=true ;;
        --brain-mode)        BRAIN_MODE="${2:-}"; shift ;;
        *)                   ARGS+=("$1") ;;
    esac
    shift
done
case "${BRAIN_MODE}" in
    lightweight|standard|enhanced-with-gbrain|enhanced-with-graphify|lab-multimodal) ;;
    *) echo "Unknown --brain-mode: ${BRAIN_MODE}"; exit 1 ;;
esac

TARGET="${ARGS[0]:-}"
if [ -z "${TARGET}" ]; then
    echo "Usage: ./install.sh [--dry-run] /path/to/target-project"
    exit 1
fi
TARGET="$(cd "${TARGET}" && pwd)"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GLOBAL_SKILLS="${HOME}/.claude/skills"

echo "════════════════════════════════════════════"
echo "║   Skill Builder — Install                ║"
echo "════════════════════════════════════════════"
echo "  Project : ${TARGET}"
echo "  Runtime : ${GLOBAL_SKILLS}"
${DRY_RUN} && echo -e "  ${CYAN}Mode    : DRY RUN — no files will be written${RESET}"
echo ""

# ── Check Node.js ────────────────────────────────────────────────────────────
if command -v node &>/dev/null; then
    ok "Node.js $(node --version) found"
else
    warn "Node.js not found — scripts (static-scan.js, generate-seed-evals.js, etc.) will not run"
    warn "Install from https://nodejs.org/ before using skill-audit or skill-eval"
fi
echo ""

# ── Existing installation check ──────────────────────────────────────────────
if [ -d "${TARGET}/skills" ] && ! ${DRY_RUN}; then
    EXISTING="$(ls "${TARGET}/skills" 2>/dev/null | tr '\n' ' ')"
    warn "Existing skills/ found in target: ${EXISTING}"
    read -r -p "  Overwrite? [y/N] " confirm
    [[ "${confirm}" =~ ^[Yy]$ ]] || { echo "Aborted."; exit 0; }
    echo ""
fi

# ── Discover skills dynamically ──────────────────────────────────────────────
SKILL_NAMES=()
while IFS= read -r dir; do
    SKILL_NAMES+=("$(basename "${dir}")")
done < <(find "${REPO_DIR}/skills" -mindepth 1 -maxdepth 1 -type d | sort)

# ── 1. Project-scoped skills (source of truth) ───────────────────────────────
echo "→ [1/8] Copying skills to project"
if ! ${DRY_RUN}; then mkdir -p "${TARGET}/skills" && cp -R "${REPO_DIR}/skills/." "${TARGET}/skills/"; fi
for skill in "${SKILL_NAMES[@]}"; do
    ${DRY_RUN} && dryrun "${skill}  →  ${TARGET}/skills/${skill}" || ok "${skill}  →  ${TARGET}/skills/${skill}"
done
echo ""

# ── 2. Runtime sync (~/.claude/skills/) ─────────────────────────────────────
echo "→ [2/8] Syncing skills to runtime"
if ! ${DRY_RUN}; then mkdir -p "${GLOBAL_SKILLS}"; fi
for skill in "${SKILL_NAMES[@]}"; do
    if ! ${DRY_RUN}; then cp -R "${REPO_DIR}/skills/${skill}" "${GLOBAL_SKILLS}/"; fi
    ${DRY_RUN} && dryrun "${skill}  →  ${GLOBAL_SKILLS}/${skill}" || ok "${skill}  →  ${GLOBAL_SKILLS}/${skill}"
done
echo ""

# ── 3. Agents (project-scoped only) ─────────────────────────────────────────
echo "→ [3/8] Installing agents"
if ! ${DRY_RUN}; then mkdir -p "${TARGET}/.claude/agents"; fi
for agent_file in "${REPO_DIR}/.claude/agents/"*.md; do
    agent_name="$(basename "${agent_file}")"
    if ! ${DRY_RUN}; then cp "${agent_file}" "${TARGET}/.claude/agents/${agent_name}"; fi
    ${DRY_RUN} && dryrun "project  →  ${TARGET}/.claude/agents/${agent_name}" || ok "project  →  ${TARGET}/.claude/agents/${agent_name}"
done
echo ""

# ── 4. Codex eval scripts + schemas ─────────────────────────────────────────
echo "→ [4/8] Installing Codex external eval scripts and schemas"
if ! ${DRY_RUN}; then
    mkdir -p "${TARGET}/scripts/codex" "${TARGET}/schemas/codex"
    cp -R "${REPO_DIR}/scripts/codex/." "${TARGET}/scripts/codex/"
    cp -R "${REPO_DIR}/schemas/codex/." "${TARGET}/schemas/codex/"
fi
for f in "${REPO_DIR}/scripts/codex/"*.js; do
    ${DRY_RUN} && dryrun "$(basename "${f}")  →  ${TARGET}/scripts/codex/$(basename "${f}")" \
               || ok "$(basename "${f}")  →  ${TARGET}/scripts/codex/$(basename "${f}")"
done
for f in "${REPO_DIR}/schemas/codex/"*.json; do
    ${DRY_RUN} && dryrun "$(basename "${f}")  →  ${TARGET}/schemas/codex/$(basename "${f}")" \
               || ok "$(basename "${f}")  →  ${TARGET}/schemas/codex/$(basename "${f}")"
done
echo ""

# ── 5. Evals workspace + .gitignore ─────────────────────────────────────────
echo "→ [5/8] Setting up evals/ workspace and .gitignore"
if ! ${DRY_RUN}; then
    mkdir -p "${TARGET}/evals"
    ok "created  ${TARGET}/evals/"
else
    dryrun "would create  ${TARGET}/evals/"
fi

# Entries to ignore: generated artifacts that should not be committed
IGNORE_ENTRIES=(
    "# skill-builder generated artifacts"
    "evals/"
    "skills/*-backup-*/"
    "skills/*-eval-snapshot/"
)

GITIGNORE="${TARGET}/.gitignore"
ADDED=()
if ! ${DRY_RUN}; then
    touch "${GITIGNORE}"
    for entry in "${IGNORE_ENTRIES[@]}"; do
        if ! grep -qF "${entry}" "${GITIGNORE}" 2>/dev/null; then
            printf '%s\n' "${entry}" >> "${GITIGNORE}"
            [[ "${entry}" != "#"* ]] && ADDED+=("${entry}")
        fi
    done
    if [ ${#ADDED[@]} -gt 0 ]; then
        ok "added to .gitignore: ${ADDED[*]}"
    else
        ok ".gitignore already up to date"
    fi
else
    dryrun "would update ${GITIGNORE} with skill-builder entries"
fi
echo ""

# ── 6. CLAUDE.md pipeline section ────────────────────────────────────────────
echo "→ [6/8] Writing pipeline rules to CLAUDE.md"
CLAUDE_MD="${TARGET}/CLAUDE.md"
MARKER_START="# >>> skill-builder >>>"

if grep -qF "${MARKER_START}" "${CLAUDE_MD}" 2>/dev/null; then
    ${DRY_RUN} && dryrun "CLAUDE.md pipeline section already present — skipping" || ok "CLAUDE.md pipeline section already present"
else
    if ! ${DRY_RUN}; then
        touch "${CLAUDE_MD}"
        [ -s "${CLAUDE_MD}" ] && echo "" >> "${CLAUDE_MD}"
        cat >> "${CLAUDE_MD}" << 'PIPELINE_SECTION'
# >>> skill-builder >>>
## Skill & Agent Development

This project uses the Skill Builder pipeline. Skills live in `skills/`. Agents live in `.claude/agents/`.

### Always

- Run `skill-needs-analysis-agent` before building anything new — maps the project stack and workflow terms to missing skill categories
- Use `skill-scout` to find existing candidates before writing any skill from scratch
- Run `skill-audit` on every sourced skill before installing — never skip the security gate
- Run `skill-adapt` to make a sourced skill project-native before use
- Run `skill-eval` after every adaptation — ship only skills clearing all 5 metric thresholds: pass rate ≥ 80%, trigger accuracy ≥ 85%, resilience ≥ 8/10, project fit ≥ 7/10
- Run `skill-refine` if any metric is below threshold — up to 10 iterations before escalating
- Run `agent-eval` after every agent-adapt — same 5 thresholds; Dispatch Accuracy replaces Trigger Accuracy
- Run `agent-refine` if any agent metric is below threshold — Lever E changes trigger agent-audit re-run automatically

### Never

- Write a skill or agent from scratch without first running `skill-scout`
- Install an external skill with a FLAG or BLOCK verdict from `skill-audit`
- Skip `skill-eval` after adapting a skill

### Pipeline

```
skill-scout → skill-audit → skill-adapt → skill-eval → skill-refine
agent-scout → agent-audit → agent-adapt → agent-eval → agent-refine
```

Periodic health check: `skill-guardian` — audits all skills, measures 5 metrics, refines any below-threshold skills.
# <<< skill-builder <<<
PIPELINE_SECTION
        ok "added pipeline section to ${CLAUDE_MD}"
    else
        dryrun "would add pipeline section to ${CLAUDE_MD}"
    fi
fi
echo ""

# ── 7. Telemetry (Level 4 real-usage hooks) ─────────────────────────────────
echo "→ [7/8] Installing telemetry hooks"
if ! ${DRY_RUN}; then
    mkdir -p "${TARGET}/scripts/telemetry" "${TARGET}/schemas/telemetry"
    cp -R "${REPO_DIR}/scripts/telemetry/." "${TARGET}/scripts/telemetry/"
    cp -R "${REPO_DIR}/schemas/telemetry/." "${TARGET}/schemas/telemetry/"
fi
for f in "${REPO_DIR}/scripts/telemetry/"*.js; do
    ${DRY_RUN} && dryrun "$(basename "${f}")  →  ${TARGET}/scripts/telemetry/$(basename "${f}")" \
               || ok "$(basename "${f}")  →  ${TARGET}/scripts/telemetry/$(basename "${f}")"
done
for f in "${REPO_DIR}/schemas/telemetry/"*.json; do
    ${DRY_RUN} && dryrun "$(basename "${f}")  →  ${TARGET}/schemas/telemetry/$(basename "${f}")" \
               || ok "$(basename "${f}")  →  ${TARGET}/schemas/telemetry/$(basename "${f}")"
done

# Merge (never clobber) telemetry hook entries into the target's .claude/settings.json.
# Surgical: only appends our own matcher/command combos if they aren't already present;
# every other hook the target project already has is left untouched.
if ! ${DRY_RUN}; then
    if command -v node &>/dev/null; then
        TELEMETRY_HOOKS_ADDED="$(node -e '
const fs = require("fs");
const path = require("path");
const target = process.argv[1];
const file = path.join(target, ".claude", "settings.json");
fs.mkdirSync(path.dirname(file), { recursive: true });
let settings = {};
if (fs.existsSync(file)) {
    try { settings = JSON.parse(fs.readFileSync(file, "utf8")); } catch { settings = {}; }
}
settings.hooks = settings.hooks || {};

function ensureHookEntry(eventName, matcher, command) {
    settings.hooks[eventName] = settings.hooks[eventName] || [];
    const list = settings.hooks[eventName];
    const already = list.some((entry) =>
        (entry.matcher || null) === (matcher || null) &&
        Array.isArray(entry.hooks) &&
        entry.hooks.some((h) => h && h.command === command)
    );
    if (already) return false;
    list.push({ ...(matcher ? { matcher } : {}), hooks: [{ type: "command", command }] });
    return true;
}

const invCmd = "node \"$CLAUDE_PROJECT_DIR/scripts/telemetry/log-invocation.js\"";
const corrCmd = "node \"$CLAUDE_PROJECT_DIR/scripts/telemetry/log-outcome.js\" --mode correction";
const endCmd = "node \"$CLAUDE_PROJECT_DIR/scripts/telemetry/log-outcome.js\" --mode session-end";

let added = 0;
if (ensureHookEntry("PostToolUse", "Skill|Task", invCmd)) added++;
if (ensureHookEntry("UserPromptSubmit", null, corrCmd)) added++;
if (ensureHookEntry("Stop", null, endCmd)) added++;
if (ensureHookEntry("SessionEnd", null, endCmd)) added++;

fs.writeFileSync(file, JSON.stringify(settings, null, 2) + "\n");
process.stdout.write(String(added));
' "${TARGET}")"
        if [ "${TELEMETRY_HOOKS_ADDED}" != "0" ]; then
            ok "merged ${TELEMETRY_HOOKS_ADDED} telemetry hook entr$([ "${TELEMETRY_HOOKS_ADDED}" = "1" ] && echo y || echo ies) into ${TARGET}/.claude/settings.json"
        else
            ok "telemetry hook entries already present in ${TARGET}/.claude/settings.json"
        fi
    else
        warn "Node.js not found — skipping .claude/settings.json hook merge for telemetry"
    fi
else
    dryrun "would merge telemetry hook entries into ${TARGET}/.claude/settings.json"
fi
echo ""

# ── 8. Second Brain (opt-in) ────────────────────────────────────────────────
if ${WITH_BRAIN}; then
    echo "→ [8/8] Installing second brain (mode: ${BRAIN_MODE})"
    BRAIN="${TARGET}/.project-brain"
    if ! ${DRY_RUN}; then
        # 8a. Hooks + scripts to target (targets need them for their own sessions)
        mkdir -p "${TARGET}/hooks/brain" "${TARGET}/scripts/brain" "${TARGET}/schemas/brain" "${TARGET}/templates/second-brain"
        cp -R "${REPO_DIR}/hooks/brain/." "${TARGET}/hooks/brain/"
        cp -R "${REPO_DIR}/scripts/brain/." "${TARGET}/scripts/brain/"
        cp -R "${REPO_DIR}/schemas/brain/." "${TARGET}/schemas/brain/"
        cp -R "${REPO_DIR}/templates/second-brain/." "${TARGET}/templates/second-brain/"
        # 8b. Capsule + hook merge + .gitignore + verify — the proven Phase 2 installer
        bash "${TARGET}/scripts/brain/brain-self-install.sh" "${TARGET}"
        # 8c. Set the chosen brain mode in the installed profile
        node -e '
const fs = require("fs");
const pf = process.argv[1] + "/.project-brain/context/brain-profile.json";
const p = JSON.parse(fs.readFileSync(pf, "utf8"));
p.brain_mode = process.argv[2];
fs.writeFileSync(pf, JSON.stringify(p, null, 2) + "\n");
' "${TARGET}" "${BRAIN_MODE}"
        # 8d. CLAUDE.md marker — @import keeps the protocol inside the brain
        CLAUDE_MD="${TARGET}/CLAUDE.md"
        touch "${CLAUDE_MD}"
        if ! grep -qF "# >>> second-brain >>>" "${CLAUDE_MD}"; then
            cat >> "${CLAUDE_MD}" <<'BRAIN_MARKER'

# >>> second-brain >>>
## Second Brain
@.project-brain/BRAIN.md
# <<< second-brain <<<
BRAIN_MARKER
            ok "second-brain section appended to CLAUDE.md"
        else
            ok "second-brain section already present in CLAUDE.md"
        fi
        ok "second brain installed (mode: ${BRAIN_MODE}) — verify passed"
    else
        dryrun "would copy hooks/brain, scripts/brain, schemas/brain, templates/second-brain"
        dryrun "would create ${BRAIN} + merge 6 hook entries + append CLAUDE.md marker"
        dryrun "would set brain_mode=${BRAIN_MODE} in brain-profile.json"
    fi
    echo ""
fi

# ── 4b. Refresh project-context.json if stale ────────────────────────────────
# A pre-existing project-context.json may be missing the hooks/mcp_servers/plugins
# fields added in the June 2026 expansion. Detect and offer to regenerate.
CTX="${TARGET}/evals/project-context.json"
if ! ${DRY_RUN} && [ -f "${CTX}" ] && command -v node &>/dev/null; then
    # Check for the presence of the "hooks" field (added in expansion)
    if ! node -e "const d=require('${CTX}'); process.exit(d.hooks !== undefined ? 0 : 1)" 2>/dev/null; then
        warn "project-context.json is missing the hooks/mcp_servers/plugins fields (pre-expansion format)"
        read -r -p "  Regenerate it now? [Y/n] " confirm_ctx
        if [[ ! "${confirm_ctx}" =~ ^[Nn]$ ]]; then
            (cd "${TARGET}" && node "${TARGET}/skills/skill-eval/scripts/extract-project-context.js" 2>/dev/null)
            ok "regenerated ${CTX}"
        else
            warn "Skipped — run '/project-setup' or 'node skills/skill-eval/scripts/extract-project-context.js' to refresh"
        fi
    else
        ok "project-context.json is current (hooks field present)"
    fi
fi
echo ""

# ── Done ─────────────────────────────────────────────────────────────────────
echo "════════════════════════════════════════════"
echo ""
if ${DRY_RUN}; then
    echo -e "  ${CYAN}~ Dry run complete — no files were written.${RESET}"
    echo -e "  ${CYAN}  Run without --dry-run to apply.${RESET}"
else
    echo -e "  ${GREEN}✓ Install complete.${RESET}"
fi
echo ""
echo "  Skills are live in Claude Code."
echo ""
echo "  Pipeline:"
echo "    project-setup  → configure CLAUDE.md and project context  ← start here"
echo "    project-audit  → scan .claude/ for secrets, permissions, hook risks"
echo "    skill-scout    → find an existing skill on GitHub"
echo "    skill-audit    → security-gate the sourced skill before install"
echo "    skill-adapt    → adapt it to this project"
echo "    skill-eval     → measure its effectiveness"
echo "    skill-refine   → auto-improve until targets are met"
echo ""
echo "  Optional: when no skill is found, skill-scout and skill-refine recommend building one with"
echo "  superpowers:writing-skills if the Superpowers plugin is installed, and by hand otherwise —"
echo "  either way through skill-audit → skill-eval. This installer does not install plugins."
echo ""
echo "  Start with: '/project-setup' to configure your project context"
echo "           or 'find a skill for <capability>' if already configured"
echo ""
