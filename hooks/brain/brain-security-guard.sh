#!/usr/bin/env bash
# hooks/brain/brain-security-guard.sh — PreToolUse guard. The ONLY blocking brain
# hook. Denies: direct Write/Edit/NotebookEdit into .project-brain/canon/; Bash
# mutations of canon/ not going through brain-promote --approve; deleting the
# capsule (rm/rmdir/unlink/shred/git rm/git clean as the command, find -delete or
# -exec rm, also after a cd into the capsule).
# Failure policy (owner decision P11, 2026-10-15):
#   - bad input (empty, not JSON, not an object with tool_name/tool_input) fails
#     CLOSED: deny with a reason. Claude Code always sends valid input.
#   - node missing or crashing fails OPEN but VISIBLY: stderr warning, a log line in
#     .project-brain/reports/guard-failures.log, exit 1 (a non-blocking hook error
#     the user sees). Denying there would block every Write/Edit/Bash, the fix included.
# Denial is expressed via permissionDecision with exit 0. Every pattern is linear-time:
# a hook that times out lets the tool call through.
# Defense-in-depth only: brain-promote --approve + git history are the real
# canon boundary; this guard raises the cost of accidental/careless mutation.
set -u
ROOT="${CLAUDE_PROJECT_DIR:-$PWD}"
# The hook input reaches node on stdin, never through an environment variable: a large
# input (a big Write) would exceed the exec size limit and make the guard fail open.
DECISION="$(node -e '
const fs = require("fs");
const path = require("path");
const deny = (reason) => {
  console.log(JSON.stringify({ hookSpecificOutput: {
    hookEventName: "PreToolUse", permissionDecision: "deny", permissionDecisionReason: reason } }));
  process.exit(0);
};
const isObj = (v) => v !== null && typeof v === "object" && !Array.isArray(v);
const malformed = (what) => deny("brain-security-guard: malformed hook input (" + what + ") — denied, the guard fails closed on bad input. Claude Code always sends a JSON object with tool_name and tool_input, so this points at a broken hook setup.");
let raw;
try { raw = fs.readFileSync(0, "utf8"); } catch { deny("brain-security-guard: unreadable hook input — denied, the guard fails closed on bad input."); }
let j;
try { j = JSON.parse(raw); } catch { malformed(raw.trim() ? "not JSON" : "empty"); }
if (!isObj(j)) malformed("not a JSON object");
if (typeof j.tool_name !== "string" || !j.tool_name) malformed("no tool_name");
if (!isObj(j.tool_input)) malformed("tool_input is not an object");
const tool = j.tool_name;
const inp = j.tool_input;

if (["Write", "Edit", "NotebookEdit"].includes(tool)) {
  const target = tool === "NotebookEdit" ? inp.notebook_path : inp.file_path;
  if (typeof target !== "string") malformed(tool + " without a string path");
  // Normalize first — "…/.project-brain/decisions/../canon/x.md" must not slip past.
  const fp = path.resolve(target);
  if (/\/\.project-brain\/canon(\/|$)/.test(fp))
    deny("Direct writes to .project-brain/canon/ are forbidden. Promote a reviewed candidate instead: node scripts/brain/brain-promote.js <candidate> --approve --to canon");
}

if (tool === "Bash") {
  if (typeof inp.command !== "string") malformed("Bash command is not a string");
  const cmd = inp.command;
  const CAPSULE = /\.project-brain/;

  // ── canon mutations ────────────────────────────────────────────────────────
  // Direct reference, or split reference (e.g. "cd .project-brain && … >> canon/y.md").
  const touchesCanon = /\.project-brain\/canon/.test(cmd)
    || (/\bcanon\//.test(cmd) && CAPSULE.test(cmd));
  // indexOf instead of [\s\S]* keeps this linear on long inputs.
  const promoteAt = cmd.search(/brain-promote(\.js)?\b/);
  const isApprovedPromote = promoteAt >= 0 && cmd.indexOf("--approve", promoteAt) >= 0;
  // Redirects to the null device or stderr-merge can never write canon — strip
  // them before mutation detection so read commands like "ls canon/ 2>/dev/null"
  // are not falsely denied. A real redirect target (> canon/x.md) survives.
  // No leading \d*: it made these replaces quadratic on long digit runs.
  const scrubbed = cmd
    .replace(/&>\s*\/dev\/null/g, " ")
    .replace(/>\s*\/dev\/null/g, " ")
    .replace(/>&\d+/g, " ");
  const sedInPlace = scrubbed.split("|").some((seg) => {
    const k = seg.search(/\bsed\b/);
    return k >= 0 && seg.indexOf("-i", k) >= 0;
  });
  const mutates = /(>>?|\btee\b|\bmv\b|\bcp\b|\brm\b)/.test(scrubbed) || sedInPlace
    || /\bnode\s+(-e|--eval)\b|\bpython3?\s+-c\b|\bperl\s+-e\b/.test(scrubbed)
    || /writeFileSync|\bopen\(/.test(scrubbed);
  if (touchesCanon && mutates && !isApprovedPromote)
    deny("Only brain-promote.js --approve may modify .project-brain/canon/");

  // ── deleting the capsule ───────────────────────────────────────────────────
  // A delete counts only when the deleting program is the command being run (not a
  // word inside an argument or a file name), and the capsule is its target: named in
  // the same pipeline (covers "find … | xargs rm"), or entered earlier with cd/pushd.
  // Quotes are dropped so quoted targets and sh -c "…" bodies are seen as words.
  const DELETERS = new Set(["rm", "rmdir", "unlink", "shred"]);
  // Programs that run another command given in their arguments: any deleter word in
  // their arguments counts (errs toward denial, e.g. "xargs grep rm").
  const RUNNERS = new Set(["sudo", "doas", "env", "command", "builtin", "exec", "nohup", "time",
    "timeout", "nice", "ionice", "stdbuf", "xargs", "eval", "bash", "sh", "zsh", "dash", "ksh", "fish"]);
  // Shell keywords that may precede a command word.
  const KEYWORDS = new Set(["do", "then", "else", "elif", "if", "while", "until", "!"]);
  const prog = (t) => t.replace(/^\\/, "").replace(/^.*\//, "");
  const findDeletes = (toks) => toks.some((t, i) => t === "-delete"
    || (/^-(exec|execdir|ok|okdir)$/.test(t) && i + 1 < toks.length && DELETERS.has(prog(toks[i + 1]))));
  const gitDeletes = (toks) => {
    let i = 1;
    while (i < toks.length && toks[i].startsWith("-")) i += /^-(C|c)$/.test(toks[i]) ? 2 : 1;
    return toks[i] === "rm" || toks[i] === "clean";
  };
  const deletes = (stage) => {
    const toks = stage.split(/\s+/).filter(Boolean);
    let i = 0;
    while (i < toks.length && (KEYWORDS.has(toks[i]) || /^[A-Za-z_][A-Za-z0-9_]*=/.test(toks[i]))) i++;
    const rest = toks.slice(i);
    if (!rest.length) return false;
    const p = prog(rest[0]);
    if (DELETERS.has(p)) return true;
    if (p === "find") return findDeletes(rest);
    if (p === "git") return gitDeletes(rest);
    if (RUNNERS.has(p)) return rest.slice(1).some((t) => DELETERS.has(prog(t)))
      || (rest.some((t) => prog(t) === "find") && findDeletes(rest));
    return false;
  };
  const isCd = (stage) => /^\s*(cd|pushd)(\s|$)/.test(stage);
  const pipelines = cmd
    .replace(/\\\n/g, " ")                    // line continuations join one command
    .replace(/["\x27]/g, "")                  // drop quotes
    .replace(/[<>]&\d*-?|&>>?/g, " ")         // fd redirects: their & is not a separator (no leading \d*: quadratic)
    .replace(/\|&/g, "|")
    .split(/\|\||&&|[;&\n()`{}]/);
  let inCapsule = false;
  for (const pl of pipelines) {
    const stages = pl.split("|");
    const namesCapsule = CAPSULE.test(pl);
    if (stages.some(isCd) && namesCapsule) inCapsule = true;
    if ((namesCapsule || inCapsule) && stages.some(deletes))
      deny("Destructive command targeting .project-brain/ blocked — the capsule is governed memory");
  }

  // Reference sources are documentation only — block direct installs into the skills dir.
  if (/reference-repositories\/sources\//.test(cmd) && /\b(cp|mv|ln|rsync)\b/.test(cmd) && /\.claude\/skills|~\/\.claude/.test(cmd))
    deny("Direct install from reference-repositories/sources/ is forbidden — route through skill-scout, skill-audit, skill-adapt");
}
' 2>/dev/null)" || {
  RC=$?
  MSG="brain-security-guard: node could not run the guard (exit ${RC}) — failing open, this tool call was NOT checked"
  echo "${MSG}" >&2
  if [ -d "${ROOT}/.project-brain" ]; then
    mkdir -p "${ROOT}/.project-brain/reports" 2>/dev/null
    printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "${MSG}" >> "${ROOT}/.project-brain/reports/guard-failures.log" 2>/dev/null
  fi
  exit 1
}
[ -n "${DECISION}" ] && printf '%s' "${DECISION}"
exit 0
