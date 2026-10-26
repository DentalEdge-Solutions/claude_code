#!/usr/bin/env bash
# hooks/brain/brain-security-guard.sh — PreToolUse guard. The ONLY blocking brain
# hook. Denies: direct Write/Edit/NotebookEdit into .project-brain/canon/ or
# .project-brain/decisions/active/; Bash mutations of either not made by exactly one
# brain-promote.js --approve call; deleting the capsule (any rm/rmdir/unlink/shred word,
# find -delete, git rm/clean, fs.rmSync, shutil.rmtree, also after a cd into the capsule).
# Only stages run by programs that never execute their arguments (grep, cat, echo, git
# add/commit/log …) are exempt.
# Failure policy (P0-09, 2026-10-26; supersedes the P11 fail-open policy of 2026-10-15):
#   - bad input (empty, not JSON, not an object with tool_name/tool_input) fails
#     CLOSED: deny with a reason. Claude Code always sends valid input.
#   - node missing, crashing, killed or past the deadline below fails CLOSED: exit 2
#     (Claude Code blocks the call and shows the stderr reason to Claude), a stderr
#     reason and a log line in .project-brain/reports/guard-failures.log. If node is
#     broken, every Write/Edit/Bash is blocked: the owner's break-glass procedure is in
#     docs/SECOND_BRAIN_SECURITY.md.
#   - the registration sets "onFailure": "block" (a guard that cannot start, or that runs
#     past the hook timeout of 30 s, blocks) — see .claude/settings.json.
# Denial is expressed via permissionDecision with exit 0. Every pattern is linear-time.
# The guard stops node at BRAIN_GUARD_DEADLINE_S (default 20 s, under the 30 s hook timeout),
# so a stall blocks the call even under a registration without onFailure.
# Defense-in-depth only: brain-promote --approve + git history are the real
# canon boundary; this guard raises the cost of accidental/careless mutation.
set -u
ROOT="${CLAUDE_PROJECT_DIR:-$PWD}"
DEADLINE="${BRAIN_GUARD_DEADLINE_S:-20}"
case "${DEADLINE}" in ''|*[!0-9]*|0) DEADLINE=20 ;; esac
# The hook input reaches node on stdin, never through an environment variable: a large
# input (a big Write) would exceed the exec size limit and make node fail to start.
# exec: the background job below is node itself, so the deadline kills the process that holds
# the output pipe (killing a subshell would leave node running and the pipe open).
guard() {
  exec node -e '
const fs = require("fs");
const path = require("path");
// The program must deny or reach its last line. This text is a bash single-quoted string, so a
// stray apostrophe ends it early and node runs only the part before it; that part exits 3 here,
// and the wrapper blocks the call (it did once during P0-09: the helpers ran, nothing was checked).
let finished = false;
process.on("exit", (code) => { if (code === 0 && !finished) process.exitCode = 3; });
const deny = (reason) => {
  console.log(JSON.stringify({ hookSpecificOutput: {
    hookEventName: "PreToolUse", permissionDecision: "deny", permissionDecisionReason: reason } }));
  finished = true;
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

// ── One canonical form for every protected-path check (P0-09 background reviews B, C, D, F) ──
// fold: the name a case-insensitive, normalization-insensitive disk (macOS APFS) resolves to, or a
// broader one: compatibility decomposition (fullwidth letters, the Kelvin sign and the long s
// become ASCII), combining marks dropped (a dotted I loses its dot), then upper- and lowercased
// (a dotless i becomes i). Folding more than the disk does only adds denials.
const fold = (s) => s.normalize("NFKD").replace(/\p{M}/gu, "").toUpperCase().toLowerCase();
// The working directory of the shell: the cwd field of the hook input (it follows a cd), else the cwd of this process.
const CWD = typeof j.cwd === "string" && j.cwd ? j.cwd : process.cwd();
const realOr = (p) => { try { return fs.realpathSync(p); } catch { return null; } };
// canonical: the path the operating system opens. Walks the segments left to right as the kernel
// does: each existing prefix is replaced by its real path (symlinks resolved), so ".." applies to
// the real folder ("link/../x" is the link target parent x, not the lexical one); "" and "." are
// skipped; a missing segment is kept as written. Over 4096 characters a path cannot be opened
// (PATH_MAX), so it is only resolved lexically; the walk is at most about 2,000 steps.
const canonical = (p, base) => {
  const start = path.isAbsolute(p) ? "/" : (realOr(base) || path.resolve(base));
  if (p.length > 4096) return path.resolve(start, p);
  let cur = start;
  for (const seg of p.split("/")) {
    if (!seg || seg === ".") continue;
    if (seg === "..") { cur = path.dirname(cur); continue; }
    const next = path.join(cur, seg);
    cur = realOr(next) || next;
  }
  return cur;
};
// kindOf: "canon", "active" or "capsule" for a canonical absolute path under .project-brain
// (compared folded), else null. depthOf: segments below the last capsule folder, or -1.
// "ancestor" is the capsule folder itself or its decisions/ folder: moving, re-permissioning or
// syncing over it reaches the protected folders inside (background review G).
const kindOf = (abs) => {
  const s = abs.split("/").map(fold);
  let k = null;
  for (let i = 0; i < s.length; i++) {
    if (s[i] !== ".project-brain") continue;
    if (s[i + 1] === "canon") return "canon";
    if (s[i + 1] === "decisions" && s[i + 2] === "active") k = "active";
    else if (k !== "active" && (i === s.length - 1 || (s[i + 1] === "decisions" && i + 1 === s.length - 1))) k = "ancestor";
    else if (!k) k = "capsule";
  }
  return k;
};
// ANSI-C quoting: bash decodes $\x27\x5cx2e...\x27 to text the rules below must see.
const ansiC = (s) => s.replace(/\$\x27((?:\\.|[^\x27\\])*)\x27/g, (m, body) => body.replace(
  /\\(x[0-9a-fA-F]{1,2}|u[0-9a-fA-F]{1,4}|U[0-9a-fA-F]{1,8}|[0-7]{1,3}|.)/g, (e, c) => {
    if (/^[xuU]/.test(c)) { const cp = parseInt(c.slice(1), 16); return cp <= 0x10FFFF ? String.fromCodePoint(cp) : ""; }
    if (/^[0-7]/.test(c)) return String.fromCharCode(parseInt(c, 8));
    return { n: "\n", t: "\t", r: "\r", a: "\x07", b: "\b", e: "\x1b", f: "\f", v: "\v" }[c] || c;
  }));
// Brace expansion as bash does it ({a,b}; a sequence {x..y} may be anything, so it becomes *), at
// most 64 results: null when there would be more.
const braces = (w) => {
  const out = [];
  const go = (s) => {
    if (out.length > 64) return;
    for (let i = 0; i < s.length; i++) {
      if (s[i] !== "{") continue;
      let depth = 0, j = i, commas = [];
      for (; j < s.length; j++) {
        if (s[j] === "{") depth++;
        else if (s[j] === "}") { depth--; if (depth === 0) break; }
        else if (s[j] === "," && depth === 1) commas.push(j);
      }
      if (j >= s.length) break;
      const inner = s.slice(i + 1, j);
      if (commas.length) {
        let from = i + 1;
        for (const c of [...commas, j]) { go(s.slice(0, i) + s.slice(from, c) + s.slice(j + 1)); from = c + 1; }
        return;
      }
      if (/\.\./.test(inner)) { go(s.slice(0, i) + "*" + s.slice(j + 1)); return; }
    }
    out.push(s);
  };
  go(w);
  return out.length > 64 ? null : out;
};
// Does a glob (already brace-expanded) name a protected folder, a folder above it or one below it?
// Segments are compared folded; *, ? and [...] match within a segment and, as in bash, not a
// leading dot unless the pattern segment starts with one. ".." and "." are applied lexically.
const globReaches = (pattern, base, targets) => {
  const segs = [];
  for (const p of (pattern.startsWith("/") ? pattern : base + "/" + pattern).split("/")) {
    if (!p || p === ".") continue;
    if (p === "..") segs.pop(); else segs.push(fold(p));
  }
  // A bracket class matches one character (any: broader than bash, so only more denials).
  const pats = segs.map((p) => p.replace(/\[[^\]]*\]/g, "?"));
  // Wildcard match without a regex: two pointers, O(length of pattern x length of name).
  const wild = (p, s) => {
    let i = 0, k = 0, star = -1, mark = 0;
    while (k < s.length) {
      if (i < p.length && (p[i] === "?" || p[i] === s[k])) { i++; k++; }
      else if (i < p.length && p[i] === "*") { star = i++; mark = k; }
      else if (star >= 0) { i = star + 1; k = ++mark; }
      else return false;
    }
    while (i < p.length && p[i] === "*") i++;
    return i === p.length;
  };
  return targets.some((t) => {
    const n = Math.min(t.length, pats.length);
    for (let i = 0; i < n; i++) {
      if (t[i].startsWith(".") && !pats[i].startsWith(".")) return false;
      if (!wild(pats[i], t[i])) return false;
    }
    return true;
  });
};
const depthOf = (abs) => {
  const s = abs.split("/").map(fold);
  const i = s.lastIndexOf(".project-brain");
  return i < 0 ? -1 : s.length - i - 1;
};
const home = (w) => (/^~(\/|$)/.test(w) && process.env.HOME ? path.join(process.env.HOME, w.slice(1)) : w);

if (["Write", "Edit", "NotebookEdit"].includes(tool)) {
  const target = tool === "NotebookEdit" ? inp.notebook_path : inp.file_path;
  if (typeof target !== "string") malformed(tool + " without a string path");
  // The canonical form: "..", ".", "//" and symlinks resolved as the kernel does, names folded.
  const kind = kindOf(canonical(target, CWD));
  if (kind === "canon")
    deny("Direct writes to .project-brain/canon/ are forbidden. Promote a reviewed candidate instead: node scripts/brain/brain-promote.js <candidate> --approve --to canon");
  if (kind === "active")
    deny("Direct writes to .project-brain/decisions/active/ are forbidden. Stage the change as a candidate with the same file name and apply it with: node scripts/brain/brain-promote.js decisions/candidates/<file> --approve --to active --force (retire one with: --to superseded)");
}

if (tool === "Bash") {
  if (typeof inp.command !== "string") malformed("Bash command is not a string");
  // Bash removes a backslash-newline (a line continuation), so "r\<newline>m" is rm. Join them
  // first, so every rule below and the floor see the command bash runs. Quotes are tracked as
  // bash does: unquoted and inside double quotes the pair is removed; inside single quotes it
  // is literal; a # starts a comment only at the start of a word outside quotes, and in a
  // comment the newline ends the comment, so the next line is a command of its own. An escaped
  // backslash (\\) stays a pair. kept is where the first pair was left in place (in single
  // quotes or a comment); a fail-closed check below uses it, since a quoting form read
  // differently from bash ($\x27…\x5c\x27…\x27) can only show up as a pair that was kept. One linear pass.
  // prev is the last character emitted. Never index out: it is built with +=, and reading a
  // character of such a string flattens it each time, which made this pass quadratic.
  const joinLines = (s) => {
    let out = "", q = "", comment = false, kept = -1, prev = "";
    const emit = (t) => { out += t; prev = t[t.length - 1]; };
    for (let i = 0; i < s.length; i++) {
      const c = s[i];
      if (comment || q === "\x27") {
        if (c === "\\" && s[i + 1] === "\n" && kept < 0) kept = out.length;
        emit(c);
        if (comment && c === "\n") comment = false;
        else if (q === "\x27" && c === "\x27") q = "";
        continue;
      }
      if (c === "\\") { if (s[i + 1] !== "\n") emit(c + (s[i + 1] || "")); i++; continue; }
      if (q === "\"") { if (c === "\"") q = ""; emit(c); continue; }
      if (c === "\x27" || c === "\"") q = c;
      else if (c === "#" && (!prev || /[\s;&|()]/.test(prev))) comment = true;
      emit(c);
    }
    return { text: out, kept };
  };
  const joined = joinLines(inp.command);
  const cmd = joined.text;
  // Case-insensitive: macOS disks are case-insensitive by default, so .PROJECT-BRAIN is the capsule
  // there (background security review of P0-09).
  const CAPSULE = /\.project-brain/i;
  // The command as the protected-path rule reads it: ANSI-C escapes decoded, quotes and
  // backslashes dropped (bash joins .pro"ject"-br\ain into one name), folded (case and Unicode,
  // as for paths), with "//" and "/./" collapsed (background reviews C, F, H).
  const decoded = ansiC(cmd);
  const fcmd = fold(decoded.replace(/[\\"\x27]/g, "")).replace(/\/(?:\.?\/)+/g, "/");
  // G1 (P0-09): the exemption holds only for a command that is exactly one plain call,
  // "node <script> <words> … --approve …", where <script> is scripts/brain/brain-promote.js,
  // ./scripts/brain/brain-promote.js or $CLAUDE_PROJECT_DIR/scripts/brain/brain-promote.js
  // written out (never another folder that merely ends that way): no separator, redirect,
  // substitution, quote, escape, glob, assignment, comment or control character anywhere in the
  // raw command, so nothing can be chained to it. Read on the raw text: with no backslash there
  // is no line continuation either. Anything else gets no exemption.
  const raw = inp.command;
  const isApprovedPromote = (() => {
    if (/[^\x20-\x7e]/.test(raw) || /[;&|<>`$()\\"\x27#*?{}\[\]~!=]/.test(raw)) return false;
    const ws = raw.trim().split(/ +/);
    const script = ws[1] || "";
    return ws[0] === "node"
      && (script === "scripts/brain/brain-promote.js" || script === "./scripts/brain/brain-promote.js"
        || (!!process.env.CLAUDE_PROJECT_DIR
          && script === path.join(process.env.CLAUDE_PROJECT_DIR, "scripts", "brain", "brain-promote.js")))
      && ws.slice(2).includes("--approve");
  })();
  // Redirects to the null device or stderr-merge can never write canon — strip
  // them before mutation detection so read commands like "ls canon/ 2>/dev/null"
  // are not falsely denied. A real redirect target (> canon/x.md) survives.
  // No leading \d*: it made these replaces quadratic on long digit runs.
  const scrubbed = cmd
    .replace(/&>\s*\/dev\/null/g, " ")
    .replace(/>\s*\/dev\/null/g, " ")
    .replace(/>&\d+/g, " ");

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
  const shellWordsRaw = (s) => {
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
    return out;
  };
  const shellWords = (s) => shellWordsRaw(s).flatMap((w) => w.split(/[(){}`$=!;<>|&,]+/)).filter(Boolean);
  // The words git receives: shell words after the git word, up to the first redirect or
  // comment. A quoted "x log" stays one word, so it can never pose as the subcommand.
  // Anchored on the command word, skipping the same prefixes as head() (VAR=…, keywords, a
  // leading redirection), never on the first word that merely ends in /git ("2>./git git …").
  // null when the shell words do not show git there: the caller treats that as unknown.
  const gitArgs = (stage) => {
    const ws = shellWordsRaw(stage);
    let i = 0;
    for (; i < ws.length; i++) {
      const w = ws[i];
      if (/^[A-Za-z_][A-Za-z0-9_]*=/.test(w) || KEYWORDS.has(w) || /^[({!]+$/.test(w)) continue;
      if (/^\d*(<<?<?|>>?|&>>?|>&|<&)/.test(w)) { if (/^\d*(<<?<?|>>?|&>>?)$/.test(w)) i++; continue; }
      break;
    }
    if (prog((ws[i] || "").replace(/^[({!]+/, "")) !== "git") return null;
    const out = [];
    for (i++; i < ws.length && !/^(\d*[<>]|#)/.test(ws[i]); i++) out.push(ws[i]);
    return out;
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
    const cmd = prog((ws[i] || "").replace(/^[({!]+/, ""));
    return { cmd, rest: ws.slice(i + 1), env, git: cmd === "git" ? gitArgs(stage) : [] };
  };
  // Global options that take the next word as their value (git 2.54). That value must never be
  // read as the subcommand: in "git --namespace log rebase -x …" the subcommand is rebase.
  const GIT_ARG_OPT = /^(-C|-c|--git-dir|--work-tree|--namespace|--config-env|--attr-source|--shallow-file)$/;
  const GIT_FLAG_OPT = /^(-p|-P|--paginate|--no-pager|--bare|--no-replace-objects|--(literal|glob|noglob|icase)-pathspecs|--no-optional-locks|--no-lazy-fetch|--no-advice|--(git-dir|work-tree|namespace|attr-source)=.*)$/;
  // config is true when an option can make git run a program (-c, --config-env, --exec-path), is
  // not recognized, or a word up to the subcommand holds a variable, glob or backtick (it may
  // split into several words, so its value could pose as the subcommand). Each ends the exemption.
  // rest must be shell words (gitArgs), not whitespace-split text.
  const UNSAFE_WORD = /[$`*?[\]{}~]/;
  // unsafeSub: the subcommand is spelled with $, a glob or a backtick ($\x27cl\x5cx65an\x27), or the
  // git words could not be read; it may be clean or rm, so the caller counts it as a delete.
  const gitSub = (rest) => {
    if (rest === null) return { sub: "", config: true, unsafeSub: true };
    let i = 0, config = false;
    while (i < rest.length && rest[i].startsWith("-")) {
      const t = rest[i];
      if (/^(-c|--config-env|--exec-path)/.test(t) || !(GIT_ARG_OPT.test(t) || GIT_FLAG_OPT.test(t))
        || UNSAFE_WORD.test(t)) config = true;
      if (GIT_ARG_OPT.test(t)) { if (UNSAFE_WORD.test(rest[i + 1] || "")) config = true; i += 2; } else i++;
    }
    const sub = rest[i] || "";
    const unsafeSub = UNSAFE_WORD.test(sub);
    if (unsafeSub) config = true;
    return { sub, config, unsafeSub };
  };
  // find is a reader unless it runs something (-exec family); -delete is checked separately.
  const nonExec = (h) => !h.env && !h.rest.some((t) => EXEC_OPT.test(t)) && (NON_EXEC.has(h.cmd)
    || (h.cmd === "find" && !h.rest.some((t) => /^-(exec|execdir|ok|okdir)$/.test(t)))
    || (h.cmd === "git" && ((g) => !g.config && GIT_NON_EXEC.has(g.sub))(gitSub(h.git))));
  // A git clean dry run is recognized only in a plain grammar that git cannot read another way,
  // not by parsing git (that was bypassed with quoting, -e values, -- and --end-of-options). The
  // stage has no quote, escape, variable, glob, redirect, comment or "="; before clean only
  // "-C <dir>"; after it only -[dfnqxX]+, --dry-run, --quiet, --force and plain paths, with at
  // least one n before any "--". No -e, --end-of-options or --no-… fits, and an -n after "--"
  // is only a path, so git can only see a dry run.
  // Anything else is a delete (a conservative denial when it was a dry run after all).
  const PLAIN_CLEAN_OPT = /^(-[dfnqxX]+|--dry-run|--quiet|--force)$/;
  const plainCleanDryRun = (stage, h) => {
    if (h.cmd !== "git" || h.env || /["\x27\\$`<>#*?[\]{}()~=!;&|]/.test(stage)) return false;
    const ws = stage.trim().split(/\s+/);
    let i = ws.findIndex((t) => prog(t) === "git") + 1;
    if (ws[i] === "-C" && ws[i + 1] && !ws[i + 1].startsWith("-")) i += 2;
    if (ws[i] !== "clean") return false;
    let dry = false;
    for (const t of ws.slice(i + 1)) {
      if (t === "--") break; // only paths follow; the dry run must already be set
      if (!t.startsWith("-")) continue;
      if (!PLAIN_CLEAN_OPT.test(t)) return false;
      if (t === "--dry-run" || (t[1] !== "-" && t.includes("n"))) dry = true;
    }
    return dry;
  };
  const stageDeletes = (stage, h, exempt) => {
    const w = words(stage);
    // find -delete: when find is the command, or anywhere in a stage that runs commands.
    if ((h.cmd === "find" || !exempt) && w.some((t) => prog(t) === "find") && w.includes("-delete")) return true;
    if (h.cmd === "git") {
      const g = gitSub(h.git);
      if (g.sub === "rm" || g.unsafeSub) return true;
      // git clean, or a clean word when an option can hide the subcommand (-c alias.x=clean)
      // or run a program (-c core.editor=…). A -c with an unrelated clean word ("-c x=y log
      // --grep clean") is a conservative denial.
      if ((g.sub === "clean" || (g.config && w.includes("clean"))) && !plainCleanDryRun(stage, h)) return true;
    }
    // git clean run by another program (env, command, nice, sudo, xargs) or nested in a git
    // executor (rebase -x, submodule foreach, bisect run): a clean word next to a git word that
    // is not the command itself.
    // Counted on one splitting with quotes dropped, so a quoted "git clean …" argument shows its
    // git word (words() holds every word twice, once per splitting).
    if (!exempt && w.includes("clean")
      && unquote(stage).split(PUNCT).filter((t) => prog(t) === "git").length >= (h.cmd === "git" ? 2 : 1)) return true;
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
  // Returns one entry per pipeline: { stages, bg }. bg marks a pipeline ended by a single
  // & (run in the background, i.e. in a subshell that cannot change the parent directory).
  const splitShell = (s) => {
    const pipelines = [];
    let stages = [], cur = "", q = "";
    const endStage = () => { stages.push(cur); cur = ""; };
    const endPipeline = (bg) => { endStage(); pipelines.push({ stages, bg: !!bg }); stages = []; };
    for (let i = 0; i < s.length; i++) {
      const c = s[i];
      if (q === "\x27") { if (c === "\x27") q = ""; cur += c; continue; }
      // A backslash-newline left after joinLines sits in a comment: the newline ends the line.
      if (c === "\\") { if (s[i + 1] === "\n") { cur += c; continue; } cur += c + (s[i + 1] || ""); i++; continue; }
      if (q === "\"") { if (c === "\"") q = ""; cur += c; continue; }
      if (c === "\x27" || c === "\"") { q = c; cur += c; continue; }
      if (c === ";" || c === "\n") { endPipeline(false); continue; }
      if (c === "&") {
        if (s[i + 1] === "&") { i++; endPipeline(false); continue; }
        if (s[i + 1] === ">" || s[i - 1] === ">" || s[i - 1] === "<") { cur += c; continue; }
        endPipeline(true); continue;
      }
      if (c === "|") {
        if (s[i + 1] === "|") { i++; endPipeline(false); continue; }
        if (s[i + 1] === "&") i++;
        endStage(); continue;
      }
      cur += c;
    }
    endPipeline(false);
    return pipelines;
  };
  const SUBST = /\$\(|`|[<>]\(/;
  const WEIRD = /\$\x27|#|<<|\$\(|`|<\(|>\(/;
  const scrub = (s) => s.replace(/&>\s*\/dev\/null/g, " ").replace(/>\s*\/dev\/null/g, " ").replace(/>&\d+/g, " ");
  // A pure reader: a program that neither runs its arguments (nonExec) nor writes a file. NON_EXEC
  // alone is not enough: touch, mkdir, tee, uniq (an output file), find -fprint, git restore,
  // switch, branch, tag and mv write (background security review of P0-09). No --output option.
  const READERS = new Set(["grep", "egrep", "fgrep", "rg", "cat", "ls", "head", "tail", "wc", "stat", "du",
    "diff", "cmp", "cut", "tr", "basename", "dirname", "realpath", "readlink", "column", "nl", "pwd", "jq",
    "echo", "printf", "test", "[", "true", "false", "cd", "pushd", "popd"]);
  const GIT_READERS = new Set(["status", "log", "diff", "show", "grep", "blame", "ls-files", "ls-tree", "rev-parse",
    "add", "commit"]);
  const pureReader = (h) => nonExec(h) && !h.rest.some((t) => /^--ou/.test(t)) && (READERS.has(h.cmd)
    || (h.cmd === "find" && !h.rest.some((t) => /^-(exec|execdir|ok|okdir|delete|fprint|fprint0|fprintf|fls)$/.test(t)))
    || (h.cmd === "git" && GIT_READERS.has(gitSub(h.git).sub)));
  // A reader stage: a pure reader, or a plain dry run of the git clean subcommand (plainCleanDryRun),
  // which only lists files.
  const readerStage = (stg) => { const h = head(stg); return pureReader(h) || plainCleanDryRun(stg, h); };
  // A read-only form: every stage of every pipeline is a pure reader, with no command or process
  // substitution, no heredoc, no ANSI-C quoting or comment that could desync the parse, and no
  // file-writing redirect. Nothing in it can write a file.
  const readerForm = () => !WEIRD.test(cmd) && !/>/.test(scrubbed)
    && splitShell(cmd).every((pl) => pl.stages.filter((s) => s.trim()).every(readerStage));

  // ── canon/ and decisions/active/: an allowlist, not a list of write verbs ─────────────────
  // (P0-09; background reviews A-D, F.) A command that reaches canon/ or decisions/active/ passes
  // only as exactly one brain-promote call (G1) or as a read-only form (which also settles G3: an
  // rm word in a reader pipeline is only an argument or part of a file name). It reaches them:
  //   - by name, in the folded text: ".project-brain/canon", ".project-brain/decisions/active",
  //     or the word canon / active in a command that also names the capsule or runs inside it;
  //   - on disk: a word of the command that, resolved from the working directory as the kernel
  //     would (symlinks, "..", "~"), lands in a protected folder;
  //   - from a working directory inside a protected folder.
  // More than 5,000 distinct words are not resolved on disk; such a command passes only in a
  // read-only form.
  const cwdAbs = canonical(CWD, "/");
  const cwdKind = kindOf(cwdAbs);
  //   - a parent of them (the capsule folder or decisions/, by name or on disk): a move, chmod -R or
  //     rsync --delete of it reaches them (review G);
  //   - a glob or brace word (.project-brai?, .pro*/can*, .project-{brain,x}) that may match one
  //     of them, a parent or a file below, against the capsule folders this session can reach
  //     (review G);
  //   - an expansion the guard cannot follow (a variable, $(…), backticks, $\x27…\x27) in a command that
  //     shows a protected-looking name (.project-b…, canon, decisions, active) or runs inside the
  //     capsule: static analysis cannot tell where it leads, so it fails closed (reviews G, H).
  // The brain scripts that never write canon/ or decisions/active/ (verify, lint, search,
  // context-pack, compile, capture) pass as one plain call, like brain-promote.
  const wordKind = new Map();
  // Resolved from the working directory only: the delete rule tracks cd itself.
  const wordKindCwd = new Map();
  // Words as bash splits them (quotes joined), each also split at = < > (--opt=PATH, x>PATH), plus
  // the words of the ANSI-C decoded text.
  const rawWords = [...new Set([...shellWordsRaw(cmd), ...shellWordsRaw(decoded)])];
  const pieces = [...new Set(rawWords.flatMap((w) => [w, ...w.split(/[=<>]+/)]).filter(Boolean))];
  const distinct = [...new Set([...shellWords(cmd), ...shellWords(decoded), ...pieces])];
  // Words are resolved from every folder the shell may be in at that stage: the working directory,
  // plus each cd/pushd target so far (kept, never dropped: a cd inside a subshell or a failed cd
  // may not have moved the shell, so both stay possible). At most 16 folders and 5,000
  // resolutions; past that, or after a cd to a target the guard cannot follow, the folder is
  // unknown. A parent folder (the capsule or decisions/) counts only as an argument of a stage
  // that is not a pure reader ("cd .project-brain && ls" is fine; "mv .project-brain x" is not).
  const EXPANSION = /\$[^\s]|`/;
  const GLOB = /[*?[]|\{[^{}]*(,|\.\.)[^{}]*\}/;
  let dirs = [cwdAbs], dirUnknown = false, budget = 5000, ancestorArg = false;
  const tooMany = distinct.length > 5000;
  if (!tooMany) for (const { stages } of splitShell(cmd)) for (const stg of stages) {
    const h = head(stg);
    const raws = shellWordsRaw(stg);
    const ws = [...new Set([...shellWords(stg), ...shellWords(ansiC(stg)), ...raws.flatMap((w) => [w, ...w.split(/[=<>]+/)])])].filter(Boolean);
    const reader = readerStage(stg);
    for (const w of ws) {
      if (w.length > 4096) continue;
      for (const d of dirs) {
        if (--budget < 0) { dirUnknown = true; break; }
        const k = kindOf(canonical(home(w), d));
        if (!k) continue;
        if (!wordKind.has(w) || k === "canon" || k === "active") wordKind.set(w, k);
        if (d === cwdAbs) wordKindCwd.set(w, k);
        if (k === "ancestor" && !reader) ancestorArg = true;
      }
    }
    if (h.cmd === "cd" || h.cmd === "pushd") {
      const t = raws.slice(raws.indexOf(h.cmd) + 1).find((x) => !x.startsWith("-"));
      if (t !== undefined && (EXPANSION.test(t) || GLOB.test(t) || t === "-")) dirUnknown = true;
      else {
        const next = dirs.map((d) => canonical(home(t === undefined ? "~" : t), d));
        dirs = [...new Set([...dirs, ...next])];
        if (dirs.length > 16) { dirs = dirs.slice(0, 16); dirUnknown = true; }
      }
    }
  }
  const kinds = new Set(wordKind.values());
  // The capsule folders this session can reach: the project one, the one below the working
  // directory, and any a word or the working directory resolved into.
  const roots = new Set([canonical(path.join(process.env.CLAUDE_PROJECT_DIR || CWD, ".project-brain"), "/"),
    canonical(".project-brain", CWD)]);
  for (const abs of [cwdAbs, ...[...wordKind.keys()].map((w) => canonical(home(w), CWD))]) {
    const s = abs.split("/"); const i = s.map(fold).lastIndexOf(".project-brain");
    if (i >= 0) roots.add(s.slice(0, i + 1).join("/"));
  }
  const segsOf = (p) => p.split("/").filter(Boolean).map(fold);
  const protTargets = [...roots].flatMap((r) => [segsOf(r + "/canon"), segsOf(r + "/decisions/active")]);
  const rootTargets = [...roots].map(segsOf);
  const globHits = (targets) => !tooMany && pieces.some((w) => {
    if (EXPANSION.test(w) || !GLOB.test(w)) return false;
    const alts = w.length <= 4096 ? braces(home(w)) : null;
    return alts === null || alts.some((a) => globReaches(a, cwdAbs, targets));
  });
  const undecidable = rawWords.some((w) => EXPANSION.test(w));
  const looksProtected = /\.project-b|roject-brain|canon|decisions|\bactive\b/.test(fcmd) || cwdKind !== null;
  const capsuleLooking = /\.project-b|roject-brain/.test(fcmd) || cwdKind !== null;
  const capsuleCtx = CAPSULE.test(fcmd) || cwdKind !== null || kinds.size > 0;
  const hitCanon = /\.project-brain\/canon\b/.test(fcmd) || (capsuleCtx && /\bcanon\b/.test(fcmd))
    || cwdKind === "canon" || kinds.has("canon");
  const hitActive = /\.project-brain\/decisions\/active\b/.test(fcmd) || (capsuleCtx && /\bactive\b/.test(fcmd))
    || cwdKind === "active" || kinds.has("active");
  const hitOther = ancestorArg || globHits(protTargets) || ((undecidable || dirUnknown) && looksProtected);
  const isBrainTool = !/[^\x20-\x7e]/.test(raw) && !/[;&|<>`$()\\"\x27#*?{}\[\]~!=]/.test(raw) && (() => {
    const ws = raw.trim().split(/ +/);
    const m = /^(?:\.\/)?scripts\/brain\/brain-(verify|lint|search|context-pack|compile|capture)\.js$/.test(ws[1] || "");
    return ws[0] === "node" && m;
  })();
  if ((hitCanon || hitActive || hitOther) && !isApprovedPromote && !isBrainTool && !readerForm())
    deny(hitCanon ? "Only brain-promote.js --approve may modify .project-brain/canon/ (a command that reaches it passes only as one brain-promote call or a read-only form: grep, cat, ls, git log/diff/add …)"
      : hitActive ? "Only brain-promote.js --approve may modify .project-brain/decisions/active/ (the weekly review stages a candidate and runs brain-promote; other commands that reach it pass only in a read-only form)"
      : "brain-security-guard: a word of this command may reach .project-brain/canon/ or decisions/active/ (a parent folder, a glob or brace pattern, or a variable or substitution the guard cannot follow) — denied unless the command is a read-only form. Name the path plainly, or split the command.");
  if (tooMany && !readerForm())
    deny("brain-security-guard: more than 5,000 distinct words; the guard cannot check where they lead on disk. Split the command.");

  // Fail closed on a kept line continuation in a command that names the capsule. A pair is kept
  // only inside single quotes or a comment, so where joinLines reads quotes as bash does this is
  // rare; where it does not (a heredoc body, $\x27\x5c\x27\x27), the rules below see a split command, and no
  // list of delete words is complete (a glued -Or…m, an ANSI-C subcommand). So deny outright.
  // The capsule is looked for in the fully joined, folded text: the kept pair can split its name.
  if (joined.kept >= 0 && CAPSULE.test(fold(cmd.split("\\\n").join(""))))
    deny("brain-security-guard: a line continuation (backslash-newline) inside quotes or a comment, in a command that names .project-brain, is denied — the guard cannot tell how the shell will split it. Put the command on one line.");

  // ── deleting the capsule: run on the command and again with its capsule words folded (deny if
  // either denies). The folded pass sees .PROJECT-BRAIN, fullwidth or dotted-i spellings as the
  // capsule (the disk does); options elsewhere keep their case (git -C, grep -O). Words that
  // resolve into the capsule on disk (a symlink) count as naming it, and a working directory inside
  // the capsule is where the shell starts.
  const deleteRule = (text, onDisk) => {
    const textScrub = scrub(text);
    // A stage names the capsule by name, by a word that resolves into it on disk, by a glob or
    // brace word that may match it (or a folder above it), or by an expansion the guard cannot
    // follow in a command that shows the capsule name (review G).
    const namesCapsule = (s) => CAPSULE.test(s) || (onDisk && (shellWords(s).some((w) => wordKindCwd.has(w))
      || shellWordsRaw(s).some((w) => (EXPANSION.test(w) ? capsuleLooking
        : GLOB.test(w) && (w.length > 4096 || ((alts) => alts === null || alts.some((a) => globReaches(a, cwdAbs, rootTargets)))(braces(home(w))))))));
    let depth = depthOf(cwdAbs);
    const dirStack = [];
    // Any grouping construct — a subshell ( ), a brace group { }, or a case statement — can run a cd
    // in a context that does not move the parent shell (a subshell), or hide a cd that is not the
    // first word of a group that is itself piped/backgrounded. Rather than parse nesting (fragile and
    // repeatedly bypassed), a command line that contains ANY of these is treated as non-plain, so a
    // capsule-LEAVING cd in it is never honored.
    const hasGrouping = /[(){}]/.test(text) || /\bcase\b/.test(text);
    for (const { stages, bg } of splitShell(text)) {
      const heads = stages.map(head);
      // Directory tracking is fail-closed and direction-aware. A move that ENTERS or stays in the
      // capsule (new depth >= 0) is always honored — erring toward a deny is safe. A move that LEAVES
      // the capsule (new depth < 0) is honored only from a plain standalone foreground command: one
      // stage, not backgrounded, and with no grouping construct anywhere on the line (see hasGrouping).
      // So a cd hidden in a subshell, brace group, case, pipeline or the background can never make a
      // later relative delete look safe; the cost is a conservative deny of some exotic "leave the
      // capsule inside a group" forms. popd/pushd are honored only when plain. A target that
      // resolves into the capsule on disk (a symlink) enters it.
      const h0 = heads[0];
      if (h0.cmd === "cd" || h0.cmd === "pushd" || h0.cmd === "popd") {
        const plain = stages.length === 1 && !bg && !hasGrouping;
        // When the stage names the capsule ("cd \"$(git rev-parse …)/.project-brain\""),
        // take the target from the capsule name on; otherwise the first non-option word.
        const named = unquote(stages[0]).match(/\.project-brain\S*/i);
        const target = named ? named[0] : h0.rest.find((t) => !t.startsWith("-"));
        if (h0.cmd === "popd") { if (plain && dirStack.length) depth = dirStack.pop(); }
        else {
          if (h0.cmd === "pushd" && plain) dirStack.push(depth);
          let nd = cdDepth(target, depth);
          if (nd < 0 && onDisk && target !== undefined && target.length <= 4096)
            nd = Math.max(nd, depthOf(canonical(home(target), CWD)));
          if (nd >= 0 || plain) depth = nd;
        }
      }
      if (depth < 0 && !stages.some(namesCapsule)) continue;
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

    // ── superset-of-main floor ─────────────────────────────────────────────────────
    // main denies any rm word followed by .project-brain inside one ;|&-free segment, with a
    // blunt regex that does not depend on how the command is parsed. Keep it as a hard floor so
    // this guard never allows a capsule delete that main would block, even when a quirk of shell
    // parsing (a quote in a comment, ANSI-C quoting, a heredoc body) would otherwise hide the rm.
    // The one exemption: a single foreground pipeline whose every stage never runs its
    // arguments (nonExec: grep, cat, git add/commit/log, find without -exec, ...), with no command
    // or process substitution, none of those parser-desyncing constructs, no background, and no
    // file-writing redirect. There an rm can only be a literal argument, so "grep rm <capsule
    // path>" and a git add of a path whose name contains rm stay allowed, while store-then-run
    // forms stay denied.
    // Linear form of main\x27s /\brm\b[^|;&]*\.project-brain/. That regex is O(n^2): on input
    // padded with many "rm" words the [^|;&]* backtracks from every rm, ~195 s on 1 MB, and a
    // PreToolUse hook that times out did NOT block the call — so it was a bypass. Split on the
    // shell separators first (linear), then in each segment look for an rm word that starts before
    // a .project-brain mention. search(\brm\b) and lastIndexOf are each linear, so the whole check
    // is O(n). Semantics match main: an rm word followed later by .project-brain in one segment.
    // Read lowercased: .PROJECT-BRAIN is the capsule on a case-insensitive disk, and RM finds
    // /bin/rm there.
    const mainDelete = text.split(/[|;&]/).some((seg) => {
      const low = seg.toLowerCase();
      const bi = low.lastIndexOf(".project-brain");
      if (bi < 0) return false;
      const ri = low.search(/\brm\b/);
      return ri >= 0 && ri < bi;
    });
    if (mainDelete) {
      const pls = splitShell(text);
      const exempt = !WEIRD.test(text) && !/>/.test(textScrub) && pls.length === 1 && !pls[0].bg
        && pls[0].stages.every((stg) => nonExec(head(stg)));
      if (!exempt) deny("Destructive command targeting .project-brain/ blocked — the capsule is governed memory");
    }
  };
  deleteRule(cmd, true);
  // The second pass folds only the words that fold onto the capsule name, so case-sensitive
  // options elsewhere (git -C, grep -O) keep their meaning.
  const pcmd = cmd.replace(/[^\s;&|<>()`$"\x27=]+/g, (w) => { const f = fold(w); return CAPSULE.test(f) ? f : w; });
  if (pcmd !== cmd) deleteRule(pcmd, false);

  // Reference sources are documentation only — block direct installs into the skills dir.
  if (/reference-repositories\/sources\//.test(cmd) && /\b(cp|mv|ln|rsync)\b/.test(cmd) && /\.claude\/skills|~\/\.claude/.test(cmd))
    deny("Direct install from reference-repositories/sources/ is forbidden — route through skill-scout, skill-audit, skill-adapt");
}
// Last line: every check ran and none denied, so the call is allowed (exit 0).
finished = true;
' 2>/dev/null
}
# Run the guard with a deadline. node runs in the background with the hook input on fd 3 (a
# background job would otherwise read /dev/null); a watcher kills it once the deadline passes.
# The watcher writes nothing to the command substitution, so a normal check returns at once, and
# it kills only after a sleep that succeeded: a sleep that fails cannot cut a check short.
exec 3<&0
DECISION="$(
  guard 0<&3 &
  GUARD_PID=$!
  (
    trap 'kill "${SLEEP_PID:-}" 2>/dev/null; exit 0' TERM
    sleep "${DEADLINE}" &
    SLEEP_PID=$!
    wait "${SLEEP_PID}" && kill -KILL "${GUARD_PID}" 2>/dev/null
  ) >/dev/null 2>&1 3<&- &
  WATCH_PID=$!
  wait "${GUARD_PID}"
  RC=$?
  kill -TERM "${WATCH_PID}" 2>/dev/null
  exit "${RC}"
)" || {
  RC=$?
  MSG="brain-security-guard: node could not run the guard, or it passed its ${DEADLINE} s deadline (exit ${RC}) — this tool call is BLOCKED (the guard fails closed). If node is broken, the owner's break-glass procedure is in docs/SECOND_BRAIN_SECURITY.md"
  echo "${MSG}" >&2
  if [ -d "${ROOT}/.project-brain" ]; then
    mkdir -p "${ROOT}/.project-brain/reports" 2>/dev/null
    printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "${MSG}" >> "${ROOT}/.project-brain/reports/guard-failures.log" 2>/dev/null
  fi
  exit 2
}
[ -n "${DECISION}" ] && printf '%s' "${DECISION}"
exit 0
