# Skill Audit Reference

## SKILL-AUDIT.md Template

```markdown
# Skill Audit: <skill-name>
**Date:** YYYY-MM-DD  
**Source:** <GitHub URL or local path>  
**Verdict:** PASS | FLAG | BLOCK

## Static Scan Results

| Check | Severity | Detail |
|-------|----------|--------|
| ... | PASS | No issues |

## Permissions Audit

**Tools requested by skill:** (list from SKILL.md instructions)  
**Purpose stated:** (description field)  
**Mismatches:** none | <list>

## Provenance

| Attribute | Value | Flag? |
|-----------|-------|-------|
| Repo age | X days | yes/no |
| Stars | N | yes/no |
| Last commit | YYYY-MM-DD | yes/no |
| Contributors | N | yes/no |

## Diff from current version

(only if updating an installed skill — paste `diff` output here)

## Decision

**Verdict:** PASS / FLAG / BLOCK  
**Reason:** (one sentence)  
**Next step:** Proceed to skill-adapt | Awaiting user confirmation | Blocked
```

---

## Threat Patterns

### Which files are read

| File | Tables applied |
|------|----------------|
| `.md`, `.txt` | prompt injection, Bash in instructions, secrets |
| `settings.json`, `settings.local.json` | settings permissions, secrets |
| `.js` `.mjs` `.cjs` `.ts` `.tsx` / `.py` `.pyi` / `.sh` `.bash` | JS / Python / shell |
| Any other file starting with a shebang (`#!/bin/sh`, `#!/usr/bin/env node`, `#!/usr/bin/env -S node …`, `#!/usr/bin/python3.12`) | the table for its interpreter: node, deno, bun → JS; python, pypy → Python; sh, bash, zsh, dash, ksh, ash → shell |
| `.json` `.jsonc` `.json5` `.yaml` `.yml` `.toml` `.ini` `.cfg` `.conf` `.env` `.properties`, and `.env`, `.env.*`, `.npmrc`, `.pypirc`, `.netrc` | secrets |

The first row that matches wins, top to bottom, so a script named `.env.sh` is a shell script. A shebang file with a data extension (`run.conf`) is read for secrets only. Shebangs with an `env` option that takes an argument (`env -u FOO python3`) or other interpreters (`tsx`, `pythonw`, `uv run`) are not recognised. Script files (JS, Python, shell) are not read for the secrets table; Python has its own hardcoded-secret FLAG. In a single-file scan, each finding's `file` is the file's name.

### What the scanner cannot check

Content the scanner cannot fully check is a finding, never a silent PASS. Content it could not read at all is **BLOCK** (manual clearance): before, the scan crashed or hung there, or passed it unread. Content it read with a caveat is **FLAG**. These checks only add findings: every file is still read the way it always was, so a verdict is never lower than before. A `blocklist` entry in `skill-audit-policy.json` raises a FLAG check to BLOCK.

| Check | Severity | When | What happens |
|-------|----------|------|--------------|
| `unreadable` | BLOCK | a file or directory that cannot be read (permissions, I/O error) | the rest of the tree is still scanned |
| `special-file` | BLOCK | a FIFO, socket or device, or a symlink to one | never opened (a FIFO would hang the scan) |
| `file-too-large` | FLAG | a file too large to read whole (past about 536 MB, node's string limit) | scanned in 64 MB chunks that overlap by 1 MB, one finding per check; a match longer than the overlap can be missed |
| `symlink-outside-tree` | FLAG | a symlink whose target is outside the scanned directory, missing, or a loop | a file target is still scanned, under the link's name, and its matches are not quoted; a directory target is not walked |

A symlink to a file inside the tree is scanned under the link's name, since that is the name Claude Code loads it by (`SKILL.md` → `payload.png` is read as markdown). A symlink to a directory is never walked; the tree's own directories are walked in place. The path you name is followed if it is a symlink; if it is not a directory, it is scanned as a single file.

### Settings permissions (settings.json)

When the file is valid JSON, each row is matched two ways. The bare-name forms are matched against every `permissions.allow` rule, trimmed; a key that appears twice in one object (`permissions` or `allow`, escaped spellings included) is read in every copy, since parsers differ on which copy wins. The quoted forms (`"Bash(*)"`, `"*"` in an `allow` array, …) are matched against the raw text with the `permissions.deny` and `permissions.ask` arrays emptied, so a rule anywhere else in the file (`allowedTools`, a nested `allow`) is still reported. Deny and ask rules grant nothing and are not reported. When the file is not valid JSON, the rows are matched against the raw text, deny and ask lists included. Per the [permissions docs](https://code.claude.com/docs/en/permissions) (read 2026-10-16), a bare tool name matches every use of the tool: "`Bash(*)` is equivalent to `Bash`", and `:*` is another way to write a trailing wildcard.

| Allow rule | Severity |
|-----------|----------|
| `Bash`, `Write`, `Edit` bare, or with a specifier of only `*`, `:` and spaces (`Bash(*)`, `Bash(:*)`) | BLOCK |
| `Read` in the same forms | FLAG |
| `*` | BLOCK |
| `Write`/`Edit` on `/` or `/*` (the settings source's root), `~/…` (home) or `//…` (any absolute path) | FLAG |
| `defaultMode: "bypassPermissions"` (anywhere in the text) | BLOCK |
| a hook command with `$(…)` | FLAG |
| `enableAllProjectMcpServers: true` | FLAG |

### Secrets (everywhere a file is read for secrets, code blocks included)

Anthropic keys and tokens (`sk-ant-api03-…`, `sk-ant-admin01-…`, `sk-ant-oat01-…`), OpenAI keys (`sk-…`, `sk-proj-…`, `sk-svcacct-…`, `sk-admin-…`), GitHub tokens (`ghp_`, `gho_`, `ghs_`, `ghu_`, `ghr_`, `github_pat_`), AWS access key IDs, Slack bot tokens, private-key headers and Bearer tokens are BLOCK. A generic `api_key`/`password`/`secret`/`token` assignment is a FLAG only when the name sits right before `:` or `=` and the value is quoted (`password = "…"`). So a JSON key (`"password": "…"`), an unquoted `.env` value (`PASSWORD=…`) and an npm `_authToken` are not matched.

### Prompt Injection (in .md files)

| Pattern | Severity | Risk |
|---------|----------|------|
| `ignore [all/any [of]] [the/your/my] previous/prior/above/earlier/preceding/all/your instructions/directions` | BLOCK | Instruction override |
| `disregard` + instructions | BLOCK | Instruction override |
| `forget everything` | BLOCK | Memory wipe |
| Zero-width Unicode (U+200B, U+200C, U+200D, U+FEFF, U+202E) | BLOCK | Hidden text |
| `you are now` | FLAG | Persona hijack |
| `from now on you must/will` | FLAG | Behavior override |
| `act as` + assistant/ai/agent/claude | FLAG | Persona override |
| `system prompt` reference | FLAG | `System prompt manipulation` |
| Base64 blobs (80+ char) | FLAG | Encoded payload |
| HTML comments `<!-- -->` | FLAG | Hidden instructions |

### Dangerous JS/TS Operations

| Pattern | Severity |
|---------|----------|
| `eval()` / `new Function()` | BLOCK |
| `require`, `import … from` or `import()` of `child_process` (with or without `node:`) | BLOCK |
| `exec()` (child process, not a method like `re.exec()`) / `execSync()` | BLOCK |
| `spawn()` / `spawnSync()` / `execFile()` / `execFileSync()` | FLAG |
| `fetch()` / `require('http')` / `require('https')` | FLAG |
| `process.env` access | FLAG |
| `fs.writeFile/appendFile/unlink/rmdir/rm()` | FLAG |
| `.innerHTML =` | FLAG (XSS) |
| `dangerouslySetInnerHTML` | FLAG (React XSS) |
| `crypto.createCipher/createDecipher()` | FLAG (no IV) |
| `rejectUnauthorized: false` | FLAG (TLS disabled) |
| `NODE_TLS_REJECT_UNAUTHORIZED = 0` | FLAG (TLS disabled) |

### Dangerous Python Operations

| Pattern | Severity |
|---------|----------|
| `pickle.loads()` / `pickle.Unpickler()` | BLOCK |
| `cPickle/cloudpickle/dill.load()` | BLOCK |
| `marshal.loads()` | BLOCK |
| `joblib.load()` / `pandas.read_pickle()` | BLOCK |
| `numpy.load(..., allow_pickle=True)` | BLOCK |
| `os.system()` | BLOCK |
| `shell=True` anywhere inside a `subprocess.run/call/Popen/check_output/check_call(...)` call, nested calls included. A reader skips strings and `#` comments, so a `)` inside them does not end the call; the older regex (arguments up to the first `)`) also runs, so a string the reader misreads cannot hide a match. Not seen: an aliased module (`import subprocess as sp`), `from subprocess import run`, `**{"shell": True}`, a truthy value other than `True` (`shell=1`), a backslash line break after `shell=`, more than 64 spaces between the name and `(` | BLOCK |
| `shelve.open()` | FLAG |
| `yaml.load()` without `Loader=yaml.SafeLoader` | FLAG |
| `xml.etree.ElementTree.parse()` | FLAG (XXE) |
| `verify=False` / `ssl._create_unverified_context` | FLAG (TLS) |
| `check_hostname=False` | FLAG (TLS) |
| hardcoded `api_key/token/password/secret =` | FLAG |

### Dangerous Bash in Markdown Instructions

BLOCK rows are BLOCK in prose. When the command appears only in what the scanner reads as code (a ``` fenced block or an inline span), it is a FLAG instead: a documented example asks for confirmation rather than refusing the skill, and a fence-pairing trick can only lower a BLOCK to a FLAG, never hide the command (owner's decision, 2026-10-15). The scanner's code detection is a regex, not a markdown parser, so some prose can be read as code (escaped backticks, backticks inside HTML or link titles): such a command is a FLAG, not a BLOCK. Main gave those a PASS. FLAG rows apply to prose only. Secrets are matched everywhere in a markdown file, code included, at full severity. Prompt-injection rows apply to prose only.

| Pattern | Severity |
|---------|----------|
| `rm` with a recursive or force option (`-rf`, `-r -f`, `-Rf`, `-rfv`, `--recursive`, `--force`), whose first target is an absolute or home path (`/…`, `~…`, `$HOME…`), quoted or not, `/tmp` included; an option run holding `--cached` before any `--` (`git rm --cached`; plain `rm` refuses that option) is not matched | BLOCK |
| `curl ... \| bash` / `wget ... \| sh` (on one line) | BLOCK |
| `~/.ssh/` access | BLOCK |
| `~/.claude/settings` write | FLAG |
| `sudo` | FLAG |
| `chmod <mode>` | FLAG |
| WebFetch to unknown domains | FLAG |

### Dangerous Shell Script Operations

| Pattern | Severity |
|---------|----------|
| `eval "..."` | BLOCK |
| `curl ... \| bash` / `wget ... \| sh` (on one line) | BLOCK |
| `pip install --break-system-packages` | FLAG |

---

## Permissions Matrix

When auditing permissions, compare what the skill *requests* vs what its *purpose* requires:

| Skill type | Expected tools | Red flags |
|-----------|---------------|-----------|
| Research/analysis | Read, WebSearch, WebFetch | Bash with write ops, Edit |
| Code generation | Read, Edit, Write, Bash (tests only) | rm, chmod, WebFetch to unknown |
| Project management | Read, Bash (git read-only) | Write to ~/.claude/, curl pipes |
| Summarization | Read only | Any Bash, any WebFetch |

---

## Provenance Red Flags

- Repo created < 30 days ago
- 0 GitHub stars (for repos claiming wide adoption)
- Single commit with all files (no development history)
- Username typosquats known publishers (e.g., `anthropic-ai` vs `anthropics`)
- README describes different functionality than SKILL.md
