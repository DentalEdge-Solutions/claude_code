# Design 2026-10-21: S11, the `rm` check reads every target

Status: **not built.** The owner accepted S11 as a known limit on 2026-10-21, after design review round 2 (see
"Is it worth building?"). This revision 2 and the round-2 findings stay on record for a later revisit; skill-audit's
REFERENCE.md says the check reads the first target only and is a tripwire, not a boundary.

## Goal

`rm-rf-root` finds a recursive or forced `rm` of a root or home path wherever the path sits in the command,
and resists the cheap ways to hide one, without the faults that sank the last attempt:

1. The forms S11 records are found: `rm -rf ./build ~/`, `rm -rf x /`, `rm --interactive=never -rf /`,
   `rm / -rf`, and after `--` a first target that starts with `-` or a quote (`rm -rf -- --foo-rm ~`).
2. So are the evasions design review round 1 showed against revision 1 (listed under "How it is checked").
3. Every finding main makes today is still made, with the same severity and the same quoted line.
4. Scan time stays linear in the input, and within a stated budget (below).
5. No new false BLOCK across lines, or because of separators inside quotes or redirections.

No static check closes every way to build a command at run time; the limits are listed, and each is a test
pinned as a known limit.

## In plain language

skill-audit reads a skill's instructions before it is installed and refuses a skill that tells Claude to
delete the root or the home folder. Today it looks only at the first thing after `rm` and its options, so
`rm -rf ./build ~/` passes. The fix reads the command the way the shell would and checks every target. It is a
second detector beside today's, so nothing today's catches is lost.

## Where it stands

- **The check today** (static-scan.js:129, REFERENCE.md "Dangerous Bash"): one regular expression. `rm` after
  any non-word character, an option run holding a recursive or force option, then the first target must start
  with `/`, `~` or `$HOME` (quoted or not; `/tmp` counts). An option run holding `--cached` before any `--` is
  `git rm --cached` and is skipped. In prose a hit is BLOCK; a hit only inside code (fenced or inline) is FLAG
  (owner decision R2, 2026-10-15). `scripts/static-scan.test.js` names it 19 times.
- **The attempt that was dropped** (triage, "Final independent review", 2026-10-15): an every-target regex
  with a `/tmp` exemption. F1, a blocker: `rm -rf "` repeated took 5 s at 100 KB and over 20 s at 1 MB. F2: a
  target read across lines. F3: separators inside arguments (`2>&1`, `\;`, a quoted `;`) ended the list early.
  F4: the `/tmp` exemption trusted text. The owner chose the first-target rule with no `/tmp` exemption
  (active decision 2026-10-15); S11 recorded that a safe version needs a shell-aware tokenizer.
- **How often it matters on benign skills:** 3,016 Markdown files (this repo's skills and agents, the installed
  `~/.claude/skills` and `~/.claude/plugins`) hold 5,076 `rm` commands with `-r` or `-f` (author's rough count,
  2026-10-21). In 1 a later target is root or home and the first is not. The reviewer's prototype of revision 1
  on 3,029 files (with `reference-repositories/`) gave 0 new BLOCK and 1 new FLAG. The value is against a skill
  written to evade the check, which a gate for external skills has to assume.
- **Facts checked** (design review round 1, 2026-10-21): GNU coreutils "Common options"
  (gnu.org/software/coreutils/manual/html_node/Common-options.html): options and operands "can appear in any
  order", `POSIXLY_CORRECT` makes options come first, `--` ends the options, and long options take
  "unambiguous abbreviations"; glibc "Getopt Long Options"
  (sourceware.org/glibc/manual/latest/html_node/Getopt-Long-Options.html) agrees. GNU rm 9.11 in a scratch
  folder: `--r` is `--recursive`, `--f` is `--force`, `rm d --r` removes `d`, `--recursive=x` is refused.
  Bash 3.2: `"~"` does not expand; `$'\x2f'` is `/` and `$'\x72m'` is `rm`; a backslash-newline inside double
  quotes joins the lines; `{` and `}` are plain words out of command position; `>|` is a redirection; `RM` runs
  `/bin/rm` on macOS's case-insensitive file system.

## Design

### 1. A second detector, beside today's

Today's regular expression stays byte for byte and keeps reporting as it does. A new detector, also named
`rm-rf-root`, is a function in the Markdown Bash table: the script loop already takes a `find` function in
place of a regular expression, and the Markdown loop gains the same.

It reports every command it finds that today's expression does not: a hit is dropped only when today's
expression matches **that command's raw text** (its span in the string today scans, from the `rm` word to the
end of the command at that nesting level), so today's finding and quoted line stay exactly as they are, and a
second command in the same file is never hidden behind today's (the lesson of PR #167: V1, V9, V11). Each raw
span is tested once per nesting level, so this stays linear.

### 2. What it reads

The same prose/code split as today, so R2 holds, with three corrections:

- **Prose:** the text with fenced code removed, one line at a time, with inline code put back in place
  (markup stripped). A hit whose `rm` word and matched target are both in prose is BLOCK; a hit that uses inline
  code for either is FLAG, as a hit inside code is today (decision D6).
- **Code:** each fenced block, its info line included (```` ```rm -rf ./x ~``` ```` on one line is code), and
  each inline span. A hit found only here is FLAG.
- **Unit boundaries:** fenced blocks are found first; inline spans on the text with fences removed. `~~~` and
  indented blocks are read as prose, as today (F7). A unit is tokenized on its own, so an unclosed quote never
  runs past its line (prose) or block (code).

### 3. Normalizing before reading

Applied to the detector's copy of the text only, never to what today's expression reads:

- Unicode NFKC (a fullwidth slash or tilde becomes `/` or `~`), then invisible characters removed
  (`\p{Default_Ignorable_Code_Point}`: word joiner, soft hyphen, zero-width spaces), so `r` + word joiner + `m`
  is `rm`.
- Separators are JavaScript `\s`, which includes the no-break space; a lone `\r` is a separator; a backslash
  before `\n` or `\r\n` joins the lines.
- The `rm` word is matched without regard to case (`RM` runs `/bin/rm` on macOS).

### 4. The tokenizer

One left-to-right pass per unit and nesting level, no backtracking:

- **Quotes:** `'…'` is literal. `"…"` keeps `\"`, `\\`, `\$`, `` \` `` and backslash-newline (a continuation).
  `$'…'` decodes its escapes (`\xHH`, `\nnn`, `\uHHHH`, `\UHHHHHHHH`, `\'`, and the letter escapes); `$"…"` is
  read as `"…"`. A word joins its quoted and unquoted pieces (`"r"m` is `rm`).
- **Backslash** outside quotes escapes the next character (`\/` is `/`, `\;` is the word `;`).
- **Stage separators** (unquoted, unescaped): newline, `;`, `&&`, `||`, `|`, and in code also `&`, `(`, `)`,
  `` ` ``, `$(`, and `{` or `}` standing as a word in command position only. In prose only newline, `;`, `&&`,
  `||` and `|` separate (decision D1): prose punctuation such as `(and ~/)` or `&` must not end a command, and
  `#` starts a comment only in code.
- **Redirections** (code and prose): a word that is or starts with an optional digit and one of `<<<`, `<<`,
  `<>`, `<&`, `<`, `>>`, `>|`, `>&`, `>`, `&>>`, `&>`, read longest first and before `&` is read as a separator.
  Its target is the rest of the word or, if the operator stands alone, the next word in the same stage, never
  a word across a separator. Neither is an `rm` target.
- **Quoted commands:** the decoded text of every quoted piece is tokenized again as a unit of its own, because
  `sh -c '…'`, `bash -c "…"`, `eval "…"`, `ssh host '…'` and `find … -exec sh -c '…'` run it. Down to eight
  levels (decision D7); a piece at level eight that still holds `rm` is FLAG. Each deeper level is a disjoint
  substring of the level above, so the cost is at most nine readings of the unit.

### 5. Finding each `rm` and its arguments

**The `rm` word:** as today, `rm` is found inside a word when no letter, digit or `_` comes right before it and
none right after (`(rm`, `**rm`, `<code>rm`, `[rm`, `\rm`, `/bin/rm`, make's `-rm` and `@rm` all count), without
regard to case. Make's `$(RM)` and `${RM}` count too. As today, `rm` anywhere in a stage counts, as an argument
too (`echo rm -rf /`); a gate errs toward refusal.

**Every `rm` word starts its own reading** (review D-R1: a dummy `rm` or `--cached` earlier in the stage must
not switch off a later one). One right-to-left pass over a stage's words records, for each position, whether a
later word is root or home, whether a recursive or force option comes before the next `--`, and whether
`--cached` does. An option word can never be root or home, so options and targets need no telling apart for
the first question. Each `rm` word then reads its answer in constant time.

**The arguments**, as GNU `rm` reads them (decision D2: options may follow targets unless after `--`; BSD reads
`rm / -rf` as three targets, so this errs toward a finding):

- Before `--`, recursive or forced is: a short-option word made only of rm's letters (GNU `dfirvIR`, BSD adds
  `PWx`) holding `r`, `R` or `f` (`-rf`, `-Rv`, `-fr`; find's `-prune` is not one), or `--recursive`, `--force`,
  or any prefix of either down to `--r` and `--f`. GNU refuses `--recursive=x`; it is still counted, which only
  over-reports.
- `--cached` before `--` makes the reading `git rm --cached` (it only untracks), as today: no finding.
- Root or home: after quotes, escapes and normalization, the word starts with `/`, `~` (any form: `~root`,
  `~+`, `~-`, which over-reports), or `$HOME`/`${HOME` followed by a character that cannot continue a name
  (review D-R7: `$HOMEBREW_PREFIX` is not home). Leading Markdown markup (`*`, `_`, `[`, `(`, `<`, a tag such as
  `<code>`) is skipped first. `/tmp` counts, as decided on 2026-10-15.

### 6. What it reports

`rm-rf-root`, BLOCK or FLAG as section 2 says. The quoted line is the `rm` word, `…`, and the target that
matched (each cut to 40 characters), so the reviewer always sees the target; a hit from a nested level says
which level, since its text is decoded and may not appear as such in the file.

## What stays out (limits, each a test, recorded in REFERENCE.md)

- A target the shell builds: a variable other than `HOME` (`rm -rf "$DIR"`, `${X:-/}`), a command substitution
  (`rm -rf $(echo /)`), brace expansion (`{/,x}`), a glob that does not start with `/` or `~`, an HTML entity
  (`&#126;`).
- A command word the shell builds: `{rm,-rf,./x,~}`, `rm${IFS}-rf` (decision D4).
- A root reached otherwise: `cd ~ && rm -rf ./x *` or a bare `cd`, relative climbing (`../../../../*`),
  `find ~ -delete`, `find ~ -exec rm -rf {} +` (the root is find's argument, not rm's).
- `rm` reached through an alias, a function or `xargs` input. Heredoc bodies are read as code (a hit is FLAG).
- Shell scripts (`.sh` and the like): the script tables have no `rm` check today (decision D3).
- A file over about 536 MB, scanned in chunks: a detector finding from an earlier chunk can take the place of
  today's line from a later chunk in the one-finding-per-check reduction (the V13 limit, accepted 2026-10-21).
- CI's baseline keys on skill, file and check: a baselined `rm-rf-root` BLOCK would also cover a new one in the
  same file. The baseline holds none today.

## Decisions for the owner

Recommendations first; review round 1 agreed with D2 to D4 and proposed D5 to D9.

- **D1, prose separators:** only newline, `;`, `&&`, `||`, `|`; no comments, parentheses, braces, backticks or
  `&` in prose. (Revision 1 used the full shell reading, which let prose punctuation hide a target.)
- **D2, options after targets:** count them, GNU's way.
- **D3, scope:** Markdown only; a script check is a separate change with its own measurement.
- **D4, words the shell builds:** targets stay out. A narrow FLAG for a command word built by brace expansion
  or `${IFS}`: recommended no for now (listed as a limit), since it adds a second parser for little benefit.
- **D5, a soft wrap in prose:** the detector does not join prose lines (a target on the next line of a
  paragraph is too often prose, the F2 fault); today's expression still finds a first target after a wrap (G1).
- **D6, a hit that mixes prose and inline code:** FLAG. The reviewer measured 34 such prose lines in 3,029
  files, mostly one skill's list of `rm -rf node_modules` / `.next` / … items, where `/` is a separator word;
  they must not become BLOCKs.
- **D7, nesting:** eight levels, and FLAG when a piece at the eighth still holds `rm`.
- **D8, case and Unicode:** match the `rm` word without regard to case; NFKC and invisible characters removed
  before reading.
- **D9, suppression:** per command, on that command's raw span (section 1), not once per file.

## How it is checked

- **Tests first**, in `scripts/static-scan.test.js`, each failing on main where it is a new finding:
  - the S11 forms, and `--r`/`--f`;
  - every evasion of review round 1: a dummy `rm` or `--cached` first in the stage
    (`find … -name rm -o -name -- -o -exec rm -rf ./x ~ \;`), three nested `sh -c` levels, `**rm**`,
    `<code>rm …</code>`, `[rm …](…)`, a target in inline code, `(and ~/)` and `& ~/` in prose, a `#` heading,
    continuations in `~~~` and indented blocks, `$'/'`, `$'\x2f'`, `$'\x72m'`, `rm -rf ./x } ~`,
    `>|/tmp/log ~`, no-break spaces, `RM`, a word joiner or soft hyphen inside `rm`, a fullwidth slash or tilde,
    `$(RM)`;
  - must-not-match: F2 and F3 (a target on the next line, `2>&1`, `\;`, a quoted `;`, a redirection to
    `/dev/null`), `$HOMEBREW_PREFIX/y`, `"${HOMEBREW_CACHE}"`, find's `-prune`, `git rm --cached`;
  - severities (prose BLOCK, code and mixed FLAG, nesting cap FLAG); every limit above pinned as a known limit;
  - a command today's expression matches is reported once, with today's quoted line; two commands in one file,
    one today's, one new, are both reported;
  - the coverage test: the detector's case carries a `tag` (it shares `md:rm-rf-root:BLOCK` with today's entry)
    and uses a form today's expression misses; removing the detector must fail the suite;
  - REFERENCE.md's `rm` row no longer says "first target".
- **Timing budget** (goal 4): linear on every input, and at 1 MB the detector at most 10 times main's
  expression and under 100 ms; at 4 MB under 400 ms. Inputs: the F1 set (`rm -rf "` repeated, `\rm -rf x`,
  `(rm -rf x)`), `rm` repeated, long unclosed quotes, long runs of `\`, `;`, `--`, `-r`, `$'`, nested quotes to
  the cap, and inline spans. The prototype of revision 1 took 30–60 ms at 1 MB and 110–220 ms at 4 MB, against
  about 7 ms for main's expression at 1 MB.
- **Differential** (decision 2026-10-15): random Markdown that includes every construct above, with the
  generator written by the reviewer, not the author (the V11 lesson: the author's generator was blind to a
  shape); every main finding kept, compared on file, check, severity and quoted line; every new finding read.
- **Real inputs:** this repo's skills and agents, `reference-repositories/`, the installed skills and plugins
  (copied without secret files, names and checks printed only); CI's `ci-scan-skills.js` must stay clean.
- **Mutants** of the quote, escape, `$'…'`, operator, redirection, normalization, option and suppression rules,
  and of the right-to-left pass.
- **Independent review** under `docs/REVIEW_PROTOCOL.md`, then a `skill-audit` deploy.

## Design review round 2 (2026-10-21): request changes

Revision 2 closes D-R1, D-R3 to D-R5, D-R7 and D-R9 to D-R13 in the design; D-R2, D-R6 and D-R8 only in part.
New findings, with the fix each would take in revision 3:

- **D-R14, blocker:** each `rm` word starts its own reading and its own report, so the readings overlap:
  `rm ` repeated 16,000 times (47 KB) took 1.4 s and gave 16,000 findings; at 1 MB, minutes and about 350,000.
  Fix: at most one finding per stage, a cap per file, and suppression keyed to the exact position of the `rm`
  word today's expression reports (one comparison per stage), never a regular expression run per span.
- **D-R15, major:** suppression must read the original text. Seven forms (a word joiner or soft hyphen inside
  `rm`, a fullwidth slash, tilde or `rm`, `$'r\x6d -rf ~'`, a continuation inside `sh -c "…"`) match today's
  expression only after normalizing or decoding; read on the detector's copy, each would be suppressed and
  pass. Fix: the position-keyed suppression above, with offsets carried through normalization and decoding.
- **D-R16, major:** stripping Markdown before reading turns `**/node_modules` and `*/` into root targets and
  `<dir>/x` into `/x`. Fix: strip in prose only, a closed list of inline tags, paired emphasis only, never a `*`
  or `_` before `/`.
- **D-R17, minor:** "10 times main's expression" cannot be met on inputs with no `rm`, and nine nesting levels
  cost 266 ms at 1 MB and 975 ms at 4 MB in the prototype. Fix: absolute bounds on the whole scan, and re-read
  a quoted piece only when it could hold `rm`.
- **D-R18, minor:** nine levels cost about 1 KB and lower a BLOCK to a FLAG; `$'\x72m'` at the cap is missed.
  Fix: FLAG at the cap on `rm` in any case, `$'` or a backslash; list "deeper than 8" as a limit.
- **D-R19, minor:** the right-to-left pass must keep a root word in prose apart from one in inline code; two
  more ways to lower a BLOCK to a FLAG go in the limits.
- **D-R20, nit:** a lone `\r`, U+2028 and U+2029 are line ends; "command position" for `{` and `}` is after a
  separator, `!`, `then`, `do`, `else` or `elif`.

## Is it worth building?

Each review round has closed one more way to spell a command, and the design has grown into a normalizing,
quote-decoding, nesting-aware tokenizer with offset mapping. The easiest evasion stays open by design: a target
built from a variable (`X=~; rm -rf ./a "$X"`) is out of scope, because a FLAG on every `rm -rf "$DIR"` would
bury the reviewer. So against an author who sets out to evade, the check stays a tripwire, and against a careless
one the measured benefit is 1 command in 5,076. The options:

1. **Build revision 3** as above: the cheap textual evasions closed, the variable path open; a sizeable parser
   to maintain, with the risk of new faults of the F1 kind, mitigated by the timing budget and review.
2. **Accept S11 as a known limit:** record in REFERENCE.md that `rm-rf-root` reads the first target only and is
   a tripwire, not a boundary, and that a skill is cleared by reading it; no code change.
3. **A narrow version:** only the multi-target, options-after-targets and `--` forms (goal 1), with the plain
   tokenizer of revision 1, one finding per stage, and every evasion of reviews 1 and 2 listed as a limit.
   It catches a careless multi-target command, not a determined author.
