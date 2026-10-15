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
| `subprocess.run/Popen(..., shell=True)` | BLOCK |
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
