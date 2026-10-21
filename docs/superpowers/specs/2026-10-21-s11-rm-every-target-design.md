# Design 2026-10-21: S11, the `rm` check reads every target

Status: draft for the owner, 2026-10-21. Nothing is built. It changes how `rm-rf-root` in
`skills/skill-audit/scripts/static-scan.js` reads Markdown; it does not touch the brain security guard.

## Goal

`rm-rf-root` finds a recursive or forced `rm` of a root or home path wherever the path sits in the command,
not only when it is the first target, without the faults that sank the last attempt:

1. The forms S11 records are found: `rm -rf ./build ~/`, `rm -rf x /`, `rm --interactive=never -rf /`,
   `rm / -rf`, and after `--` a first target that starts with `-` or a quote (`rm -rf -- --foo-rm ~`).
2. Every finding main makes today is still made, with the same severity and the same quoted line.
3. Scan time stays linear in the input: no input makes it slower than main by more than a small constant.
4. No new false BLOCK across lines, or because of separators inside quotes or redirections.

Done means: the S11 forms are tests that fail on main; the decision of 2026-10-15 is met (a main-versus-
branch differential with every evidence line compared, 1 MB and 4 MB timing including the F1 inputs, and
real inputs); CI's skill scan stays clean.

## In plain language

skill-audit reads a skill's instructions before it is installed and refuses a skill that tells Claude to
delete the root or the home folder. Today it looks only at the first thing after `rm` and its options. A
skill can slip past by putting a harmless folder first: `rm -rf ./build ~/` deletes the home folder and
passes. The fix reads the command the way the shell would, word by word, and checks every target. It is a
second detector beside today's, so nothing today's catches is lost.

## Where it stands

- **The check today** (static-scan.js:129, REFERENCE.md "Dangerous Bash"): one regular expression. `rm`
  after any non-word character, an option run that holds a recursive or force option, then the first target
  must start with `/`, `~` or `$HOME` (quoted or not; `/tmp` counts). An option run holding `--cached` before
  any `--` is `git rm --cached` and is skipped. In Markdown prose a hit is BLOCK; a hit only inside code
  (fenced or inline) is FLAG (owner decision R2, 2026-10-15). `scripts/static-scan.test.js` names it 19 times.
- **The attempt that was dropped** (triage, "Final independent review", 2026-10-15): an every-target regex
  with a `/tmp` exemption. F1, a blocker: `rm -rf "` repeated took 5 s at 100 KB and over 20 s at 1 MB.
  F2: a target was read across lines (`rm -rf dist`, then `cd /usr/src/app`). F3: separators inside
  arguments (`2>&1`, `\;`, a quoted `;`) ended the target list early. F4: the `/tmp` exemption trusted text
  (`/tmp/.\./etc`). The owner then chose the first-target rule with no `/tmp` exemption (active decision
  2026-10-15), and S11 recorded that "a safe version needs a shell-aware tokenizer, not a regex".
- **How often it matters on benign skills** (measured 2026-10-21, a rough whitespace split, not this
  design): 3,016 Markdown files (this repo's skills and agents, the installed `~/.claude/skills` and
  `~/.claude/plugins`) hold 5,076 `rm` commands with `-r` or `-f`. In 2,266 the first target is root or home
  (main finds these: 2,265 in code, 1 in prose). In 1 a later target is and the first is not (in code). In
  prose, no line would gain a finding. So the change adds almost no noise; its value is against a skill
  written to evade the check, which a security gate for external skills has to assume.

## Design

### 1. A second detector, beside today's

Today's regular expression stays byte for byte, and keeps reporting as it does. A new detector, also named
`rm-rf-root`, is a function in the Markdown Bash table: the script loop already takes a `find` function in place of a regular expression, and the Markdown loop gains the same. It reports
a command only when today's expression does not match that command's text, so the two never report the same
command twice and today's quoted line is never replaced (the lesson of PR #167, reviews V1, V9, V11).

### 2. What it reads

The same split as today, so R2 holds:

- **Prose:** the text with code removed (`stripCodeBlocks`), one line at a time. A hit is BLOCK.
- **Code:** each fenced block and each inline span, found with the same two expressions `stripCodeBlocks`
  uses. A hit found only here is FLAG.

A unit is tokenized on its own, so an unclosed quote can never run past its line (prose) or its block (code).

### 3. The tokenizer

One left-to-right pass over a unit, no backtracking. It yields shell words and operators:

- **Quotes:** `'…'` is literal; `"…"` keeps `\"`, `\\`, `\$` and `` \` `` escapes; a word joins its quoted and
  unquoted pieces (`"r"m` is `rm`, `/"etc"` is `/etc`). The word also records whether its first character came
  from a quote, so `"~"` (no tilde expansion) can be told from `~`; both are treated as home, as today.
- **Backslash:** outside quotes it escapes the next character (`\/` is `/`, `\;` is the word `;`, not an
  operator); a backslash before a newline joins the lines (a continued command).
- **Operators**, only when unquoted and unescaped: newline, `;`, `&&`, `||`, `|`, `&`, `(`, `)`, `{`, `}`
  as words, `` ` `` and `$(` . Each ends the current command (a stage). `#` at the start of a word starts a
  comment to the end of the line.
- **Redirections:** a word that is or starts with `<`, `>`, `>>`, `2>`, `&>`, `>&`, `<<`, `<<<` (with an
  optional digit) is a redirection; its target is the rest of the word or, if the operator stands alone, the
  next word. Neither is an `rm` target, so `rm -rf build 2>/dev/null` is not read as removing `/dev/null`.
- **Limits that keep it linear:** each character is read once; each stage is read once (below). There is no
  regular expression with nested repetition. The input is at most a Markdown file the scanner already holds
  as a string.

### 4. Finding an `rm` and its arguments

In each stage, the first word that names `rm` starts the command: the word, after leading `(`, `{`, `!`, and
make's recipe prefixes `-`, `@`, `+` are dropped, is `rm` or ends in `/rm` (`\rm`, `/bin/rm`, `sudo rm`,
`xargs rm`, `git rm`, `find … -exec rm` all reach it). As today, `rm` anywhere in the stage counts, also as an
argument (`echo rm -rf /`); a gate errs toward refusal. Only the first `rm` word in a stage is read, so a stage
is read once: words after it are its arguments up to the end of the stage, which is also what the shell does
(`rm a rm -rf /` is one `rm` with five arguments).

The arguments, as GNU `rm` reads them (options may follow targets unless after `--`):

- Before `--`: a word starting with `-` (and not `-` alone) is an option. Recursive or forced: a short cluster
  holding `r`, `R` or `f` (`-rf`, `-Rv`, `-fr`), or `--recursive`, `--force`, or an unambiguous prefix of
  either that GNU accepts (`--rec`, `--for`), with or without `=…`. `--interactive=never`,
  `--no-preserve-root` and the like are options that are neither.
- `--` ends the options; every later word is a target, even one starting with `-` or a quote.
- `--cached` among the options before `--` makes it `git rm --cached` (it only untracks), as today: the
  command is skipped.
- Every other word is a target.

A command is reported when it has a recursive or forced option and any target is root or home: after the
tokenizer has removed quotes and escapes, it starts with `/`, `~` (any user: `~root`), `$HOME` or
`${HOME`. `/tmp` counts, as decided on 2026-10-15.

### 5. What it reports

`rm-rf-root`, BLOCK from prose and FLAG from code only, as today. The quoted line is the unit's text from the
`rm` word through the target that matched, cut at 80 characters, so the reviewer sees the target that made it.

## What stays out (limits, recorded in REFERENCE.md)

- A target the shell builds: a variable other than `HOME` (`rm -rf "$DIR"`, `${X:-/}`), a command
  substitution (`rm -rf $(echo /)`), brace expansion (`{/,x}`), a glob that does not start with `/` or `~`.
- `rm` reached through an alias, a function, `eval`, a heredoc fed to a shell, or `xargs` input.
- Shell scripts (`.sh` and the like): the script tables have no `rm` check today; adding one is decision D3.
- Systems where options must come first (BSD `rm` reads `rm / -rf` as three targets): GNU's reading is used,
  which errs toward a finding.

## Decisions for the owner

- **D1, prose:** read prose lines with the full tokenizer, or only up to the first plain word ("rm -rf to
  remove /tmp files" would otherwise read `/tmp` as a target). Recommendation: full tokenizer; the measurement
  found no prose line that would gain a finding. Revisit if the real-input check finds one.
- **D2, options after targets:** count them (GNU), as above. Recommendation: yes; a skill runs on the host's
  `rm`, which is GNU on Linux.
- **D3, scope:** Markdown only, as today's check, or also shell scripts. Recommendation: Markdown now; a script
  check is a separate change with its own real-input measurement, since scripts use `rm -rf "$TMP"` and
  absolute build paths far more than instructions do.
- **D4, targets the shell builds:** keep them out (above), or FLAG a recursive `rm` whose target holds `$`,
  `` ` `` or `$(` other than `$HOME`. Recommendation: out for now; a FLAG on every `rm -rf "$DIR"` would be
  noise in most skills.

## How it is checked

- **Tests first**, in `scripts/static-scan.test.js`: the S11 forms (each failing on main); every case of F2
  and F3 as must-not-match (a target on the next line, `2>&1`, `\;`, a quoted `;`, a redirection to `/dev/null`);
  prose and code severities; `git rm --cached`; every existing `rm-rf-root` test unchanged; a test that a command today's
  expression matches is reported once, with today's quoted line.
- **Timing:** the F1 inputs (`rm -rf "` repeated, `\rm -rf x`, `(rm -rf x)`), `rm` repeated, long unclosed
  quotes, long runs of `\`, `;`, `--` and `-r`, at 1 MB and 4 MB, against main.
- **Differential** (decision 2026-10-15): random Markdown with `rm` commands in prose, inline and fenced
  code; every main finding kept, compared on file, check, severity and quoted line; every new finding read.
- **Real inputs:** this repo's skills and agents, `reference-repositories/`, the installed skills and plugins
  (copied without secret files, names and checks printed only); CI's `ci-scan-skills.js` must stay clean.
- **Mutants:** of the tokenizer's quote, escape, operator, redirection and option rules.
- **Independent review** under `docs/REVIEW_PROTOCOL.md`, then a `skill-audit` deploy.
