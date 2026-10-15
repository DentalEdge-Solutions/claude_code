#!/usr/bin/env bash
# hooks/brain/brain-security-guard.sh — PreToolUse guard. The ONLY blocking brain
# hook. Denies: direct Write/Edit/NotebookEdit into .project-brain/canon/; Bash
# mutations of canon/ not going through brain-promote --approve; deleting the
# capsule (any rm/rmdir/unlink/shred word, find -delete, git rm/clean, fs.rmSync,
# shutil.rmtree, also after a cd into the capsule). Only stages run by programs that
# never execute their arguments (grep, cat, echo, git add/commit/log …) are exempt.
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
  // As on main, any rm/rmdir/unlink/shred word counts as a delete — also behind sudo,
  // busybox, ssh, a git alias or "| sh". One exemption: a stage whose command never runs
  // its arguments (grep, cat, echo, safe git subcommands …), if it has no command
  // substitution and feeds only such programs. So "grep rm <capsule path>" passes, while
  // "echo rm … | sh" does not. The capsule is the target when named in the same pipeline
  // (covers "find … | xargs rm") or entered earlier with cd/pushd. Find -delete and
  // git rm/clean count too.
  const DELETERS = new Set(["rm", "rmdir", "unlink", "shred"]);
  // No pagers (less, more, ag/ack --pager), no sort (--compress-program, abbreviable), and no
  // network git (fetch/push/pull run ssh and --upload-pack): they can run a command.
  const NON_EXEC = new Set(["grep", "egrep", "fgrep", "rg", "cat", "ls", "head", "tail", "wc",
    "echo", "printf", "file", "stat", "du", "diff", "cmp", "uniq", "cut", "tr",
    "basename", "dirname", "realpath", "readlink", "cd", "pushd", "popd", "mkdir", "touch", "test", "[",
    "true", "false", "column", "nl", "tee", "pwd", "jq"]);
  const GIT_NON_EXEC = new Set(["add", "commit", "status", "log", "diff", "show", "grep", "blame", "ls-files",
    "ls-tree", "rev-parse", "branch", "switch", "tag", "mv", "restore"]);
  // Options that make a reader run a program: rg --pre / --hostname-bin, git grep -O /
  // --open-files-in-pager (git accepts it shortened, so any --ope…), git -c, --ext-diff and
  // similar. Any of them ends the exemption. The program a reader runs through its config
  // (pager, diff driver) can only be set from the command line by -c or VAR=, both covered.
  const EXEC_OPT = /^(--(pre|hostname-bin|pager|compress-program|use-compress-program|upload-pack|receive-pack|exec|config-env|exec-path|ext-diff|extcmd|tool|textconv|ope)|-c$|-[A-Za-z]*O)/;
  const KEYWORDS = new Set(["do", "then", "else", "elif", "if", "while", "until", "time"]);
  const prog = (t) => t.replace(/^.*\//, "");
  const unquote = (s) => s.replace(/["\x27\\]/g, "");
  // Words for delete detection: split on whitespace and shell punctuation, so
  // "{x,.project-brain}", "$(rm …)" and "alias.x=!rm" expose their parts. Done twice:
  // quotes dropped ("r""m" is rm) and quotes as separators (env -S\x27rm …\x27 is not -Srm).
  const PUNCT = /[\s(){}`$=!;<>|&,]+/;
  const quotedWords = (s) => s.split(/[\s(){}`$=!;<>|&,"\x27\\]+/).filter(Boolean);
  // Shell words: adjacent quoted and unquoted pieces join ("-O\"r\"m" is -Orm), whitespace
  // inside quotes stays in the word, a backslash escapes the next character. Each word is
  // then split at shell punctuation other than whitespace (x=-Orm gives -Orm).
  const shellWords = (s) => {
    const out = [];
    let cur = "", q = "";
    for (let i = 0; i < s.length; i++) {
      const c = s[i];
      if (q) { if (c === q) q = ""; else if (c === "\\" && q === "\"") cur += s[++i] || ""; else cur += c; continue; }
      if (c === "\x27" || c === "\"") { q = c; continue; }
      if (c === "\\") { cur += s[++i] || ""; continue; }
      if (/\s/.test(c)) { if (cur) out.push(cur); cur = ""; continue; }
      cur += c;
    }
    if (cur) out.push(cur);
    return out.flatMap((w) => w.split(/[(){}`$=!;<>|&,]+/)).filter(Boolean);
  };
  const words = (s) => unquote(s).split(PUNCT).filter(Boolean).concat(quotedWords(s));
  // Script-level deletes: node fs.rmSync / unlinkSync / rmdirSync, python shutil.rmtree, rimraf.
  const API_DELETE = /\b(rmSync|rmdirSync|unlinkSync|rmtree|rimraf)\b/;
  const head = (stage) => {
    const ws = unquote(stage).trim().split(/\s+/);
    let i = 0, env = false;
    for (;;) {
      const w = ws[i];
      if (w === undefined) break;
      // A VAR=value prefix (PAGER=, GIT_EXTERNAL_DIFF=, LESSOPEN=) can make a reader run a program.
      if (/^[A-Za-z_][A-Za-z0-9_]*=/.test(w)) { env = true; i++; continue; }
      if (KEYWORDS.has(w) || /^[({!]+$/.test(w)) { i++; continue; }
      // A leading redirection: ">/dev/null", "2>&1", or "<" followed by its target.
      if (/^\d*(<<?<?|>>?|&>>?|>&|<&)/.test(w)) { i += /^\d*(<<?<?|>>?|&>>?)$/.test(w) ? 2 : 1; continue; }
      break;
    }
    return { cmd: prog((ws[i] || "").replace(/^[({!]+/, "")), rest: ws.slice(i + 1), env };
  };
  const gitSub = (rest) => {
    let i = 0, config = false;
    while (i < rest.length && rest[i].startsWith("-")) {
      if (/^(-c|--config-env|--exec-path)/.test(rest[i])) config = true;
      i += /^-(C|c)$/.test(rest[i]) ? 2 : 1;
    }
    return { sub: rest[i] || "", config };
  };
  // find is a reader unless it runs something (-exec family); -delete is checked separately.
  const nonExec = (h) => !h.env && !h.rest.some((t) => EXEC_OPT.test(t)) && (NON_EXEC.has(h.cmd)
    || (h.cmd === "find" && !h.rest.some((t) => /^-(exec|execdir|ok|okdir)$/.test(t)))
    || (h.cmd === "git" && ((g) => !g.config && GIT_NON_EXEC.has(g.sub))(gitSub(h.rest))));
  // git clean with -n / --dry-run only lists what it would remove.
  const gitCleanDryRun = (rest) => rest.some((t) => t === "--dry-run" || /^-[A-Za-z]*n[A-Za-z]*$/.test(t));
  const stageDeletes = (stage, h, exempt) => {
    const w = words(stage);
    // find -delete: when find is the command, or anywhere in a stage that runs commands.
    if ((h.cmd === "find" || !exempt) && w.some((t) => prog(t) === "find") && w.includes("-delete")) return true;
    if (h.cmd === "git") {
      const sub = gitSub(h.rest).sub;
      if (sub === "rm" || (sub === "clean" && !gitCleanDryRun(h.rest))) return true;
    }
    // A deleter glued to a short option ("git grep -Orm", -O"r"m) counts too. Checked on
    // shell words, so env -S\x27farm .project-brain\x27 is the one word "-Sfarm .project-brain".
    return !exempt && (w.some((t) => DELETERS.has(prog(t)))
      || shellWords(stage).some((t) => /^-[A-Za-z]*(rm|rmdir|unlink|shred)$/.test(t))
      || API_DELETE.test(stage));
  };
  // Where cd/pushd/popd leave the shell: depth below the capsule root, or -1 outside.
  // A target naming the capsule sets the depth from what follows it; an absolute or home
  // target leaves; a relative one walks from the current depth; anything unknown (a
  // variable, "cd -") keeps the current state, which errs toward denial.
  const cdDepth = (target, depth) => {
    const t = target === undefined ? "~" : target;
    const at = t.search(CAPSULE);
    if (at >= 0) return t.slice(at).split("/").slice(1).filter((p) => p && p !== ".").reduce((d, p) => (p === ".." ? d - 1 : d + 1), 0);
    if (/^[\/~]/.test(t)) return -1;
    if (t === "-" || /\$/.test(t) || depth < 0) return depth;
    for (const p of t.split("/")) {
      if (p === "..") depth--; else if (p && p !== ".") depth++;
      if (depth < 0) return -1;
    }
    return depth;
  };
  // Split like the shell: ; & && || | |& and newline separate only outside quotes; a
  // backslash escapes the next character; \<newline> joins lines; &> >& <& are redirects.
  const splitShell = (s) => {
    const pipelines = [];
    let stages = [], cur = "", q = "";
    const endStage = () => { stages.push(cur); cur = ""; };
    const endPipeline = () => { endStage(); pipelines.push(stages); stages = []; };
    for (let i = 0; i < s.length; i++) {
      const c = s[i];
      if (q === "\x27") { if (c === "\x27") q = ""; cur += c; continue; }
      if (c === "\\") { if (s[i + 1] === "\n") cur += " "; else cur += c + (s[i + 1] || ""); i++; continue; }
      if (q === "\"") { if (c === "\"") q = ""; cur += c; continue; }
      if (c === "\x27" || c === "\"") { q = c; cur += c; continue; }
      if (c === ";" || c === "\n") { endPipeline(); continue; }
      if (c === "&") {
        if (s[i + 1] === "&") { i++; endPipeline(); continue; }
        if (s[i + 1] === ">" || s[i - 1] === ">" || s[i - 1] === "<") { cur += c; continue; }
        endPipeline(); continue;
      }
      if (c === "|") {
        if (s[i + 1] === "|") { i++; endPipeline(); continue; }
        if (s[i + 1] === "&") i++;
        endStage(); continue;
      }
      cur += c;
    }
    endPipeline();
    return pipelines;
  };
  const SUBST = /\$\(|`|[<>]\(/;
  let depth = -1;
  const dirStack = [];
  for (const stages of splitShell(cmd)) {
    const heads = stages.map(head);
    for (const [k, h] of heads.entries()) {
      // When the stage names the capsule ("cd \"$(git rev-parse …)/.project-brain\""),
      // take the target from the capsule name on; otherwise the first non-option word.
      const named = unquote(stages[k]).match(/\.project-brain\S*/);
      const target = named ? named[0] : h.rest.find((t) => !t.startsWith("-"));
      if (h.cmd === "cd") depth = cdDepth(target, depth);
      else if (h.cmd === "pushd") { dirStack.push(depth); depth = cdDepth(target, depth); }
      else if (h.cmd === "popd" && dirStack.length) depth = dirStack.pop();
    }
    if (depth < 0 && !stages.some((s) => CAPSULE.test(s))) continue;
    // Walk back from the last stage: a stage keeps its exemption only if every later
    // stage is non-exec too, so output never reaches a shell, xargs or interpreter.
    let downstreamNonExec = true;
    for (let k = stages.length - 1; k >= 0; k--) {
      const ne = nonExec(heads[k]);
      if (stageDeletes(stages[k], heads[k], ne && downstreamNonExec && !SUBST.test(stages[k])))
        deny("Destructive command targeting .project-brain/ blocked — the capsule is governed memory");
      downstreamNonExec = downstreamNonExec && ne;
    }
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
