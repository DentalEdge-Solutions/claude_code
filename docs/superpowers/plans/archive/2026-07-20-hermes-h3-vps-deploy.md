# Hermes H3 — VPS Deploy + Real Credentials Implementation Plan

> **⚠ SPLIT by the definitive roadmap.** VPS provision/deploy = **kernel K3** (dummy creds only); real
> credentials + staged rollout + security-review gate = deferred **Operate track**. Authoritative:
> `~/.claude/plans/iterative-squishing-church.md` and
> `.project-brain/decisions/candidates/2026-07-21-hermes-definitive-roadmap.md`.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to work through this plan. H3 is infrastructure/ops, so tasks are script-authoring + command-verified checkpoints rather than unit-test TDD. Steps use checkbox (`- [ ]`) syntax. **Do not introduce any real credential until Task 5's security-review gate is fully signed.**

**Goal:** Run the locally-hardened Hermes on the Hostinger VPS with real credentials, safely — provision + harden the box, deploy via git+compose, gate real creds behind a security review, and roll out smallest-blast-radius-first.

**Architecture:** Add a `deploy/` directory (provision, deploy, systemd unit, env template, review checklist). No changes to the run core — H3 ships what H0–H2 built.

**Tech Stack:** Bash provisioning on Ubuntu, Docker + compose (from H0/H0.5), SSH-key access. Node ≥22 already in the image.

**Spec:** `docs/superpowers/specs/2026-07-20-hermes-h3-vps-deploy-design.md` · **Master:** `docs/superpowers/specs/2026-07-20-hermes-master-architecture.md`

## Global Constraints

- Git repo is the source of truth; deploy = `git pull` + `docker compose build && up -d` on the box.
- `HERMES_VAULT_KEY` and all secrets: never in git, never in logs; key is root-only (`0600`), out of band.
- Inbound network = SSH only (key auth); no app port opened in v1.
- Real credentials only after the Task 5 security-review checklist is signed; capped/test accounts first.
- `hermes/state/` (vault + db) lives only on the box, gitignored, backed up encrypted.

---

### Task 1: VPS provisioning script (`deploy/provision.sh`)

Idempotent hardening — safe to re-run. Run once as root (or via `sudo`) on a fresh Ubuntu box.

**Files:**
- Create: `deploy/provision.sh`

- [ ] **Step 1: Write `deploy/provision.sh`**

```bash
#!/usr/bin/env bash
# deploy/provision.sh — idempotent Ubuntu hardening for the Hermes VPS.
# Usage (as root on the box):  DEPLOY_USER=hermes SSH_PUBKEY="ssh-ed25519 AAAA..." bash provision.sh
set -euo pipefail

DEPLOY_USER="${DEPLOY_USER:-hermes}"
: "${SSH_PUBKEY:?set SSH_PUBKEY to the deploy user's public key}"

echo "[provision] apt update + base packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y --no-install-recommends \
  ca-certificates curl git ufw fail2ban unattended-upgrades

echo "[provision] create non-root deploy user: ${DEPLOY_USER}"
if ! id "${DEPLOY_USER}" >/dev/null 2>&1; then
  adduser --disabled-password --gecos "" "${DEPLOY_USER}"
fi
install -d -m 700 -o "${DEPLOY_USER}" -g "${DEPLOY_USER}" "/home/${DEPLOY_USER}/.ssh"
echo "${SSH_PUBKEY}" > "/home/${DEPLOY_USER}/.ssh/authorized_keys"
chmod 600 "/home/${DEPLOY_USER}/.ssh/authorized_keys"
chown "${DEPLOY_USER}:${DEPLOY_USER}" "/home/${DEPLOY_USER}/.ssh/authorized_keys"

echo "[provision] SSH hardening (keys only, no root login)"
sed -i 's/^#\?PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config
sed -i 's/^#\?PermitRootLogin.*/PermitRootLogin no/' /etc/ssh/sshd_config
systemctl restart ssh || systemctl restart sshd

echo "[provision] firewall: default-deny inbound, allow SSH"
ufw --force reset
ufw default deny incoming
ufw default allow outgoing
ufw allow OpenSSH
ufw --force enable

echo "[provision] fail2ban + unattended upgrades"
systemctl enable --now fail2ban
dpkg-reconfigure -f noninteractive unattended-upgrades

echo "[provision] Docker engine + compose plugin"
if ! command -v docker >/dev/null 2>&1; then
  curl -fsSL https://get.docker.com | sh
fi
usermod -aG docker "${DEPLOY_USER}"

echo "[provision] DONE. Verify with: ufw status, fail2ban-client status, sshd -T | grep -E 'passwordauth|permitroot'"
```

- [ ] **Step 2: Make executable + syntax-check locally**

Run: `chmod +x deploy/provision.sh && bash -n deploy/provision.sh`
Expected: no output (syntax OK). (Do not run it locally — it hardens a host.)

- [ ] **Step 3: Run on the VPS and verify**

On the box (as root): `DEPLOY_USER=hermes SSH_PUBKEY="<key>" bash provision.sh`, then verify:
- `ufw status` → `Status: active`, only OpenSSH allowed.
- `fail2ban-client status` → sshd jail present.
- `sshd -T | grep -E 'passwordauthentication|permitrootlogin'` → `passwordauthentication no`, `permitrootlogin no`.
- Re-run `provision.sh` → completes cleanly (idempotent).

- [ ] **Step 4: Commit**

```bash
git add deploy/provision.sh
git commit -m "feat(hermes/deploy): idempotent VPS hardening script"
```

---

### Task 2: Deploy script + env template (`deploy/deploy.sh`, `deploy/env.example`)

**Files:**
- Create: `deploy/deploy.sh`
- Create: `deploy/env.example`

- [ ] **Step 1: Write `deploy/env.example`** (documents required env — NO values)

```bash
# deploy/env.example — copy to /etc/hermes/hermes.env on the box (root-owned, chmod 600).
# NEVER commit the real file. NEVER put real values here.

# Anthropic API key for the claude CLI engine.
ANTHROPIC_API_KEY=

# 32-byte base64 CSPRNG key for the credential vault. Generate once:
#   openssl rand -base64 32
# Store ONLY on the box (this file, 0600) and in your password manager.
HERMES_VAULT_KEY=
```

- [ ] **Step 2: Write `deploy/deploy.sh`** (run on the box as the deploy user)

```bash
#!/usr/bin/env bash
# deploy/deploy.sh — pull the source of truth and (re)deploy Hermes on the VPS.
# Usage (as the deploy user, from the repo checkout):  bash deploy/deploy.sh [git-ref]
set -euo pipefail

REF="${1:-main}"
ENV_FILE="/etc/hermes/hermes.env"
COMPOSE="hermes/docker-compose.yml"

[ -f "${ENV_FILE}" ] || { echo "missing ${ENV_FILE} (root-owned 0600) — see deploy/env.example"; exit 1; }

echo "[deploy] fetching ${REF}"
git fetch --all --tags
git checkout "${REF}"
git pull --ff-only origin "${REF}" || true
DEPLOYED_SHA="$(git rev-parse --short HEAD)"

echo "[deploy] build + up (sha ${DEPLOYED_SHA})"
docker compose --env-file "${ENV_FILE}" -f "${COMPOSE}" build
docker compose --env-file "${ENV_FILE}" -f "${COMPOSE}" up -d hermesd

echo "[deploy] health check"
sleep 3
if docker compose -f "${COMPOSE}" ps hermesd | grep -q "Up\|running"; then
  echo "[deploy] OK — hermesd running at ${DEPLOYED_SHA}"
else
  echo "[deploy] FAILED — hermesd not running; check: docker compose -f ${COMPOSE} logs hermesd"
  exit 1
fi
```

- [ ] **Step 3: Executable + syntax-check**

Run: `chmod +x deploy/deploy.sh && bash -n deploy/deploy.sh` → no output.

- [ ] **Step 4: Commit**

```bash
git add deploy/deploy.sh deploy/env.example
git commit -m "feat(hermes/deploy): git+compose deploy script with health check + env template"
```

---

### Task 3: Systemd unit + state volume + backups (`deploy/hermes.service`)

Ensure the daemon restarts on failure/reboot and that `hermes/state/` persists and is backed up.

**Files:**
- Create: `deploy/hermes.service`
- Create: `deploy/backup-state.sh`

- [ ] **Step 1: Write `deploy/hermes.service`** (optional to compose's `restart: unless-stopped`; use one)

```ini
[Unit]
Description=Hermes daemon (docker compose)
Requires=docker.service
After=docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=/home/hermes/claude_code
EnvironmentFile=/etc/hermes/hermes.env
ExecStart=/usr/bin/docker compose -f hermes/docker-compose.yml up -d hermesd
ExecStop=/usr/bin/docker compose -f hermes/docker-compose.yml down
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

- [ ] **Step 2: Write `deploy/backup-state.sh`**

```bash
#!/usr/bin/env bash
# deploy/backup-state.sh — encrypted backup of hermes/state (vault + db).
# Requires the vault master key holder; encrypts with a separate backup passphrase.
set -euo pipefail
SRC="hermes/state"
DEST="${HERMES_BACKUP_DIR:?set HERMES_BACKUP_DIR}"
STAMP="$(date +%Y%m%d-%H%M%S)"
tar -czf - "${SRC}" | openssl enc -aes-256-cbc -salt -pbkdf2 -out "${DEST}/hermes-state-${STAMP}.tar.gz.enc"
echo "[backup] wrote ${DEST}/hermes-state-${STAMP}.tar.gz.enc"
```

- [ ] **Step 3: Syntax-check + verify on the box**

`bash -n deploy/backup-state.sh`; on the box, install the unit (`systemctl enable --now hermes`),
confirm `systemctl status hermes` is active, reboot once, confirm `hermesd` comes back and the SQLite
queue survived.

- [ ] **Step 4: Commit**

```bash
git add deploy/hermes.service deploy/backup-state.sh
git commit -m "feat(hermes/deploy): systemd unit + encrypted state backup"
```

---

### Task 4: Deploy with DUMMY creds + full verification on the box

No real credentials yet. Prove the whole stack runs and every safety guarantee holds on the real host.

- [ ] **Step 1: Provision `/etc/hermes/hermes.env` with dummy values**

On the box (as root): create `/etc/hermes/hermes.env` (mode `0600`), set a real `ANTHROPIC_API_KEY`
and a freshly generated `HERMES_VAULT_KEY` (`openssl rand -base64 32`). Use **dummy** pack credentials
only.

- [ ] **Step 2: Deploy**

Run: `bash deploy/deploy.sh main` → `hermesd` reports running.

- [ ] **Step 3: Run the full test suite on the box**

Run (inside a one-off container): `docker compose -f hermes/docker-compose.yml run --rm hermes ../scripts/run-all-tests.js`
— or exec `node scripts/run-all-tests.js` in the app dir. Expected: all suites green on the box.

- [ ] **Step 4: Verify the safety guarantees with dummy creds**

- Wrong `HERMES_VAULT_KEY` → vault `get` fails closed (temporarily set a bad key, confirm, revert).
- A write-tier tool under `hitl` → denied + pending approval recorded.
- Over-cap money action (dummy binding cap) → denied.
- Staging write to a non-staging host → denied.
- `git check-ignore hermes/state/hermes.db` → ignored; `git log -p | grep -i HERMES_VAULT_KEY` → clean.

- [ ] **Step 5: Commit** (any doc/config tweaks discovered)

```bash
git add -A && git commit -m "chore(hermes/deploy): dummy-cred deploy verification notes" || echo "nothing to commit"
```

---

### Task 5: Security-review gate (`deploy/SECURITY-REVIEW.md`) — HARD GATE

**No real credential is added until every item is checked and human-signed.**

**Files:**
- Create: `deploy/SECURITY-REVIEW.md`

- [ ] **Step 1: Write `deploy/SECURITY-REVIEW.md`**

```markdown
# Hermes VPS Security Review — sign before ANY real credential

Deploy commit: __________   Reviewer: __________   Date: __________

- [ ] Non-root deploy user; root SSH disabled; SSH password auth disabled (`sshd -T`).
- [ ] UFW default-deny inbound, only OpenSSH allowed (`ufw status`).
- [ ] fail2ban active (`fail2ban-client status`); unattended-upgrades enabled.
- [ ] HERMES_VAULT_KEY: CSPRNG-generated; `/etc/hermes/hermes.env` is root-owned, mode 0600;
      key also stored in a password manager; NOT in git (`git log -p | grep -i vault_key` clean);
      NOT in container logs (`docker compose logs | grep -i vault_key` clean).
- [ ] hermes/state/ is on the box only, gitignored (`git check-ignore` confirms), backed up encrypted.
- [ ] Full test suite green on the box with dummy creds (Task 4).
- [ ] Negative tests on the box refused: production-target staging write; over-cap money action;
      write-tier without approval; wrong key.
- [ ] (Optional, on request only — may incur cost) `npx ecc-agentshield` / project-audit on the
      deployed .claude/ config: clean.
- [ ] Least-privilege real creds obtained: read-scoped where possible; Google Ads on a LOW-CAP TEST
      account first; WordPress pointed at a REAL STAGING site.
- [ ] Rollback plan confirmed: previous release commit noted; `deploy.sh <prev-ref>` tested once.

Signed: ______________________  (real credentials may now be added, one rollout step at a time)
```

- [ ] **Step 2: Complete and sign the review** (human) — do not proceed otherwise.

- [ ] **Step 3: Commit the (blank template) checklist**

```bash
git add deploy/SECURITY-REVIEW.md
git commit -m "docs(hermes/deploy): security-review gate checklist (pre-real-credential)"
```

---

### Task 6: Staged real-credential rollout (smallest blast radius first)

Only after Task 5 is signed. Each sub-step has a verify-before-next gate. Credentials are added with
`hermes vault set <name>` **on the box** (value via stdin), then the pack tier is enabled in the
box's `hermes/hermes.config.json`.

- [ ] **Step 1: Read-only real credential (Google Analytics)**

Vault-set the GA read credential; add the GA read-only pack target; run it; verify real output and
that no secret appears in the run artifact. **Gate:** output correct, artifact clean.

- [ ] **Step 2: WordPress staging (real staging site)**

Add the client binding (`packs/wordpress/clients/<client>/binding.json` with the real
`staging_site_url`); vault-set WordPress creds; enable `staging-autonomous`; run a staging write.
**Gate:** the write lands on staging; a deliberate production-target write is **refused**.

- [ ] **Step 3: Google Ads on a LOW-CAP TEST account**

Add the client binding with a low `max_daily_budget_usd`; vault-set Ads creds; enable `hitl`; run a
money action end to end: propose → `hermes approvals approve` → execute → ledger entry.
**Gate:** within-cap action executes and ledgers; an over-cap action is **denied**; new campaigns are
created paused (per the pack contract).

- [ ] **Step 4: Widen to real client accounts, one at a time**

For each client: add binding + vault creds; run one supervised action per tier; verify; only then
enable scheduled/autonomous runs for that client.

- [ ] **Step 5: Capture the milestone in the brain**

Run `brain-capture` to log "Hermes v1 live on VPS" as a candidate; leave promotion to `active`/`canon`
to a human `brain-promote --approve` (governance is human-gated).

---

## Definition of done (H3 = Hermes v1 complete)

- [ ] VPS hardened + idempotently reprovisionable; SSH-key-only; UFW + fail2ban + auto-upgrades on.
- [ ] `deploy.sh` deploys via git+compose; daemon restarts on failure/reboot; state survives.
- [ ] Full suite green on the box with dummy creds.
- [ ] Security-review checklist signed before any real credential.
- [ ] Read-only, staging-autonomous, and HITL money paths each verified end to end on the box,
      smallest blast radius first, with negative tests refused.
- [ ] Rollback + encrypted backup/restore exercised once.

## Out of scope / future (master D9)

LangChain retrieval, CrewAI multi-session coordination, a public HTTP/Slack channel, multi-VPS/HA —
each only on a measured need, via `scout → audit → adapt → eval`.
