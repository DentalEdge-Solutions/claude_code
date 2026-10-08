# VPS Bring-Up: From a Bought Box to Docker-Ready

> **For provisioning an Ubuntu 24.04 box on Hostinger KVM 2 and running the systemd units
> listed in the README at line 957.** This runbook covers phases 0–4 (buying and hardening
> the host, the on-box layout these units require, `.env`, and the compose build); Phase 5
> then hands off to the README sequence, and Phase 6 confirms the bind agreement once the
> README steps have run. Phase 7 covers reaching the dashboard from a laptop.

Spec: `docs/superpowers/specs/2026-09-18-vps-provisioning-and-bring-up-design.md`
First real run (2026-09-21), and every correction below that it earned:
`docs/superpowers/specs/2026-09-21-vps-first-bring-up-findings.md`

> **Pasting output off the box (F21 policy).** Journal, broker and pre-flight output can name
> real clients. Before pasting any of it into a chat, PR, doc or handoff, replace every real
> client slug with `<client>`. `RESULT` blocks use scratch slugs only. See README "Client names
> and the journal".

**Every command is labelled by where it runs.** Read the prompt before pasting:
`you@laptop` is the laptop, `root@<host>` / `hermesops@<host>` is the VPS. On the first run a
laptop command was pasted into the VPS web console and the VPS tried to SSH into itself.

---

## Phase 0: Buy the Box

1. On Hostinger, provision a **KVM 2 VPS**:
   - 2 vCPU
   - 8 GB RAM
   - 100 GB NVMe
   - OS: Ubuntu 24.04 LTS
   - Template: **Plain OS, not Docker-preinstalled** (we pin deliberately)

   **Sizing rationale (measured 2026-09-18):** the amd64 base image is 33 layers / 0.95 GB
   compressed, so budget ~10 GB for Docker alone; 8 GB RAM because the gateway spawns
   `claude -p` executor subprocesses and one-shot mutator containers.

2. Generate a keypair locally:
   ```bash
   ssh-keygen -t ed25519 -f ~/.ssh/vps-hermes -C "hermes deploy key"
   ```
   Copy the public key (`~/.ssh/vps-hermes.pub`) — you will use it in phase 1.

3. Note the box's IP address from the Hostinger console. You will use it as `<ip>` in the
   commands below.

4. **Authorize the key for root** — nothing above does this, and phase 1 needs it. Either add
   `~/.ssh/vps-hermes.pub` in hPanel's SSH-keys settings, or append it to
   `/root/.ssh/authorized_keys` from Hostinger's **browser terminal** (which does not use SSH).
   Then prove it, **laptop**:
   ```bash
   ssh -i ~/.ssh/vps-hermes -o IdentitiesOnly=yes -o ConnectTimeout=10 root@<ip> 'echo KEY_LOGIN_OK; lsb_release -ds; uname -m'
   ```
   Expect `KEY_LOGIN_OK`, `Ubuntu 24.04.x LTS`, `x86_64`. On first connect, compare the host
   fingerprint against `ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub` run in the browser
   terminal before accepting it.

   **Do not add `-o BatchMode=yes` to this test.** A passphrase-protected key cannot be
   unlocked in batch mode, and ssh reports that as `Permission denied (publickey,password)` —
   indistinguishable from a key the server rejected. On the first run this cost a full
   diagnosis round. Run `ssh-add ~/.ssh/vps-hermes` once per laptop session instead.

---

## Phase 1: Harden

The script `provision.sh` (in this directory) hardens the box to a state where:
- A non-root deploy user can log in via SSH key only
- Root login and password auth are disabled
- The firewall is active (inbound SSH only, default-deny)
- fail2ban is running
- Unattended security upgrades are enabled
- Docker Engine is installed

### Step 1a: Copy the script

**Laptop**, from the repo root:

```bash
scp -i ~/.ssh/vps-hermes infra/hermes-agent/deploy/provision.sh root@<ip>:~/
```

### Step 1b: Run as root

First open a root session and **keep it open** — a root SSH session from the laptop, or the
Hostinger browser terminal (better: it does not depend on sshd at all). If SSH hardening goes
wrong, that session is your recovery path.

Then, from a **second laptop terminal**:

```bash
ssh -i ~/.ssh/vps-hermes root@<ip> "DEPLOY_USER=hermesops SSH_PUBKEY='$(cat ~/.ssh/vps-hermes.pub)' bash ~/provision.sh" 2>&1 | tee ~/provision-run.log
```

The laptop substitutes `$(cat ...)` before sending, so the key is never hand-pasted (and the
script refuses a truncated key before it disables password login). `tee` swallows the exit
status — apply mode prints nothing after `docker installed`, so a clean tail is consistent with
success but does not prove it; step 1c does.

**Expected on a fresh box:** apt prints several `Waiting for cache lock ... held by process N
(unattended-upgr)` lines. The box's own first-boot security upgrade holds the dpkg lock; apt
waits and continues. It is not a failure.

### Step 1b-2: Give the deploy user a sudo password

`provision.sh` creates `hermesops` with `adduser --disabled-password` and adds it to `sudo`,
but sets no password and no `NOPASSWD` rule — so **as provisioned, `hermesops` cannot use
sudo at all**. `--check` does not catch this: "is in the sudo group" is membership, not
usability. Close the root session before this step and the only way back to root is the
browser terminal.

In the **root session**:

```bash
passwd hermesops
```

Generate the value in a password manager; the prompt echoes nothing. This does not re-enable
password SSH (`PasswordAuthentication no` still holds) — it is a second factor behind the key.
Passwordless sudo was rejected: it would make the private key alone sufficient for root.

### Step 1c: Verify the hardening worked

Still in the root session:

```bash
bash ~/provision.sh --check
```

You should see:
```
[provision] deploy user: hermesops (mode: check)
  OK    user hermesops exists
  OK    hermesops is in the sudo group
  OK    hermesops is not in the docker group
  OK    authorized_keys present and non-empty
  OK    authorized_keys mode is 600
  OK    authorized_keys owned by hermesops
  OK    unattended security upgrades enabled
  OK    sshd: PasswordAuthentication no
  OK    sshd: PermitRootLogin no
  OK    sshd: KbdInteractiveAuthentication no
  OK    sshd: PubkeyAuthentication yes
  OK    firewall active
  OK    default incoming policy is deny
  OK    no inbound rule beyond SSH
  OK    fail2ban running
  OK    docker running
  OK    docker group has no members beyond hermes-docker-proxy
[provision] all checks passed (17 checks)
```

(The check count is what the script reports, so do not "correct" it from a manual count — if
you want to verify, run the script against mocks rather than counting by eye.)

### Step 1d: Lockout protocol (SSH hardening is dangerous)

1. **Keep the root session open.** Do not close it.
2. In a **second laptop terminal**, prove key login as `hermesops`, and prove root login is
   actually refused (the control — `--check` reading `PermitRootLogin no` is not the same as
   sshd enforcing it):
   ```bash
   ssh -i ~/.ssh/vps-hermes hermesops@<ip> 'id'
   ssh -i ~/.ssh/vps-hermes -o BatchMode=yes root@<ip> true; echo "ROOT_LOGIN_EXIT=$?"
   ```
   Expect `uid=1000(hermesops) gid=1000(hermesops) groups=1000(hermesops),27(sudo),100(users)`
   on a fresh box (measured 2026-09-21), then `Permission denied (publickey)` and
   `ROOT_LOGIN_EXIT=255`.

3. Prove `sudo` works as `hermesops` — `-t` so sudo can prompt for the step 1b-2 password:
   ```bash
   ssh -t -i ~/.ssh/vps-hermes hermesops@<ip> 'sudo -v && echo SUDO_OK'
   ```
   Expect `SUDO_OK`. `sudo: a password is required` here means step 1b-2 was skipped.

4. **Only then** close the root session. If you get locked out after this, skip to recovery
   below.

5. **If you are locked out:** Hostinger's browser console (VPS → Overview → Browser terminal)
   does not use SSH, so you can still reach the box. Log in as root there and reconcile the
   issue.

### Step 1e: Verify the gid-10000 precondition (before README "VPS deploy sequence" runs)

SSH in as `hermesops` and check:

```bash
getent group hermes    # expect: empty, or a group at gid 10000
getent group docker    # expect: no members yet
```

If `getent group hermes` returns a line with a gid other than 10000, stop here. That is
design spec §2.1 — a name collision that will silently break the executor's access to the
governance store. Reconcile deliberately before proceeding.

---

## Phase 2: Lay Out the Box

The systemd units at lines noted below dictate this layout. It is not free-choice.

| Path | Holds | Required by |
|---|---|---|
| `/opt/projects/claude_code` | this repo | so compose's `../../../claude-google-ads` resolves to `/opt/projects/claude-google-ads` |
| `/opt/projects/claude-google-ads` | the ads repo | `hermes-docker-proxy.service:36` |
| `/opt/hermes-agent` | `bin/`, `registry/` | `hermes-broker.service:18,33,35,37`; `hermes-docker-proxy.service:26,37,38` |
| `/var/lib/hermes/governance` | the governance store | `hermes-broker.service:21,22,34,36,44`; `hermes-docker-proxy.service:32-35` |
| `/var/lib/hermes/spool` | the request spool | `hermes-broker.service` (`HERMES_SPOOL_ROOT`, `ReadWritePaths`); `docker-compose.yml` (`HERMES_SPOOL_DIR`) |

In a `hermesops@<host>` session:

```bash
sudo mkdir -p /opt/projects /var/lib/hermes
# claude_code is public — no credential on the box for it
sudo git clone https://github.com/DentalEdge-Solutions/claude_code.git /opt/projects/claude_code
sudo ln -s /opt/projects/claude_code/infra/hermes-agent /opt/hermes-agent
sudo install -d -m 755 -o root -g root /var/lib/hermes
# the store and the spool under it are created by README "VPS deploy sequence" step 2
# verify
sudo git -C /opt/projects/claude_code log -1 --oneline     # must equal origin/main
readlink -f /opt/hermes-agent                               # /opt/projects/claude_code/infra/hermes-agent
sudo stat -c '%a %U:%G %n' /var/lib/hermes                  # 755 root:root
```

**Do not `mkdir /opt/hermes-agent` before the `ln -s`.** An earlier version of this runbook did.
When the link path already exists as a directory, `ln -s` puts the link *inside* it
(`/opt/hermes-agent/hermes-agent`) and the layout is silently wrong.

**Copy is not an alternative to the symlink.** Compose resolves the symlink (measured, phase
5), so from the symlink `../../../claude-google-ads` lands at `/opt/projects/claude-google-ads`.
From a real directory at `/opt/hermes-agent` the same path resolves to `/claude-google-ads`.

### The ads repo

`claude-google-ads` is **private**, and its tracked files include account-level audit
reports. Two options:

- **Placeholder** (used on the first run, until after the security review). No GitHub
  credential and no client-adjacent data on the box. The compose bind paths still exist:
  ```bash
  sudo install -d -m 755 /opt/projects/claude-google-ads
  echo "PLACEHOLDER: real repo deferred until after the security review" | sudo tee /opt/projects/claude-google-ads/PLACEHOLDER >/dev/null
  sudo install -m 600 /dev/null /opt/projects/claude-google-ads/.env
  ```
- **App package** (after the security review — spec 2026-09-28 §6, decision 3): no clone and
  no GitHub key on the box; build on the laptop with `bin/build-app-package.py`, install with
  `sudo bin/install-app-package.py`.

**The empty `.env` is required either way.** `docker-compose.yml:70` binds a mask file *onto*
`/projects/claude_google_ads/.env` inside a `:ro` mount, and the mountpoint has to exist.
`.env` is gitignored, so a fresh clone does not have one either; the laptop never hit this
because a real `.env` is present there. (This is a prediction from the mount layout — the
first run created the file before `up`, so the failure itself was not observed.)

---

## Phase 3: `.env`

Phase 2 created `/opt/hermes-agent` and `/opt/projects/...` under `sudo`, so these directories
are root-owned. That is correct: `sudo docker compose` reads the files as root, and deploy
commands run under `sudo` (the deploy user is deliberately not in the `docker` group).

Copy the example to `.env` at mode 600 and set the dummy key. `.env.example` already sets
`HERMES_GOVERNANCE_DIR`, `HERMES_SPOOL_DIR`, `HERMES_AGENT_DIR` and `HERMES_ADS_REPO_DIR` to
the box's paths.

```bash
sudo install -m 600 /opt/hermes-agent/.env.example /opt/hermes-agent/.env
sudo sed -i 's/^ANTHROPIC_API_KEY=$/ANTHROPIC_API_KEY=dummy-key-this-wave/' /opt/hermes-agent/.env
# verify — key NAMES only, never values
sudo grep -Ev '^\s*(#|$)' /opt/hermes-agent/.env | cut -d= -f1       # ANTHROPIC_API_KEY, HERMES_GOVERNANCE_DIR, HERMES_SPOOL_DIR, HERMES_AGENT_DIR, HERMES_ADS_REPO_DIR
sudo grep -c '^ANTHROPIC_API_KEY=dummy-key-this-wave$' /opt/hermes-agent/.env   # 1 — sed is silent on a non-match
sudo git -C /opt/projects/claude_code status --short                  # empty — .env is gitignored
```

Two prohibitions:

- **Never run `docker compose config`** — it renders `env_file` secrets in cleartext to stdout.
- **No real client credentials this wave.** Use dummy values. Real money-spending credentials
  are gated behind a security review that is downstream of this runbook.

---

## Phase 4: Build, Measure, Then Start

**Measure the binds before anything starts.** An earlier version ran `up` here and measured in
the old phase 5 — the wrong order: if compose had resolved paths from the symlink lexically, the
gateway's `../..` mount would have been the host root, and `up` would have started a container
with it. `create` builds containers without running them, and `inspect` shows only paths (this
is not `docker compose config`; no secret is rendered).

```bash
cd /opt/hermes-agent && sudo docker compose build; echo "BUILD_EXIT=$?"
sudo docker compose create hermes-agent
sudo docker inspect $(sudo docker compose ps -a -q hermes-agent) --format '{{range .HostConfig.Binds}}{{println .}}{{end}}'
sudo docker compose down
```

Every source must be under `/opt/projects/`, with **one** expected exception: the spool,
`/var/lib/hermes/spool:/opt/data/spool` (from `HERMES_SPOOL_DIR`, F10). Measured 2026-09-21,
before the spool bind existed — identical from `/opt/hermes-agent` and from the physical path,
i.e. compose **resolves** the symlink:
`/opt/projects/claude_code:/projects/claude_code:ro`,
`/opt/projects/claude-google-ads:/projects/claude_google_ads:ro`,
`/opt/projects/claude_code/infra/hermes-agent/{bin,registry,data,skills/...,masks/empty}`.
Any source of `/`, or outside `/opt/projects/` other than `/var/lib/hermes/spool`, is a stop.

**The `up` below makes Docker create `/var/lib/hermes/spool` as `755 root:root`,** because
README "VPS deploy sequence" step 2 has not laid it out yet. That is expected, and wrong:
`init-host-layout.py --apply` refuses it. README step 2 takes the gateway down, removes the
Docker-created directory, lays out the real spool, and brings the gateway back up so it mounts
that spool.

**`data/` must belong to uid 10000 before `up`.** It is gitignored, so it does not exist on a
fresh clone; Docker creates missing bind sources as root at *start* (not at `create`), and the
container runs as `USER hermes` (uid 10000). macOS hides this — Docker Desktop remaps
ownership.

```bash
[ "$(sudo ls -A data 2>/dev/null | wc -l)" -eq 0 ] && sudo install -d -o 10000 -g 10000 -m 700 data
sudo install -o 10000 -g 10000 -m 640 config.yaml.example data/config.yaml
sudo docker compose up -d; echo "UP_EXIT=$?"
sleep 20; sudo docker compose ps -a
sudo docker compose exec hermes-agent hermes gateway status    # ✓ Gateway is running
sudo docker compose exec hermes-agent claude --version         # 2.1.278 (Claude Code) on 2026-09-21
sudo ss -tlnH                                                  # public: :22 only
```

`claude-auth-init` should be `Exited (0)`. The gateway warnings "No env user allowlists
configured" and "No messaging platforms enabled" are expected with no platform configured.

**Use `ss`, not `ufw`, to check exposure.** Docker publishes ports through its own iptables
chains, which bypass ufw — `provision.sh --check`'s "no inbound rule beyond SSH" cannot see a
container port. `127.0.0.1:9119` (the dashboard port-map) is the only non-SSH listener expected.

**Known, not yet fixed:** `data/skills` ends up `755 root:root`, because compose mounts four
skills *inside* it and Docker creates the parent as root. The gateway then logs
`Permission denied: '/opt/data/skills/github'` while seeding bundled skills. Non-blocking;
tracked in the findings record.

---

## Phase 5: Hand Off

**Not blocked.** Installing and verifying the units creates no container: the proxy only opens
its socket at start, the broker's `ExecStartPre` checks make no Docker call, and the
`curl …/version` probe is on the proxy's allow-list (F9 spec §3.1). The store and spool layout
(F10) is landed, and README step 1 (users and groups) was run and verified on 2026-09-21.

Hand off to:

1. README "VPS deploy sequence" steps 1–5 (create the Hermes users and groups, install the
   systemd units, run the preflight checks)
2. `docs/superpowers/handoffs/2026-09-17-vps-deploy-and-remeasurement.md` §2–§5 (the 2026-09-17
   handoff sequence)

**Note:** This runbook does not create the kill switch, and mutation stays disabled throughout.
The handoff's §6 gates (F3 hardening, `UMask=0077`, audit-log truncation) are all closed: §6
part A in PR #48, §6 part B in PR #57 (applied to the box 2026-09-25). What remains before the
kill switch is the rehearsal gate below, then the operator's own decision.

---

## Phase 6: Confirm the Bind Agreement

**Run this only after README "VPS deploy sequence" steps 2–5**: the store exists, both units
run, and the kill switch is **absent**. CI already proved the agreement on Linux (the
`bind-agreement` job). This confirms it on the box's own Compose version and real image, on
the broker's real path: as `hermes-broker`, through the proxy socket, with the broker unit's
environment and `--env-file /dev/null`. The ids are dummies. The executor checks the kill
switch before it reads anything else, so this cannot touch an account.

**Why not just run `run-ads-mutate.sh`?** The wrapper refuses at this point in bring-up: it
requires `.env.gaw` carrying the WRITE Google Ads credential, which does not exist yet. So
this pastes the wrapper's own Compose invocation directly instead. `proxy-policy-sync.test.py`
(`TestRunbookMatchesTheWrapper`) is what keeps the two equal — it fails if the wrapper's
invocation ever changes and this block is not updated to match.

```bash
# Precondition check. `sudo test`, not `[ ! -e ]`: hermesops is not in `hermes` and cannot
# traverse the 2750 store, so an unprivileged test reports "absent" whatever is there (F17).
sudo test ! -e /var/lib/hermes/governance/control/mutation-enabled && echo "kill switch absent — safe to proceed"
sudo -u hermes-broker env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin \
  HOME="$(getent passwd hermes-broker | cut -d: -f6)" \
  DOCKER_HOST=unix:///run/hermes/docker-proxy.sock \
  HERMES_GOVERNANCE_DIR=/var/lib/hermes/governance HERMES_AGENT_DIR=/opt/hermes-agent \
  HERMES_ADS_REPO_DIR=/opt/projects/claude-google-ads HERMES_SPOOL_DIR=/var/lib/hermes/spool \
  docker compose --env-file /dev/null -f /opt/hermes-agent/docker-compose.yml \
  run --rm --no-deps -T ads-mutator \
  --client slug-1 --changeset 20260922-120000-abcdef01 --request 00000000-0000-4000-8000-000000000000
echo "rc=$?"
sudo journalctl -u hermes-docker-proxy --since "-5 min" --no-pager | grep 'containers/create'
```

Expected: `rc=2`, output containing `mutation is disabled`, and a journal line
`ALLOW POST /v…/containers/create`. The values in the command are the ones in
`hermes-broker.service`; if you changed the unit, use its values. The refusal is doubly safe:
`slug-1` is also not a registered client (a fresh store's `registry/clients.json` is `{}`), so
even a kill switch present would not reach an account.

**RESULT, 2026-09-22 — PASSED on the box.** `rc=2`, output
`apply-changeset: mutation is disabled (kill switch absent or unreadable) — this is the safe
default`, and the proxy journal line
`ALLOW POST /v1.55/containers/create?name=hermes-agent-ads-mutator-run-…`. Measured on Docker
Engine 29.8.1, API v1.55 — a NEWER Compose/Engine than the CI runner that proved the
`bind-agreement` job (28.0.4), and the bind strings matched the pinned set exactly. The real
`hermes-agent-claude` image ran, not the CI stand-in. Two items leave the "unproven" list:
the box's own Compose version, and the real image. Re-run this phase after any change to the
compose sources, the broker unit's `Environment=`, or the proxy's `--allow-bind` set.

**On anything else:** stop and record it. A `DENY … bind set does not match` means the box's
Compose sends different strings than CI measured. Do not widen the allow-list. A refusal is a
refusal, not a breach, and widening a policy to make bring-up pass is the reflex this runbook
exists to prevent. Never run the old `sudo docker compose --profile tools create ads-mutator`
instrument. Run as root from the working directory, Compose resolves the symlink the broker
does not (F9 spec §2, M6), and before README step 2 it makes Docker create governance
directories as root.

---

## Gate: First Approved Request (Rehearsal)

It sits between Phase 6 and anything that touches the kill switch. **It needs:** F9 (landed),
F12 (landed — approvals are written `hermes-broker:hermes` and run records go to
`<store>/records/`), Phase 6 passed, and a `.env.gaw` the wrapper accepts. **Operator decision
2026-09-25:** the rehearsal uses a **dummy** `.env.gaw` (`GOOGLE_ADS_CREDENTIAL_ROLE=write`,
placeholders elsewhere) and a dedicated **`rehearsal`** client. With the kill switch absent the
executor refuses at its first guard, the kill switch (`apply-changeset.py:105-106`), before it
resolves the client or reads a credential (its guard 8), so the real WRITE credential would prove nothing here. It goes
in later, deliberately — see "Before creating the kill switch" below. The procedure is "Running
the rehearsal", after the F12/F14/§6 notes.

**After pulling F12, lay down the new `records/` row** — these three commands and nothing else
(spec §4). They are flag-less: `init-host-layout.py` already defaults to the right store and spool
roots. Do **not** "run README step 2's layout commands again", which this runbook used to say:
step 2 opens with `.env` edits, `sudo docker compose down` and an `rmdir` of the live store, none
of which is self-guarding and none of which this needs.

```bash
cd /opt/hermes-agent
sudo python3 bin/init-host-layout.py                              # dry run: one "create records", the rest "ok"
sudo python3 bin/init-host-layout.py --apply
sudo -u hermes-broker python3 bin/init-host-layout.py --check     # must exit 0
```

**The dry run needs `sudo` here** (it did not in README step 2, where the store did not yet
exist). The store is `root:hermes 2750` and `hermesops` is deliberately not in `hermes`, so an
unprivileged dry run cannot `lstat` anything below `governance/` or `spool/` and reports every
child as `mismatch … Permission denied` — alarming, and wrong (F17). Run as `hermesops` without
`sudo` on 2026-09-23, it printed exactly that.

**Run `--apply` promptly after the pull — the broker will not start until you do.** Its
`ExecStartPre=` is `init-host-layout.py --check`, which now covers the `records` row, so any
restart in the window between the pull and the `--apply` (a reboot, `Restart=on-failure`, a manual
`systemctl restart`) fails the pre-condition, and with `RestartSec=5` that becomes a restart loop.
This is correct fail-closed behaviour, not a bug: the refusal names `records`, and `--apply` clears
it. No unit files change, so nothing restarts on its own account.

**The proof:** with the kill switch **absent**, a human-approved request goes broker → proxy →
container and comes back `refused_preflight` ("mutation is disabled"). That exercises the
broker's own path (reservation, the wrapper, persistence), which Phase 6 does not. A refusal
emits no `HERMES-RESULT-JSON`, so `persist-run-record.py` writes **no** run record for it
(`persist-run-record.py:18-20`) — the broker's outcome is recorded on the approval instead.

**No further code gate stands before the kill switch** — audit-log truncation (§6 part B) is
closed (PR #57, applied to the box 2026-09-25; see "After pulling §6B"). (F19 —
container-scoped calls accepted any container id — fixed in PR #53 and applied to the box
2026-09-24; see "After pulling F19".) (F14 —
a Compose failure reported as "nothing was mutated" — is fixed: an unverified executor exit is
now status 4, "possibly modified". After pulling F14, run `sudo systemctl restart
hermes-broker` so the running broker process loads the `failed_unverified_exit` mapping —
until it is restarted, a wrapper 4 is recorded as `failed_unknown_exit` instead, which is
still fail-closed but not the intended label. No unit change, no image rebuild; the kill
switch stays absent.)

**After pulling the framing hardening (§6 part A), re-install both units** — they are copied into
`/etc/systemd/system/`, so a pull alone does not apply `UMask=0077`:

```bash
sudo cp /opt/projects/claude_code/infra/hermes-agent/deploy/hermes-docker-proxy.service /etc/systemd/system/
sudo cp /opt/projects/claude_code/infra/hermes-agent/deploy/hermes-broker.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl restart hermes-docker-proxy     # the broker Requires= it and restarts with it —
                                               # no second broker restart: it would interrupt that
                                               # one mid-ExecStartPre (harmless, but logs "Failed
                                               # with result 'signal'"; seen on the box 2026-09-23)
systemctl show -p UMask hermes-docker-proxy hermes-broker          # UMask=0077, both
sudo stat -c '%U:%G %a %n' /run/hermes/docker-proxy.sock           # hermes-docker-proxy:hermes-rail 660
systemctl is-active hermes-docker-proxy hermes-broker              # active, active
systemctl show -p NRestarts hermes-docker-proxy hermes-broker      # not climbing
```

Then re-run Phase 6's pasted create: `rc=2`, `mutation is disabled`, and `ALLOW POST
/v…/containers/create` in `journalctl -u hermes-docker-proxy`. A `DENY … (malformed …)` there is
a finding — identify the client and the header before touching the grammar.

**After pulling F18** — no unit changes; the proxy runs its script from the repo:

```bash
sudo systemctl restart hermes-docker-proxy     # the broker Requires= it and restarts with it
systemctl is-active hermes-docker-proxy hermes-broker
```

Then re-run Phase 6: besides `rc=2` and `ALLOW POST …/containers/create`, the proxy journal must
show `UPGRADE POST /v…/containers/…/attach… (101)`. A `DENY-FOLLOWUP` for the real attach is a
finding (the rail failed closed) — understand it before changing anything.

**After pulling F19** — no unit changes; the proxy runs its script from the repo. **Before
pulling**, see today's gap with the instrument that will prove it closed (prints only a status
code, never a body):

```bash
command -v curl                                                    # a path
GW=$(sudo docker ps -q --no-trunc --filter label=com.docker.compose.service=hermes-agent); echo "${#GW}"   # 64
sudo -u hermes-broker curl -s -o /dev/null -w '%{http_code}\n' \
  --unix-socket /run/hermes/docker-proxy.sock "http://d/v1.55/containers/$GW/json"          # 200 — the gap
```

Then:

```bash
sudo test ! -e /var/lib/hermes/governance/control/mutation-enabled && echo "kill switch absent"
sudo git -C /opt/projects/claude_code pull --ff-only
sudo git -C /opt/projects/claude_code log -1 --oneline                                   # the merge commit of PR #53
sudo systemctl restart hermes-docker-proxy     # the broker Requires= it and restarts with it
systemctl is-active hermes-docker-proxy hermes-broker                                    # active, active
systemctl show -p NRestarts hermes-docker-proxy hermes-broker                            # 0, 0
sudo -u hermes-broker curl -s -o /dev/null -w '%{http_code}\n' \
  --unix-socket /run/hermes/docker-proxy.sock "http://d/v1.55/containers/$GW/json"          # 403
sudo journalctl -u hermes-docker-proxy --since "-5 min" --no-pager \
  | grep -c 'target is not an ads-mutator run: entrypoint mismatch'                          # 1 per probe run since the restart
sleep 1                                                            # journalctl --since includes the whole
                                                                    # second; the 403 probe's own DENY must
                                                                    # fall before T0, not land in the same
                                                                    # second as it
T0=$(date '+%F %T')
```

Then re-run Phase 6 and check the proxy journal:

```bash
sudo journalctl -u hermes-docker-proxy --since "$T0" --no-pager | grep -E 'ALLOW POST .*/containers/create|UPGRADE|DENY'
```

Expected: one `ALLOW POST …/containers/create…`, one `UPGRADE POST …/attach… (101)`, and **no
`DENY` whose reason starts with `target`**. A `target` DENY for the mutator's own calls is a
finding — never widen the check. Other `DENY … not on the allow-list` lines (CI's Compose sends
`GET /info` and `GET /networks/<name>` and tolerates their refusal) predate F19 — record any you
see; never widen the allow-list to silence them. The grep above still shows every `DENY` line
(not filtered to `target` ones) so the operator can record whichever kind appears.

**RESULT, 2026-09-24 — PASSED on the box** (`5acee36..d4fbb29`, proxy restarted only; both units
`active`, `NRestarts=0`). Probe: **`200` before the pull, `403` after**, one `entrypoint mismatch`
line. Phase 6: `rc=2`, `mutation is disabled`, `ALLOW POST …/containers/create…`, `UPGRADE POST
…/attach?stderr=1&stdin=1&stdout=1&stream=1 (101)`, and no `DENY` line of any kind. Kill switch:
absent.

**After pulling §6B** — no unit changes; the broker and pre-flight run their scripts from the
repo. The box has no registered clients, so the new pre-flight check is **vacuous on the real
store** — the proof uses a **scratch store** on the same disk. The real store, the real
registry and the kill switch are never touched. Stop at the first mismatch, but always run the
cleanup block.

Setup (same shell throughout; from `/opt/hermes-agent`):

```bash
cd /opt/hermes-agent
B=/var/lib/hermes-s6b-scratch; SG=$B/governance; SS=$B/spool; L=$SG/log/s6b-probe.jsonl
sudo test -e /var/lib/hermes/governance/control/mutation-enabled && echo PRESENT || echo ABSENT   # ABSENT
PROBE=$(cat <<'EOF'
import errno, os, sys
p = sys.argv[1]
def n():
    with open(p, 'rb') as f: return f.read().count(b'\n')
def t(label, fn):
    try: fn(); print('%-9s OK' % label)
    except OSError as e: print('%-9s DENIED (%s)' % (label, errno.errorcode.get(e.errno, e.errno)))
def app():
    with open(p, 'a') as f: f.write('{}\n')
print('uid=%d gid=%d' % (os.getuid(), os.getgid()))
t('append', app)
t('o_trunc', lambda: os.close(os.open(p, os.O_WRONLY | os.O_TRUNC)))
t('truncate', lambda: os.truncate(p, 0))
print('lines    ', n())
EOF
)
as_broker() { sudo systemd-run --quiet --pipe --wait --collect \
  -p User=hermes-broker -p Group=hermes-broker -p SupplementaryGroups="hermes-rail hermes" \
  -p NoNewPrivileges=true -p ProtectSystem=strict -p ProtectHome=tmpfs -p PrivateTmp=true \
  -p ReadWritePaths="$SG" /usr/bin/python3 -c "$PROBE" "$L"; }
as_executor() { sudo docker run --rm --network none --entrypoint python3 \
  -v $SG/log:/opt/governance/log hermes-agent-claude -c "$PROBE" /opt/governance/log/s6b-probe.jsonl; }
build_scratch() {
  sudo mkdir -m 0755 $B
  sudo python3 bin/init-host-layout.py --store-root $SG --spool-root $SS --apply
  sudo sh -c "printf '%s\n' '{\"clients\": {\"s6b-probe\": {\"status\": \"active\"}}}' > $SG/registry/clients.json"
  sudo python3 bin/migrate-governance.py --governance-root $SG --bootstrap-logs --apply
}
teardown_scratch() { sudo chattr -a $L 2>/dev/null; sudo rm -rf $B; sudo test -e $B && echo STILL-THERE || echo GONE; }
```

**Before the pull** (today's code):

```bash
build_scratch                                   # ends with a JSON result naming s6b-probe in "created"
sudo lsattr $L                                  # NO "a" in the flags
as_broker                                       # append OK · o_trunc OK · truncate OK · lines 0  ← the gap
sudo -u hermes-broker python3 bin/preflight-governance-access.py --root $SG; echo rc=$?   # rc=0
teardown_scratch                                # GONE
```

**Pull** (the broker restarts with the proxy):

```bash
sudo git -C /opt/projects/claude_code pull --ff-only
sudo git -C /opt/projects/claude_code log -1 --oneline          # the §6B merge commit
sudo systemctl restart hermes-docker-proxy
systemctl is-active hermes-docker-proxy hermes-broker           # active, active
systemctl show -p NRestarts hermes-docker-proxy hermes-broker   # 0, 0
```

**After:**

```bash
build_scratch
sudo lsattr $L                                  # an "a" in the flags
as_broker                                       # append OK · o_trunc DENIED (EPERM) · truncate DENIED (EPERM) · lines 1
as_executor                                     # uid=10000 · append OK · o_trunc DENIED (EPERM) · truncate DENIED (EPERM) · lines 2
sudo -u hermes-broker python3 bin/preflight-governance-access.py --root $SG; echo rc=$?   # rc=0
sudo chattr -a $L
sudo -u hermes-broker python3 bin/preflight-governance-access.py --root $SG; echo rc=$?   # rc=2, "1 registered client log(s) are not append-only"
```

**Cleanup — always:**

```bash
teardown_scratch                                                                          # GONE
sudo python3 bin/init-host-layout.py --check --store-root /var/lib/hermes/governance --spool-root /var/lib/hermes/spool; echo rc=$?   # layout OK, rc=0
sudo python3 bin/preflight-governance-access.py --root /var/lib/hermes/governance; echo rc=$?   # rc=0
systemctl is-active hermes-docker-proxy hermes-broker                                     # active, active
sudo test -e /var/lib/hermes/governance/control/mutation-enabled && echo PRESENT || echo ABSENT   # ABSENT
```

**When the first real client is registered:** `--bootstrap-logs --apply` seals its log; confirm
with `sudo lsattr /var/lib/hermes/governance/log/*.jsonl` (an `a` on every line).

**RESULT, 2026-09-25 — PASSED on the box** (`d4fbb29..2a4e30e`, proxy restarted only, no unit
changes; both units `active`, `NRestarts=0`). Scratch store only; the real store, the real
registry and the kill switch were never written. **Before the pull:** the bootstrapped log had
no `a` (`--------------e-------`); as the broker (uid 997, the unit's sandboxing via
`systemd-run`): `append OK · o_trunc OK · truncate OK · lines 0` — the gap; the pre-flight on the
scratch store `rc=0`. **After:** `-----a--------e-------`; as the broker: `append OK · o_trunc
DENIED (EPERM) · truncate DENIED (EPERM) · lines 1`; as the executor (uid 10000, the real image,
through the bind mount): `append OK · o_trunc DENIED (EPERM) · truncate DENIED (EPERM) · lines
2`; the pre-flight `rc=0`, then, after `chattr -a`, `rc=2` with `1 registered client log(s) are
not append-only` and no slug. Cleanup: scratch `GONE`; real store `init-host-layout --check`
`layout OK` `rc=0`, pre-flight `rc=0`; kill switch: absent. Two observations, neither a finding:
right after the restart `is-active` read the broker as `activating` — its `ExecStartPre` checks
were still running; ten seconds later it was `active`/`running`, `NRestarts=0`, the journal
showing `layout OK` then `Started`. And the refusal's headline still says the executor "cannot
use the governance store", which is wrong-footed for an unsealed log (the executor can do too
much, not too little) — the cosmetic wording left by the §6B final review.

**After pulling F22** — the broker **unit** changes (`ProtectHome=tmpfs`, was `true`), and unit
files are copies in `/etc/systemd/system/`, so a pull alone does not apply it:

```bash
sudo test -e /var/lib/hermes/governance/control/mutation-enabled && echo PRESENT || echo ABSENT   # ABSENT
sudo git -C /opt/projects/claude_code pull --ff-only
sudo git -C /opt/projects/claude_code log -1 --oneline                                   # the F22 merge commit
sudo cp /opt/projects/claude_code/infra/hermes-agent/deploy/hermes-broker.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl restart hermes-docker-proxy     # the broker Requires= it and restarts with it
sleep 10
systemctl is-active hermes-docker-proxy hermes-broker                                    # active, active
sudo diff /opt/projects/claude_code/infra/hermes-agent/deploy/hermes-broker.service \
  /etc/systemd/system/hermes-broker.service && echo SAME                                 # SAME
systemctl show -p ProtectHome hermes-broker                                              # ProtectHome=tmpfs  ("yes" = the old unit is still loaded)
systemctl show -p NRestarts hermes-broker                                                # NRestarts=0
```

The end-to-end proof that Compose now works inside the broker's sandbox is the rehearsal's
step 6.

Only the broker unit changes; the proxy unit is untouched and needs no `cp`. Then continue the
rehearsal below **from step 4**: attempt 1's approval is consumed and cannot be reused.

### Running the rehearsal

**Attempt 1 (2026-09-25) stopped at step 6 — F22.** Steps 0–5 matched; the request came back
`failed`/`failed_unverified_exit`, exit 4: Compose, run by the broker under its sandbox, could
not find its own plugin (compose rc=125, no container created). Nothing could have been touched
(kill switch absent, dummy credential, fake customer id; log 0 lines, no run record). The fix is
F22 ("After pulling F22" above). After it, re-run **from step 4** in a fresh session, after
checking that attempt 1 left the state step 4 needs — the stop protocol above may have run
step 8:

```bash
cd /opt/hermes-agent; G=/var/lib/hermes/governance
sudo test -e $G/control/mutation-enabled && echo PRESENT || echo ABSENT              # ABSENT
sudo python3 -c "import json;print(json.load(open('$G/registry/clients.json'))['clients']['rehearsal']['status'])"   # active
sudo lsattr $G/log/rehearsal.jsonl                                                   # an "a" in the flags
sudo stat -c '%U:%G %a' .env.gaw                                                     # hermes-broker:hermes-broker 600
```

If the status is `retired`, re-run step 1 (it rewrites the registry with `rehearsal` active;
step 2 is then unnecessary — the sealed log is still there). If `.env.gaw` is missing, re-run
step 3. Then continue from step 4.

**Mutation stays disabled throughout; nothing here creates the kill switch.** One dedicated,
plainly fake client — `rehearsal`, customer id `0000000000` — goes through the whole approved
path once and is then retired. Nothing here can reach an account: the kill switch is absent,
the executor checks it first, and the credential is a dummy. Registering `rehearsal` is
permanent by design: its sealed log and its approval stay in the store as the record of this
run, and step 8 retires it so the executor refuses it (`client status … not 'active'`) even
once a kill switch exists. Run **every block in the same shell session**, from
`/opt/hermes-agent` — later blocks use `G`, `P`, `CID`, `RID` and `T0` from earlier ones, and
each block starts with a guard that stops it if they are missing. Stop at the first mismatch
and paste what you have, then, before leaving the box:

- **Stopped before step 2 printed `rc=0`:** put the empty registry back, or the broker's
  start-up pre-flight refuses the log-less `rehearsal` and restart-loops on its next restart:
  `printf '%s\n' '{"clients": {}}' > /tmp/r.json && sudo install -o root -g hermes -m 0640 /tmp/r.json $G/registry/clients.json && rm /tmp/r.json`
- **Got past step 3:** run step 8 (retire `rehearsal`, remove the dummy `.env.gaw`).

**0. Preconditions.**

```bash
cd /opt/hermes-agent
G=/var/lib/hermes/governance
sudo test -e $G/control/mutation-enabled && echo PRESENT || echo ABSENT              # ABSENT
systemctl is-active hermes-docker-proxy hermes-broker                                # active, active
sudo python3 -c "import json;print(len(json.load(open('$G/registry/clients.json')).get('clients',{})))"   # 0
sudo test -e .env.gaw && echo "env.gaw PRESENT" || echo "env.gaw absent"             # env.gaw absent
```

**Stop if the client count is not `0`** — step 1 replaces the registry file, and this runbook
is written for a store with no real clients yet.

**1. Register `rehearsal`** (the README's `install` pattern, so the file keeps `root:hermes 0640`):

```bash
: "${G:?run step 0 first}"
printf '%s\n' '{"clients": {"rehearsal": {"project": "claude_google_ads", "customer_id": "0000000000", "status": "active"}}}' > /tmp/rehearsal-clients.json
sudo install -o root -g hermes -m 0640 /tmp/rehearsal-clients.json $G/registry/clients.json
rm /tmp/rehearsal-clients.json
sudo stat -c '%U:%G %a' $G/registry/clients.json                                     # root:hermes 640
```

**2. Its audit log — sealed at creation (§6B) — and the pre-flight on the real store.** This is
the first time the §6B check runs against a registered log rather than an empty registry.

```bash
: "${G:?run step 0 first}"
sudo python3 bin/migrate-governance.py --governance-root $G --bootstrap-logs --apply  # {"created": ["rehearsal"], "skipped": []} (over several lines)
sudo lsattr $G/log/rehearsal.jsonl                                                   # an "a" in the flags
sudo -u hermes-broker python3 bin/preflight-governance-access.py --root $G; echo rc=$?   # rc=0
```

**3. The dummy `.env.gaw`** — the wrapper reads only `GOOGLE_ADS_CREDENTIAL_ROLE` before the
container runs; the executor refuses before it reads the rest. Owned by the broker, which runs
the wrapper. Gitignored.

```bash
: "${G:?run step 0 first}"
printf '%s\n' GOOGLE_ADS_CREDENTIAL_ROLE=write \
  GOOGLE_ADS_DEVELOPER_TOKEN=REHEARSAL-NOT-A-CREDENTIAL GOOGLE_ADS_CLIENT_ID=REHEARSAL-NOT-A-CREDENTIAL \
  GOOGLE_ADS_CLIENT_SECRET=REHEARSAL-NOT-A-CREDENTIAL GOOGLE_ADS_REFRESH_TOKEN=REHEARSAL-NOT-A-CREDENTIAL \
  GOOGLE_ADS_LOGIN_CUSTOMER_ID=0000000000 GOOGLE_ADS_CUSTOMER_ID=0000000000 > /tmp/rehearsal-env.gaw
sudo install -o hermes-broker -g hermes-broker -m 0600 /tmp/rehearsal-env.gaw .env.gaw
rm /tmp/rehearsal-env.gaw
sudo stat -c '%U:%G %a' .env.gaw                                                     # hermes-broker:hermes-broker 600
```

**4. Propose one action** (credential-free, no network). The actions file is in `/tmp` and
removed after.

```bash
: "${G:?run step 0 first}"
# propose runs as root: keep the gateway's vault tree owned by the gateway (uid 10000), or it
# could never create a real client's vault later.
sudo test -d data/vaults || sudo install -d -o 10000 -g 10000 -m 700 data/vaults
sudo stat -c '%u:%g %a' data/vaults                                                  # 10000:10000 700
printf '%s\n' '{"actions": [{"type": "add_campaign_negative", "campaign_id": "1", "keyword": "rehearsal-not-a-real-keyword", "match_type": "EXACT"}]}' > /tmp/rehearsal-actions.json
P=$(sudo env HERMES_GOVERNANCE_DIR=$G HERMES_AGENT_DIR=/opt/hermes-agent HERMES_ADS_REPO_DIR=/opt/projects/claude-google-ads HERMES_SPOOL_DIR=/var/lib/hermes/spool ./changeset.sh propose --client rehearsal --from /tmp/rehearsal-actions.json); echo "$P"   # …/data/vaults/rehearsal/changes/<cid>.json (under sudo the wrapper resolves the /opt/hermes-agent symlink, so it prints /opt/projects/claude_code/infra/hermes-agent/… — the same directory)
rm /tmp/rehearsal-actions.json
sudo chown -R 10000:10000 data/vaults/rehearsal
CID=$(basename "$P" .json); echo "$CID"                                              # YYYYMMDD-HHMMSS-<8 hex>
```

**5. Approve it** — first without `--expect-sha256`, which prints the action and the digest and
refuses (`rc=2`); read the action; then approve with that digest.

```bash
: "${G:?run step 0 first}" "${P:?run step 4 first}" "${CID:?run step 4 first}"
sudo env HERMES_GOVERNANCE_DIR=$G HERMES_AGENT_DIR=/opt/hermes-agent HERMES_ADS_REPO_DIR=/opt/projects/claude-google-ads HERMES_SPOOL_DIR=/var/lib/hermes/spool ./changeset.sh approve --client rehearsal --changeset "$CID" --operator hermesops; echo rc=$?
#   1. add_campaign_negative  campaign 1  EXACT  'rehearsal-not-a-real-keyword'
#   sha256 <64 hex> … rc=2
SHA=$(sudo sha256sum "$P" | cut -d' ' -f1); echo "$SHA"                              # the same 64 hex as above
sudo env HERMES_GOVERNANCE_DIR=$G HERMES_AGENT_DIR=/opt/hermes-agent HERMES_ADS_REPO_DIR=/opt/projects/claude-google-ads HERMES_SPOOL_DIR=/var/lib/hermes/spool ./changeset.sh approve --client rehearsal --changeset "$CID" --operator hermesops --expect-sha256 "$SHA"; echo rc=$?
#   approved <cid> by hermesops (expires <+24h>) … 1 action(s) bound … rc=0
```

**6. File the request from inside the gateway** — the same client Hermes itself uses — and wait
for the broker (it polls every 5 s).

```bash
: "${CID:?run step 4 first}"
GW=$(sudo docker ps -q --no-trunc --filter label=com.docker.compose.service=hermes-agent); echo "${#GW}"   # 64
sleep 1; T0=$(date '+%F %T')
RID=$(sudo docker exec "$GW" python3 /opt/cc-bin/hermes-syscall.py apply --client rehearsal --changeset "$CID"); echo "$RID"   # a 36-character request id
for i in $(seq 1 24); do
  out=$(sudo docker exec "$GW" python3 /opt/cc-bin/hermes-syscall.py result --request-id "$RID")
  case "$out" in pending*) sleep 5 ;; *) break ;; esac
done; echo "$out"
```

Expected: `status refused`, `classification refused_preflight`, `exit_code 2`. Still `pending`
after two minutes is a finding — check `systemctl is-active hermes-broker` and its journal.
`exit_code 4` (`failed_unverified_exit`) is a finding, not a hazard — the kill switch is absent
either way. Attempt 1 hit exactly this (F22). After F22, a second one means the unit copy or the
`daemon-reload` did not take effect (re-check "After pulling F22"), or a new cause. Record it with
step 7's journal output; change nothing.

**7. What the broker, the proxy and the store recorded.**

```bash
: "${G:?run step 0 first}" "${CID:?run step 4 first}" "${RID:?run step 6 first}" "${T0:?run step 6 first}"
sudo journalctl -u hermes-broker --since "$T0" --no-pager | grep -E "request $RID|mutation is disabled|NOT PERSISTED|NOT VERIFIED"
#   broker: request <rid> client rehearsal changeset <cid> rc=2
#   apply-changeset: mutation is disabled (kill switch absent or unreadable) — this is the safe default
#   (no "RUN RECORD NOT PERSISTED", no "EXECUTOR EXIT NOT VERIFIED")
sudo journalctl -u hermes-docker-proxy --since "$T0" --no-pager | grep -E 'ALLOW POST .*/containers/create|UPGRADE|DENY'
#   one ALLOW POST …/containers/create…, one UPGRADE POST …/attach… (101), no DENY whose reason starts "target"
sudo python3 -c "import json,sys;r=json.load(open(sys.argv[1]));print({k:r.get(k) for k in ('request_id','reserved_at','outcome','finished_at')})" $G/approvals/rehearsal/$CID.approval.json
#   request_id == $RID, outcome 'refused_preflight', reserved_at and finished_at set
sudo sh -c "wc -l < $G/log/rehearsal.jsonl"                                          # 0 — refused before any action
sudo find $G/records -mindepth 1 | wc -l                                             # 0 — a refusal writes no run record
```

**8. Retire `rehearsal` and remove the dummy credential — always.**

```bash
: "${G:?run step 0 first}"
printf '%s\n' '{"clients": {"rehearsal": {"project": "claude_google_ads", "customer_id": "0000000000", "status": "retired"}}}' > /tmp/rehearsal-clients.json
sudo install -o root -g hermes -m 0640 /tmp/rehearsal-clients.json $G/registry/clients.json
rm /tmp/rehearsal-clients.json
sudo rm -f .env.gaw; sudo test -e .env.gaw && echo "env.gaw PRESENT" || echo "env.gaw absent"   # env.gaw absent
sudo -u hermes-broker python3 bin/preflight-governance-access.py --root $G; echo rc=$?   # rc=0 (the sealed log stays registered)
systemctl is-active hermes-docker-proxy hermes-broker                                # active, active
sudo test -e $G/control/mutation-enabled && echo PRESENT || echo ABSENT              # ABSENT
```

When pasting output off the box, `rehearsal` is not a real client and needs no redaction; any
other slug does (F21).

**RESULT, 2026-09-25 — PASSED on the box (attempt 2).** F22 applied first (`9cfa681..872ae01`,
broker unit copied, `daemon-reload`, proxy restarted; `diff` → `SAME`, `ProtectHome=tmpfs`,
`NRestarts=0`). Pre-check: `rehearsal` `active`, log sealed (`-----a--------e-------`), dummy
`.env.gaw` `hermes-broker:hermes-broker 600`. New change-set `20260925-191002-c5ad8582`, approved
`rc=0`. Request `88c6485c-219a-48f4-9285-3d541d89e68a` → `status refused`, `classification
refused_preflight`, `exit_code 2`, "a guard refused before any mutation; nothing was mutated".
Broker journal: `rc=2`, container `Creating`/`Created`, `apply-changeset: mutation is disabled (kill
switch absent or unreadable) — this is the safe default`, and the attested `HERMES-EXIT <nonce> 2`
(F14's check succeeding) — no `permission denied`, no `unknown command`, no `NOT VERIFIED`, no
`NOT PERSISTED`. Proxy: every call `ALLOW` — `_ping`, the Compose listing calls, `containers/create`,
and inspect/attach/wait/start each `(target is an ads-mutator run)` (F19) — plus `UPGRADE …/attach
(101)`; **no `DENY`**. Approval: `request_id` = the request, `outcome 'refused_preflight'`,
`reserved_at` and `finished_at` set. Log 0 lines; `records/` empty; kill switch absent. Step 8:
`rehearsal` → `retired`, `.env.gaw` removed, pre-flight `rc=0`, both units `active`, kill switch
absent. (Attempt 1, the same day, stopped at step 6 — F22; see above.)

### Before creating the kill switch

The rehearsal never checked the credential. Before `control/mutation-enabled` is ever created:
put the **real** WRITE credential in `/opt/hermes-agent/.env.gaw` as its own deliberate step
(`install -o hermes-broker -g hermes-broker -m 0600`, never pasted into a chat or a doc), and
register the first real client with `--bootstrap-logs --apply` so its log is sealed (§6B). When
adding that client, **merge** it into `clients.json` and keep the `rehearsal` entry (status
`retired`) — do not reuse the rehearsal's replace-the-whole-file commands.
Creating the kill switch itself remains the operator's decision.

**Also required (F23, added 2026-09-26): the real ads repo, not F6's placeholder.** The executor
runs `code/mutate_campaign_negative.py` from `/opt/projects/claude-google-ads`. That path held the
placeholder when live gate attempt 1 ran, and guard 7 refused (`mutator not found`). The rehearsal
could not catch this, because guard 1 refuses before guard 7 looks for the script. F6's clone is
gated on the **security review**, and so is the real credential (Phase 3). Then check both that
the mutator exists and that the repo is at the commit the laptop verified. Guard 7 checks
existence only:

```bash
A=/opt/projects/claude-google-ads
sudo test ! -e $A/PLACEHOLDER && sudo test -f $A/code/mutate_campaign_negative.py && sudo test -f $A/.hermes-package.json && echo MUTATOR_OK   # MUTATOR_OK
```

Do not create the kill switch unless the line is as shown.

**Live gate attempt 1, 2026-09-26 — refused at guard 7, nothing mutated (F23).** Change-set
`20260926-215204-c332cf8b`, approved `rc=0`; the kill switch was created and removed in one block,
present for about two seconds. Result: `refused_preflight`, `exit_code 2`, attested; no proxy
`DENY`; approval consumed; audit log 0 lines. Because guard 7 runs after guards 1–6b, this also
proved on the box, with the real credential and client, that the kill switch is read, the pilot
resolves, the approval verifies, the caps pass, and the credential's customer id matches the
pilot's. Re-run from a **fresh** change-set once the prerequisite above is met.

**The security review must PASS for the current state (spec 2026-09-28 §5.3).** The ads repo
now reaches the box as an **app package** (`bin/build-app-package.py` on the laptop,
`sudo bin/install-app-package.py` here) — not a clone, so `git rev-parse` above does not apply;
use `D6.1` instead. The running gateway keeps its bind to the *replaced* directory, so after
installing a package run `cd /opt/hermes-agent && sudo docker compose up -d --force-recreate
hermes-agent` and confirm `docker compose ps` shows it running. Three checks against the latest
PASS report in `docs/security-reviews/`, all of which must hold before the kill switch is
created:

```bash
sudo python3 bin/collect-review-evidence.py --fingerprint-only     # "fingerprint" == the report's box fingerprint, "complete": true
sudo python3 bin/collect-review-evidence.py --credentials-only     # == the report's authorised credential set
# laptop: python3 bin/collect-review-evidence-laptop.py --customer "$CUST" --access-digest   # == the report's digest
```

**RESULT, 2026-09-25 — real WRITE credential installed on the box.** Measured on the laptop first,
before the file left it: `./audit-credential-access.sh --cred .env.gaw` → `rc=0`, declared `write`,
measured `MUTATE_CAPABLE`, `mismatch false`; manager-level ADMIN (expected — the operator's own
account, per the credential table in the README); the read-only `hermes@` account still `READ_ONLY`
at both levels; the target customer among the 3 reachable accounts. Copied with `scp` to the deploy
user's home, then:

```bash
cd /opt/hermes-agent
sudo test -e .env.gaw && echo "env.gaw PRESENT" || echo "env.gaw absent"           # absent
sudo install -o hermes-broker -g hermes-broker -m 0600 ~/env.gaw.incoming .env.gaw
shred -u ~/env.gaw.incoming; test -e ~/env.gaw.incoming && echo LEFTOVER || echo gone   # gone
sudo stat -c '%U:%G %a' .env.gaw                                                   # hermes-broker:hermes-broker 600
sudo grep -c '^GOOGLE_ADS_CREDENTIAL_ROLE=write$' .env.gaw                         # 1
sudo grep -c 'REHEARSAL' .env.gaw                                                  # 0 — not the dummy
sudo sed -n 's/^GOOGLE_ADS_REFRESH_TOKEN=//p' .env.gaw | tr -d '\n' | sha1sum | cut -c1-12   # = the audit's refresh_token_sha12
G=/var/lib/hermes/governance; sudo test -e $G/control/mutation-enabled && echo PRESENT || echo ABSENT   # ABSENT
```

Every line as expected; the refresh-token fingerprint on the box matched the laptop audit's
`refresh_token_sha12` (`b5aa4baf3310`, the audit's own sha1-of-the-bare-value convention), so the
installed file is the audited one. No value was printed on either side. Kill switch absent; no
real client registered yet — that is the next step.

**RESULT, 2026-09-26 — first real client registered as the dormant pilot.** Operator decision: the
first real client is the authorised dormant pilot (spec §13), marked `mutation_target:
"dormant_pilot"` — the one client `vault_lib.resolve_dormant_pilot()` returns, the live gate's only
target. It must be the account the WRITE credential is pinned to: `apply-changeset.py` refuses
unless the client's `customer_id` equals the digits of `GOOGLE_ADS_CUSTOMER_ID` in `.env.gaw`
(guard 6b). So the id is read from `.env.gaw` on the box, never typed, and the registry is rebuilt
from the current file — `rehearsal` kept `retired`, as required above:

```bash
cd /opt/hermes-agent
G=/var/lib/hermes/governance
SLUG=<client>                                                                        # stays on the box
CID=$(sudo sed -n 's/^GOOGLE_ADS_CUSTOMER_ID=//p' .env.gaw | tr -dc 0-9); echo "${#CID}"   # 10
printf '%s' "$CID" | sha1sum | cut -c1-12                                            # = the laptop audit's customer_id_sha12
(umask 077; sudo python3 - "$G/registry/clients.json" "$SLUG" "$CID" > /tmp/clients.json.new <<'PY'
import json, re, sys
path, slug, cid = sys.argv[1:]
d = json.load(open(path)); c = d.setdefault("clients", {})
assert re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", slug), "bad slug"
assert re.fullmatch(r"\d{10}", cid), "bad customer id"
assert c.get("rehearsal", {}).get("status") == "retired", "rehearsal entry missing or not retired"
assert slug not in c, "slug already registered"
assert not any(isinstance(v, dict) and v.get("mutation_target") == "dormant_pilot" for v in c.values()), "a dormant pilot is already marked"
c[slug] = {"project": "claude_google_ads", "customer_id": cid,
           "currency": "USD", "timezone": "America/New_York",
           "status": "active", "mutation_target": "dormant_pilot"}
json.dump(d, sys.stdout, indent=2); print()
PY
)
sudo python3 -c "import json,sys;c=json.load(open(sys.argv[1]))['clients'];print(len(c),sorted(v['status'] for v in c.values()),sum(v.get('mutation_target')=='dormant_pilot' for v in c.values()))" /tmp/clients.json.new   # 2 ['active', 'retired'] 1
sudo install -o root -g hermes -m 0640 /tmp/clients.json.new $G/registry/clients.json && rm /tmp/clients.json.new
sudo stat -c '%U:%G %a' $G/registry/clients.json                                     # root:hermes 640
[ "$(sudo python3 bin/vault_lib.py --dormant-pilot --registry $G/registry/clients.json --field customer_id)" = "$CID" ] && echo PILOT_OK || echo PILOT_MISMATCH   # PILOT_OK
sudo python3 bin/migrate-governance.py --governance-root $G --bootstrap-logs --apply  # created: [<client>], skipped: [rehearsal]
sudo lsattr $G/log/$SLUG.jsonl                                                       # an "a" in the flags
sudo -u hermes-broker python3 bin/preflight-governance-access.py --root $G; echo rc=$?   # rc=0
sudo test -e $G/control/mutation-enabled && echo PRESENT || echo ABSENT               # ABSENT
```

Every line as expected: id fingerprint matched the laptop audit's (value kept off the repo: see step 5 of "Ads audits on the box"), `2 ['active',
'retired'] 1`, `root:hermes 640`, `PILOT_OK`, `created: [<client>]` / `skipped: [rehearsal]`, the
log sealed (`-----a--------e-------`), pre-flight `rc=0`, kill switch absent.

**Gotcha, hit on the first run:** the resolver check was first written as `sudo
HERMES_GOVERNANCE_DIR=$G python3 bin/vault_lib.py …` and printed `vault-lib: client registry not
found: /opt/governance/registry/clients.json` → `PILOT_MISMATCH`. The Python library reads
`HERMES_GOVERNANCE_ROOT` (`governance_lib.py`), and falls back to the container path
`/opt/governance`; `HERMES_GOVERNANCE_DIR` is the name the host wrappers (`changeset.sh`) take.
Pass `--registry` explicitly, as above. Nothing on the box was wrong.

Every prerequisite above is now met. Creating `control/mutation-enabled` remains the operator's
decision — and it is turned off again immediately after the live gate.

### Stop everything in one step (security review D8.1)

Paste as one block. It removes the kill switch first (that alone disables every apply), then
stops the broker and the Docker proxy so nothing can file or run a mutation, and confirms both.
Undo is a separate, deliberate step. It is a sequence, not a single `if`: the kill-switch
removal runs even if a `systemctl` call fails.

```bash
G=/var/lib/hermes/governance
sudo rm -f $G/control/mutation-enabled
sudo systemctl stop hermes-broker hermes-docker-proxy
sudo test -e $G/control/mutation-enabled && echo "KILL SWITCH PRESENT — remove it" || echo "kill switch ABSENT"   # kill switch ABSENT
systemctl is-active hermes-broker hermes-docker-proxy                                   # inactive, inactive
```

To resume later: `sudo systemctl start hermes-docker-proxy hermes-broker` (the broker requires
the proxy). The kill switch stays absent until the operator creates it again.

### Revoke the write credential and prove it dead (security review D8.2)

Canon (credential governance) decides the order and the proof: **mint the replacement before
revoking** if the role must keep working, and **prove death by using the token** — the revoke
endpoint's HTTP 200 only means "request accepted". Run on the laptop, from
`~/Projects/claude_code/infra/hermes-agent`, against the laptop's `.env.gaw`. Nothing prints the
token: it goes to `curl` on stdin, never in argv.

1. **Disable on the box first:** the D8.1 block above, then remove the box's copy:
   `sudo shred -u /opt/hermes-agent/.env.gaw` and a system-wide `sudo find / -xdev -name '*env.gaw*'`
   that shows only `.env.gaw.example`.
2. **Record which token you are killing:**
   `sed -n 's/^GOOGLE_ADS_REFRESH_TOKEN=//p' .env.gaw | tr -d '\n' | shasum | cut -c1-12`
3. **Revoke:**
   ```bash
   sed -n 's/^GOOGLE_ADS_REFRESH_TOKEN=//p' .env.gaw | tr -d '\n' | sed 's/^/token=/' \
     | curl -s -o /dev/null -w 'revoke http %{http_code}\n' --data @- https://oauth2.googleapis.com/revoke   # revoke http 200 — NOT proof
   ```
   (Equivalent by hand: Google Account → Security → Third-party access → the Hermes OAuth app →
   remove access. Either way, step 4 is the proof.)
4. **Prove death:** `./audit-credential-access.sh --cred .env.gaw; echo rc=$?` must now FAIL — the
   token refresh is refused (Google's refusal names `invalid_grant`). A successful read means the
   token is alive: stop and investigate. Only then delete the laptop's `.env.gaw`.
5. **Check collateral, per canon rule 1:** revocation isolation follows the Google ACCOUNT, not the
   OAuth client. If the write role shares an account with anything else, run
   `./audit-credential-access.sh --all` and confirm every credential you meant to keep still reads.
6. **Record it:** the revoked token's sha12 (step 2), the date, and step 4's refusal, in the findings
   doc and the brain.

### Sweep the in-memory mounts (security review D2.1)

**Since checklist v1.7 the collector does this itself** (D2.1 `memory_sweep`: every tmpfs/ramfs
mount, by name and by content, paths only), so a review no longer needs this block. Keep it as the
fallback when `memory_sweep` is `could-not-check`, and to re-check by hand.

The collector's credential sweep stays on the root filesystem (`find / -xdev`), so it reports the
writable in-memory mounts as `not_swept`. Sweep them directly and attach the result to the review.
Each `/run/user/<uid>` is its own mount, so each is listed. Names first, then a content check for
renamed files; both are read-only and print paths only.

```bash
for m in /dev/shm /run /run/lock /run/user/*; do
  sudo find "$m" -xdev -type f \( -name '.env*' -o -name '*.ga' -o -name '*.gaw' -o -name '.git-credentials' \
      -o -name 'credentials.json' -o -name 'application_default_credentials.json' \
      -o -name 'id_rsa' -o -name 'id_ecdsa' -o -name 'id_ed25519' \) -print 2>/dev/null
done; echo "name sweep done"                                                             # only "name sweep done"
sudo grep -rlsI -E 'GOOGLE_ADS_(REFRESH_TOKEN|CLIENT_SECRET|DEVELOPER_TOKEN)=|1//0[0-9A-Za-z_-]{20,}' /dev/shm /run/user 2>/dev/null; echo "content sweep done"   # only "content sweep done"
```

### Ads audits on the box (spec 2026-09-29)

`sudo run-client-audit <client>` produces a client's Google Ads trend-audit draft on the box. It
runs the collectors in the one-shot `ads-collector` container, the analyst in `ads-reader`, and
writes the draft into the client's vault with `vault-write` (uid 10000). Exit codes: `0` draft
written, `1` a step failed, `2` a pre-check refused, `3` another audit is running. The read
credential lives at `/etc/hermes/.env.ga` (`root:root 0400`), is passed to the containers per run
by variable name, and is never mounted. The orchestrator calls `docker compose` **without**
`--env-file`, so compose reads `/opt/hermes-agent/.env` for interpolation; that file must keep
`HERMES_GOVERNANCE_DIR`, `HERMES_SPOOL_DIR`, `HERMES_AGENT_DIR` and `HERMES_ADS_REPO_DIR`.

Do the steps in order. The slug and the customer id never go in the repo; write `<client>` here.

**0. Update the box checkout.** Everything below (the command, the compose services, the checks)
comes from this PR's merge.

```bash
cd /opt/projects/claude_code && sudo git pull --ff-only && sudo git log --oneline -1   # the merge commit of the ads-audits-on-the-box PR
sudo git -C /opt/projects/claude_code status --short                                 # empty
```

**1. Install the re-pinned package.** The pin is in `registry/projects.yaml`
(`claude_google_ads` → `commit: 81103e1a3b563d97b4a1087fc35c29f9e74f120f`, the scrubbed SOP docs).
Build on the laptop, copy to the deploy user's home, install on the box. This is the same
procedure as in "The ads repo" (its **App package** bullet) and in the Gate section paragraph
"The security review must PASS for the current state"; only the pin changed.

```bash
# laptop — the builder refuses unless the ads repo's HEAD is exactly the pin with no tracked changes,
# so park the local settings change, build, then restore it and the branch you were on
cd ~/Projects/claude_code/infra/hermes-agent
git -C ~/Projects/claude-google-ads checkout -q 81103e1a3b563d97b4a1087fc35c29f9e74f120f
git -C ~/Projects/claude-google-ads stash push -q -m pkg -- .claude/settings.json
python3 bin/build-app-package.py --project claude_google_ads --repo ~/Projects/claude-google-ads --commit 81103e1a3b563d97b4a1087fc35c29f9e74f120f --out-dir /tmp/pkg; echo rc=$?   # rc=0, "files: 21", printed sha256 == package.sha256 in registry/projects.yaml
git -C ~/Projects/claude-google-ads stash pop -q
git -C ~/Projects/claude-google-ads checkout -q -
git -C ~/Projects/claude-google-ads stash list                                          # empty
scp /tmp/pkg/claude_google_ads-81103e1a3b56.tar /tmp/pkg/claude_google_ads-81103e1a3b56.manifest.json hermesops@<host>:~/
# box
cd /opt/hermes-agent
sudo python3 bin/install-app-package.py --project claude_google_ads --package ~/claude_google_ads-81103e1a3b56.tar --manifest ~/claude_google_ads-81103e1a3b56.manifest.json --target /opt/projects/claude-google-ads; echo rc=$?   # rc=0: the installer refuses unless the manifest sha256 equals the registry pin and every member matches
sudo docker compose up -d --force-recreate hermes-agent && sudo docker compose ps hermes-agent   # running
```

The security review's `D6.1` then reports `installed_sha256 == pin`.

**2. Install the read credential** (operator, from the laptop). Measure it first with
`./audit-credential-access.sh --cred .env.ga` (declared `read`, measured `READ_ONLY`), then copy it
to the deploy user's home and install it:

```bash
# laptop: scp .env.ga hermesops@<host>:~/env.ga.incoming
sudo install -d -m 0755 /etc/hermes && sudo install -o root -g root -m 0400 ~/env.ga.incoming /etc/hermes/.env.ga && shred -u ~/env.ga.incoming
sudo stat -c '%U:%G %a' /etc/hermes/.env.ga                                       # root:root 400
sudo grep -c '^GOOGLE_ADS_CREDENTIAL_ROLE=read$' /etc/hermes/.env.ga              # 1
sudo python3 /opt/hermes-agent/bin/collect-review-evidence.py --credentials-only  # the read row for /etc/hermes/.env.ga (role read; its refresh-token sha12 equals the laptop's .env.ga row's), then one row per non-Google secret already installed
ls ~/env.ga.incoming 2>&1                                                         # No such file or directory (F24: no stray copy)
```

**3. Install the Anthropic key** (operator). The key never enters an assistant session.

1. In the Anthropic Console create the workspace `hermes-box`, set a **monthly spend limit** on it,
   create a key in that workspace and save it in the password manager.
2. Delete the legacy `...9wAA` key in the Console.
3. On the box, replace the dummy value with `sudoedit` (the value stays off the command line):

```bash
sudoedit /opt/hermes-agent/.env                  # set ANTHROPIC_API_KEY=<the new key>; keep the four HERMES_* directory variables
sudo sed -nE 's/^ANTHROPIC_API_KEY=//p' /opt/hermes-agent/.env | awk '{print substr($0,1,10), "len="length($0)}'   # sk-ant-api len=<n>  (prefix and length only)
cd /opt/hermes-agent && sudo docker compose up -d --force-recreate                     # claude-auth-init rewrites the executor's settings
sudo docker compose ps                                                                  # gateway running
```

The orchestrator refuses a key that does not start `sk-ant-` (it also refuses the old dummy).

**4. Create the audit-data and audit-logs roots.** Per-client audit-data directories are created
`10000:10000 0700` by the tool (the collector mounts them read-write); the root must be traversable
by uid 10000 but not listable. Each run's step logs go to `/var/lib/hermes/audit-logs/<client>/`,
which is never mounted into a container: root-owned `0711`, logs `root 0600`, except
`snapshot.stdout`, which is handed to uid 10000 so `vault-write` can read it.

```bash
sudo install -d -o root -g root -m 0711 /var/lib/hermes/audit-data
sudo install -d -o root -g root -m 0711 /var/lib/hermes/audit-logs
sudo stat -c '%U:%G %a' /var/lib/hermes/audit-data /var/lib/hermes/audit-logs      # root:root 711 (twice)
```

Reports no longer live in `data/reports`: since Option B part 1, `ads-reader` writes
`/var/lib/hermes/reports/<client>`, which `run-client-audit` creates fresh (uid 10000, `0700`) on
every run below the root `0711` parent from part 1 step 2 ("Chat-triggered audits — part 1"
below). Do not create `data/reports`.

**5. Register the spending client.** The entry is `"status": "active"` with **no**
`mutation_target`; the dormant pilot stays the only mutation target. The slug and the id stay off
the repo (F21). Compute the id's fingerprint on the laptop first, printing only the sha1 prefix:
`printf '%s' <id> | shasum -a 1 | cut -c1-12`.
The fingerprint is for comparing laptop and box **in the terminal only**: never write it into
this repo, a review report, the brain or a ticket. A customer id is 10 digits, so its sha1 prefix
is reversible by brute force in minutes, and publishing it is publishing the id.

**Incident, 2026-09-29 — do not change this procedure's shape.** An earlier version put a hidden
`read` inside a multi-line paste. The paste fed `read` an empty line, the id check failed, and the
next line's `sudo install` copied the resulting EMPTY temp file over `clients.json`. The store was
broken (`migrate-governance` and the preflight refused, correctly) until it was rebuilt. Hence:
the id is read in its OWN one-line paste, from `/dev/tty`, into a root-only temp file; the
registry is only ever replaced by a script that parses the current file, validates the new one and
swaps it atomically.

A. Paste this **single line**, press Enter, type the id at the hidden prompt, Enter:

```bash
read -rs -p "customer id: " P </dev/tty; echo; printf '%s' "$P" | tr -dc 0-9 | sudo tee /root/.cid >/dev/null; unset P; sudo sh -c 'tr -d "\n" </root/.cid | wc -c; tr -d "\n" </root/.cid | sha1sum | cut -c1-12'   # 10, then the laptop fingerprint — if not, stop
```

B. Only if both matched (no prompt in this block; set `SLUG` and `FP`, the laptop fingerprint):

```bash
G=/var/lib/hermes/governance; SLUG=<client>; FP=<fingerprint>; cd /opt/hermes-agent
sudo python3 bin/register-client.py --slug "$SLUG" --fingerprint "$FP"                # N ['active', ...] 1: it refuses, changing nothing, on an empty or unparsable registry, a duplicate, or a wrong fingerprint
sudo stat -c '%U:%G %a' $G/registry/clients.json                                     # root:hermes 640
sudo python3 bin/migrate-governance.py --governance-root $G --bootstrap-logs --apply  # created: [<client>]
sudo lsattr $G/log/$SLUG.jsonl                                                       # an "a" in the flags
sudo -u hermes-broker python3 bin/preflight-governance-access.py --root $G; echo rc=$?   # rc=0
sudo install -d -o 10000 -g 10000 -m 0700 /var/lib/hermes/vaults/$SLUG && sudo stat -c '%u:%g %a' /var/lib/hermes/vaults/$SLUG   # 10000:10000 700 (Option B part 1: the vault is outside the gateway data/)
sudo shred -u /root/.cid; sudo ls /root/.cid 2>&1                                    # No such file or directory
```

If the script stops at any `assert`, the registry is untouched: fix the input and repeat A.

**6. Install the command.**

```bash
sudo ln -sf /opt/hermes-agent/deploy/run-client-audit /usr/local/sbin/run-client-audit
ls -l /usr/local/sbin/run-client-audit                                          # -> /opt/hermes-agent/deploy/run-client-audit
```

**7. Dry run, then the first audit.**

```bash
sudo run-client-audit <client> --dry-run; echo rc=$?    # the planned steps: full commands, env var NAMES only, customer id redacted; rc=0
sudo run-client-audit <client>; echo rc=$?              # every step rc=0; "draft -> /var/lib/hermes/vaults/<client>/audits/<ts>-audit.md" (Option B part 1); rc=0
```

Copy the draft off with `scp`, and record the runtime (the summary the run prints) and the cost
(the Console's `hermes-box` usage).

Two checks that have never run on real Docker; do them on this first run and write the result down:

- **(a) `-e NAME` pass-through.** The dry run shows names only; confirm compose really receives the
  values from the calling environment. The first real collect step must either succeed, or fail
  with an auth error that names **no missing variable**. A `variable is not set` warning or an
  auth error naming a variable means the pass-through does not work: stop and fix it before
  another run.
- **(b) uid 10000 traversal.** `vault-write` runs as uid 10000 via `setpriv`. It must traverse the
  governance store (`root:hermes 2750`) and `/var/lib/hermes/audit-logs` (`0711`, twice: the root
  and `<client>/`), to read `snapshot.stdout`. A `vault-write` failure with `EACCES` (Permission
  denied) is a traversal problem: check the modes on each path component
  (`sudo namei -m /var/lib/hermes/audit-logs/<client>/snapshot.stdout`), not the tool. The step
  logs are `root 0600`: read them with `sudo`.

**Operator note:** after the first real run, merge and push the ads-repo branch
`docs/scrub-client-ids` (commit `81103e1`), so the pin is reproducible from GitHub.

**8. Offboarding.** When a client is retired, set its registry status to `retired`, then remove
both trees and its logs. The review's D7.1 checks that no retired client has either tree.

```bash
sudo rm -rf /var/lib/hermes/audit-data/<client> /var/lib/hermes/audit-logs/<client> /var/lib/hermes/vaults/<client> /var/lib/hermes/reports/<client> /var/lib/hermes/draft-out/<client>
sudo ls /var/lib/hermes/audit-data /var/lib/hermes/audit-logs /var/lib/hermes/vaults /var/lib/hermes/reports /var/lib/hermes/draft-out   # <client> no longer listed
```

## Chat-triggered audits — part 1: isolation and egress (spec 2026-09-30 §4–§6)

**Gate: apply only after parts 2 and 3 are merged and review #6 is scheduled (spec §10: the box
gets nothing until all three PRs are merged).**

Breaks the review-#5 binding; nothing here is live for chat until part 2 and review #6.

1. Record the current commit, then pull (the SHA is what a rollback checks out):
   `sudo git -C /opt/projects/claude_code log --oneline -1`
   `cd /opt/projects/claude_code && sudo git pull --ff-only && sudo git log --oneline -1`
2. Host parents (root 0711):
   `sudo install -d -o root -g root -m 0711 /var/lib/hermes/vaults /var/lib/hermes/reports /var/lib/hermes/draft-out`
3. Anthropic key to its own file. Run this ALONE (it prompts on the tty, hidden):
   `sudo python3 /opt/hermes-agent/bin/install-env-secret.py set --file /etc/hermes/.env.anthropic --name ANTHROPIC_API_KEY --prefix sk-ant- --mode 0400 --owner-uid 0 --owner-gid 0`
   Check: `sudo stat -c '%U:%G %a' /etc/hermes/.env.anthropic` → `root:root 400`.
4. Stop the gateway, migrate, check:
   `cd /opt/hermes-agent && sudo docker compose stop hermes-agent`
   `sudo python3 bin/migrate-client-data.py` (dry run: read the counts)
   `sudo python3 bin/migrate-client-data.py --apply; echo rc=$?` → `rc=0`
   Exit codes: `0` done (copies verified, `data/vaults` and `data/reports` removed); `1` verify failed or the source changed while copying: the source is intact, remove the destination dirs the command lists, make sure the gateway is really stopped, and re-run; `2` refused before copying anything (a symlink in the source, an existing destination client dir, or a destination parent that is not root 0711); `3` copies verified but removing the source failed: **do NOT remove the destination** (it may now be the only full copy) — finish removing `data/vaults` and `data/reports` by hand, then continue.
   `sudo ls -la /var/lib/hermes/vaults` → one `drwx------ 10000` dir per active client
5. Strip the key from the gateway env (part 2 retires claude-auth-init; until then the gateway
   needs no real key for audits):
   `sudo python3 bin/install-env-secret.py strip --file /opt/hermes-agent/.env --name ANTHROPIC_API_KEY`
   `sudo docker compose up -d --force-recreate hermes-agent`
   `sudo test -e /opt/hermes-agent/data/home/.claude/settings.json && echo STILL-PRESENT || echo absent`
   → `absent` (spec §6: no Anthropic key in a file the gateway can read; `STILL-PRESENT`: see below)
   `STILL-PRESENT` after pulling all three parts at once is expected (the retired sidecar that cleared the
   file no longer exists), and this step is not passed until the test prints `absent`.
   The file holds the Anthropic key: check it is the old one
   (`sudo stat -c '%y' /opt/hermes-agent/data/home/.claude/settings.json` → a date before today), then
   `sudo shred -u /opt/hermes-agent/data/home/.claude/settings.json` and re-run the test → `absent`.
   A file dated today means something still writes it: stop.
6. Install show-audit: `sudo ln -sf /opt/hermes-agent/deploy/show-audit /usr/local/sbin/show-audit`
7. Docker engine and DNS (CVE-2024-29018: older engines forward an `internal: true` network's
   external DNS lookups, a covert exit for the drafter):
   `sudo docker version --format '{{.Server.Version}}'` → at least **26.0.0**, or **25.0.4+** on 25.x,
   or **23.0.11+** on 23.x; anything older stops here (upgrade Docker first).
   In-drafter DNS probe (from `/opt/hermes-agent`; the drafter must not resolve an outside name):
   `sudo docker compose --profile tools run --rm --no-deps -T ads-drafter "python3 -c 'import socket; socket.getaddrinfo(\"example.com\", 443)' 2>/dev/null && echo DNS_RESOLVES || echo DNS_BLOCKED"`
   → `DNS_BLOCKED`; `DNS_RESOLVES` stops here (upgrade Docker; the CI integration test asserts the same).
   Manual audit on the spending client:
   `sudo run-client-audit <client> --dry-run` (the plan shows `proxy` then `draft`, env names only)
   `sudo run-client-audit <client>; echo rc=$?` → `rc=0`
   `sudo show-audit <client> | head -20` → the DRAFT banner
   `sudo run-client-audit <client> --list --json` → `{"audits": [...], "status": "ok"}`
   (`show-audit <client>` prints the latest; `--ts TS` a specific one; `--list` the timestamps.)
8. Registering a NEW client from now on also creates
   `sudo install -d -o 10000 -g 10000 -m 0700 /var/lib/hermes/vaults/<client>` (replaces the
   data/vaults step of "Ads audits on the box" step 5). Offboarding removes
   `/var/lib/hermes/{vaults,reports,draft-out}/<client>` as well as `audit-data` and `audit-logs`.
9. Rollback (only if part 1 must be undone before part 2):
   `cd /opt/hermes-agent && sudo docker compose stop hermes-agent`
   Return the checkout to the commit recorded before step 1's pull: `sudo git -C /opt/projects/claude_code checkout <recorded sha>` (detached HEAD: later pulls fail until you return; once the issue is fixed: `cd /opt/projects/claude_code && sudo git checkout main && sudo git pull --ff-only`)
   `sudo install -d -o 10000 -g 10000 -m 700 /opt/hermes-agent/data/vaults` (the migration removed it)
   For each client: `sudo mv /var/lib/hermes/vaults/<client> /opt/hermes-agent/data/vaults/<client>`
   (`mv` on the same filesystem keeps owners, modes and mtimes; across filesystems use
   `sudo cp -a` then verify before removing the source), then
   `sudo stat -c '%u %a' /opt/hermes-agent/data/vaults/<client>` → `10000 700`.
   Restore the gateway key, ALONE (prompts on the tty):
   `sudo python3 /opt/hermes-agent/bin/install-env-secret.py set --file /opt/hermes-agent/.env --name ANTHROPIC_API_KEY --prefix sk-ant- --mode 0600 --owner-uid 0 --owner-gid 0`
   `sudo docker compose up -d --force-recreate hermes-agent`

---

## Chat-triggered audits — part 2: the chat trigger (spec 2026-09-30 §3, §6)

Requires part 1 on the box. Still not live until review #6.

1. Record the current commit, then pull (the SHA is what a rollback checks out):
   `sudo git -C /opt/projects/claude_code log --oneline -1`
   `cd /opt/projects/claude_code && sudo git pull --ff-only`
2. The app user (no login, no home, primary group of its own, member of hermes):
   `sudo useradd --system --user-group --no-create-home --shell /usr/sbin/nologin hermes-app-ads-audit`
   `sudo usermod -aG hermes hermes-app-ads-audit`
   `id hermes-app-ads-audit` → groups `hermes-app-ads-audit,hermes`, and NOT docker or sudo
3. Layout: `cd /opt/hermes-agent && sudo python3 bin/init-host-layout.py --app ads-audit --apply; echo rc=$?` → `rc=0`
   Registry readable by the broker: `sudo -u hermes-app-ads-audit test -r /var/lib/hermes/governance/registry/clients.json && echo REG_OK`
4. Units:
   `sudo cp deploy/hermes-app-broker@.service deploy/hermes-app-runner@.service deploy/hermes-app-runner@.path /etc/systemd/system/`
   `sudo systemctl daemon-reload`
   `sudo systemctl enable --now hermes-app-broker@ads-audit hermes-app-runner@ads-audit.path`
   `systemctl is-active hermes-app-broker@ads-audit hermes-app-runner@ads-audit.path` → `active active`
5. OpenRouter: in the OpenRouter console create a dedicated key with limit $10, reset monthly. Set
   Zero Data Retention in the OpenRouter ACCOUNT privacy settings (Hermes has no zdr key; the
   config sends `provider_routing.data_collection: "deny"`; spec §13), and deny data-collecting
   providers there too. Back up the gateway env first (the rollback copy):
   `sudo install -o root -g root -m 0600 /opt/hermes-agent/.env /opt/hermes-agent/.env.pre-optb2`
   Then, ALONE:
   `sudo python3 bin/install-env-secret.py set --file /opt/hermes-agent/.env --name OPENROUTER_API_KEY --prefix sk-or- --mode 0600`
6. Gateway config: back up the live file first, outside the gateway-writable `data/`:
   `sudo install -o root -g root -m 0600 data/config.yaml /root/config.yaml.pre-optb2`
   (it is your rollback copy), then `sudo diff data/config.yaml config.yaml.example` (review anything
   Hermes wrote itself), then `sudo install -o 10000 -g 10000 -m 640 config.yaml.example data/config.yaml`
   The gateway rewrites `data/config.yaml` once it runs (its layout, and it may add keys of its own); review item D10.6 compares the
   parsed `mcp_servers` block with the template, so do not re-install the template to "fix" a layout difference.
   From Hermes v0.21.5 the template carries `platforms.api_server.enabled: false` (the API server stays off); a box whose `data/config.yaml` predates it gets that block appended once, as a top-level key, or `api_server: {enabled: false}` added under an existing top-level `platforms:` key (never a second `platforms:` key) (the gateway keeps it through its rewrites), then `sudo docker compose restart hermes-agent`; review item D4.1 `listeners` then shows no `8642`.
7. Recreate the gateway without the retired sidecar:
   `sudo docker compose up -d --build --remove-orphans hermes-agent`
   `sudo docker compose ps -a` → no `claude-auth-init`
   `sudo test ! -e /opt/hermes-agent/data/home/.claude/settings.json && echo NO_CLAUDE_KEY_FILE`
   (if present, it holds the Anthropic key: `sudo shred -u /opt/hermes-agent/data/home/.claude/settings.json`, as part 1 step 5)
   After any later pull that changes `bin/hermes-app-mcp.py` or a `bin/*_lib.py` it imports: `cd /opt/hermes-agent && sudo docker compose restart hermes-agent` (the gateway keeps the old tool server running until then).
8. Tools visible: `sudo docker compose exec hermes-agent hermes mcp list` → `ads_audit` with 3 tools
9. Kill switch (for the review and for emergencies):
   on:  `sudo touch /var/lib/hermes/app-state/ads-audit/DISABLED`
   off: `sudo rm /var/lib/hermes/app-state/ads-audit/DISABLED`
   The switch only refuses NEW requests: jobs already queued in `jobs/` and a run in flight
   still go ahead. To stop queued work too, stop the runner's path unit and the runner itself:
   `sudo systemctl stop hermes-app-runner@ads-audit.path hermes-app-runner@ads-audit.service`
   (an in-flight run is cut off and later reported `interrupted`, never re-run; queued jobs wait
   in `jobs/` and run when `sudo systemctl start hermes-app-runner@ads-audit.path` is issued).
   To discard the queued jobs instead, with both units stopped:
   `sudo find /var/lib/hermes/app-state/ads-audit/jobs -mindepth 1 -delete` — the broker then
   reports each one `interrupted` (its periodic recover, within about a minute).
10. First chat audit: `cd /opt/hermes-agent && sudo docker compose exec -it hermes-agent hermes chat`, then ask
    "Run the Google Ads audit for <client>." Expect `ok` within ~5 min (or `pending`; ask for its
    status later). Journal: `sudo journalctl -u hermes-app-broker@ads-audit -n 20 --no-pager`.
    A reply of "MCP call timed out" while the journal shows `status=ok` for that request means the gateway is
    running a tool server from before the ping fix: pull, then `sudo docker compose restart hermes-agent`.
    Once it works, delete both rollback backups (they may hold provider keys; they MUST be gone
    before review #6's evidence collection; keep them until then only if you still need to roll back):
    `sudo shred -u /opt/hermes-agent/.env.pre-optb2 /root/config.yaml.pre-optb2`
    `sudo ls /opt/hermes-agent/.env.pre-optb2 /root/config.yaml.pre-optb2` → both `No such file or directory`
11. Live refusal checks (review D10.7 needs one each of `refused/disabled`, `refused/quota` and
    `refused/bad_request` in the broker journal, 30 days back; the broker journal shows the client
    short name by design). They place a request file in the spool the way the gateway's MCP tool does
    (`requests/<uuid>.json`, as the broker's own user, which owns that directory) and read the journal
    line the broker writes for it (it polls every 2 s). None runs an audit. Each line is one paste;
    `<client>` is the client of step 10's chat audit.
    a. Kill switch, then a request while it is set (any `run` request is refused before anything else is checked):
    `sudo touch /var/lib/hermes/app-state/ads-audit/DISABLED`
    `R=$(cat /proc/sys/kernel/random/uuid); printf '{"app": "ads-audit", "client": "<client>", "op": "run", "request_id": "%s"}' "$R" | sudo -u hermes-app-ads-audit tee /var/lib/hermes/spool/apps/ads-audit/requests/$R.json >/dev/null; sleep 6; sudo journalctl -u hermes-app-broker@ads-audit --since -2min -o cat --no-pager | grep "request=$R"`
    → `hermes-app-broker[ads-audit]: request=<uuid> op=run client=<client> status=refused reason=disabled`
    Only when that line has appeared: `sudo rm /var/lib/hermes/app-state/ads-audit/DISABLED` (switch off again before the next check). If no line appeared (the broker is stopped or slow), delete the request first with `sudo rm -f /var/lib/hermes/spool/apps/ads-audit/requests/$R.json`, check `systemctl is-active hermes-app-broker@ads-audit`, and only then remove the switch: a request still in `requests/` is decided afresh once the switch is gone, and could start a real audit.
    b. Quota (the manifest allows one `run` per client per UTC day. The broker refuses a second one only
    while a `run` for that client is HELD today: a `list` request, a `run` that ended `busy` and a run
    from another day do not count. If none is held, the request below would be admitted and start a
    real, paid audit.) Ask the broker's own counter, as root, on the same UTC day as step 10's audit:
    `sudo python3 -c 'import sys; sys.path.insert(0, "/opt/hermes-agent/bin"); import app_lib as A; print("HELD_RUNS=%d" % A.Ledger("/var/lib/hermes/app-state/ads-audit/state/ledger.jsonl").count(A.utcnow()[:10], "run", "<client>"))'`
    → `HELD_RUNS=1` is the only output that means safe to paste the next line (paste it at once, not after midnight UTC). Any other output (`HELD_RUNS=0`, an error): skip the quota check for today and run it after the next day's first real audit.
    Then the same second-run request as in a:
    `R=$(cat /proc/sys/kernel/random/uuid); printf '{"app": "ads-audit", "client": "<client>", "op": "run", "request_id": "%s"}' "$R" | sudo -u hermes-app-ads-audit tee /var/lib/hermes/spool/apps/ads-audit/requests/$R.json >/dev/null; sleep 6; sudo journalctl -u hermes-app-broker@ads-audit --since -2min -o cat --no-pager | grep "request=$R"`
    → `... request=<uuid> op=run client=<client> status=refused reason=quota`
    If no line appears, delete `requests/$R.json` as in a before doing anything else.
    c. Malformed request. It must be a well-named file (`<36 characters of 0-9a-f and ->.json`, a fresh
    uuid) with content the broker rejects (here `{}`: the keys are wrong): that is `refused/bad_request`.
    A badly named file (any other name) is only `dropped/bad_request`, which does not count:
    `R=$(cat /proc/sys/kernel/random/uuid); printf '{}' | sudo -u hermes-app-ads-audit tee /var/lib/hermes/spool/apps/ads-audit/requests/$R.json >/dev/null; sleep 6; sudo journalctl -u hermes-app-broker@ads-audit --since -2min -o cat --no-pager | grep "request=$R"`
    → `hermes-app-broker[ads-audit]: request=<uuid> op=- client=- status=refused reason=bad_request`
    Confirm all three at once: `sudo journalctl -u hermes-app-broker@ads-audit --since -30d -o cat --no-pager | grep -oE 'status=refused reason=(disabled|quota|bad_request)' | sort | uniq -c` → one line each. Each refusal also leaves a result file in `results/` (the review's D10.8 lists them; they are in the whitelist).
12. Rollback (only if part 2 must be undone):
    `sudo touch /var/lib/hermes/app-state/ads-audit/DISABLED`
    `sudo systemctl disable --now hermes-app-broker@ads-audit hermes-app-runner@ads-audit.path`
    `sudo systemctl stop hermes-app-runner@ads-audit.service` (stopping the path unit does not stop an in-flight runner)
    `cd /opt/hermes-agent && sudo docker compose stop hermes-agent`
    Return the checkout to the commit recorded before step 1's pull: `sudo git -C /opt/projects/claude_code checkout <recorded sha>` (detached HEAD: later pulls fail until you return; once the issue is fixed: `cd /opt/projects/claude_code && sudo git checkout main && sudo git pull --ff-only`)
    Restore the config: `sudo install -o 10000 -g 10000 -m 640 /root/config.yaml.pre-optb2 data/config.yaml`
    Restore the gateway env: `sudo install -o root -g root -m 600 /opt/hermes-agent/.env.pre-optb2 /opt/hermes-agent/.env`
    `cd /opt/hermes-agent && sudo docker compose up -d --build --force-recreate hermes-agent`
    Revoke the dedicated OpenRouter key created in step 5, in its console. The app user and the
    layout directories are left in place (harmless). Delete the backups as in step 10.

---

## The listener check (finding F50)

A timer measures the gateway container's listening ports every 15 minutes and records the result.
It repeats, between reviews, what a review's D4.1 measures: Hermes v0.21.5 opened an API server on
port 8642 by default (F44), and the two controls that keep it off sit in files the gateway can
write. **It records only**: it stops nothing and flips no switch (operator decision, 2026-10-07).
Review item D4.5 checks that it is live.

Install it once, after a pull that brings `deploy/hermes-listener-check.service`. Run `sudo -v`
alone first, so sudo's password prompt cannot take a pasted line:

```bash
sudo install -d -o root -g root -m 0700 /var/lib/hermes/listener-check
sudo cp /opt/projects/claude_code/infra/hermes-agent/deploy/hermes-listener-check.service /etc/systemd/system/
sudo cp /opt/projects/claude_code/infra/hermes-agent/deploy/hermes-listener-check.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now hermes-listener-check.timer
sudo ln -sf /opt/hermes-agent/deploy/show-listener-check /usr/local/sbin/show-listener-check
sudo systemctl start hermes-listener-check.service; echo "first_run_rc=$?"
sudo show-listener-check; echo "status_rc=$?"
systemctl is-active hermes-listener-check.timer; systemctl is-enabled hermes-listener-check.timer
systemctl list-timers hermes-listener-check.timer --no-pager | head -3
sudo journalctl -u hermes-listener-check -n 3 -o cat --no-pager
```

Expected: `first_run_rc=0`. The status is JSON, one value to a line: under `"last"` it shows
`"status": "ok"`, `"listeners"` holding `9119` (or nothing, with the dashboard off) and
`"docker_dns_listeners": 1`; then `"alert_present": false`; it ends with `listener check: OK`, and
`status_rc=0`. Then `active` and `enabled`; a timer line with a NEXT time about 15 minutes ahead;
and the journal line `hermes-listener-check: status=ok reason=- listeners=[9119] unexpected=[]
docker_dns_listeners=1`.

Two things here are proven on the box for the first time, because neither can be tested on the
laptop: that the service works inside its systemd sandbox (it reads another process's `/proc` on
the host; `first_run_rc=0` with a real port list is that proof), and that the timer runs again
after a run that did not exit 0 (check once, around a gateway restart: after a `could-not-check`
run, `systemctl list-timers hermes-listener-check.timer` still shows a NEXT time).

**This runs a `systemctl daemon-reload`.** The next review's D4.2 shows `matches_last_pass: false`
for the proxy, and the operator's evidence carries the reconstruction of "A security review"
step 3, as after the chat-trigger rollout.

Reading it later:

- `sudo show-listener-check` prints the last result, its age, whether an alert is waiting, the
  history's counts (about a month of runs) and the alert log (every alert and clearing ever
  recorded; `alerts.jsonl` is never trimmed, and a review compares it with the previous one's). It ends with `listener check: OK` (exit 0) only when the last result is `ok`,
  it is under 45 minutes old, and no alert is waiting. Make it part of the weekly look at the box.
- `sudo journalctl -u hermes-listener-check --since -1d -o cat --no-pager | tail` shows the runs: one
  line each, ports and fixed words only.
- A run exits 1 on an alert and 2 when it could not look (the gateway was down), so
  `systemctl status hermes-listener-check` shows that run as failed. That is the signal, not a
  fault: the timer runs it again 15 minutes later.
- Around a gateway restart or recreate, a `could-not-check` run with the reason `no-gateway` is
  expected.

If an alert is waiting (`"alert_present": true`): the `ALERT` file names the first time it happened
and the unexpected ports, and stays until you remove it. Find out what listened (`cd /opt/hermes-agent && sudo docker
compose exec hermes-agent sh -c 'cat /proc/net/tcp'` shows the table; port 8642 means the API
server is back on: check that `platforms.api_server.enabled: false` is still in
`data/config.yaml`), fix it, write down what it was for the next review (D4.5 asks), and only then:
`sudo python3 /opt/hermes-agent/bin/check-gateway-listeners.py --clear-alert`.

---

## Replace the OpenRouter key

The gateway's OpenRouter key is the box's alone: created in the OpenRouter console for the box
only, typed once into the installer prompt, and stored nowhere else (no laptop file, no password
manager, no note). It is replaced every 12 months (operator decision, 2026-10-06; the key in use
was created 2026-10-06), and at once on a suspected leak or a copy found outside the box.

The order matters: the old key is deleted only after the new one is proven, and no backup copy
of the old `.env` is made (the review's sweep reports one as `unlisted`, a FAIL).

1. OpenRouter console: create a new key for the box only, credit limit $10, reset monthly. Copy
   it once.
2. Box. First `sudo -v`, so the password prompt cannot take the paste. Then, ALONE:
   `cd /opt/hermes-agent && sudo python3 bin/install-env-secret.py set --file /opt/hermes-agent/.env --name OPENROUTER_API_KEY --prefix sk-or- --mode 0600 --owner-uid 0 --owner-gid 0`
   Paste the key at `value (hidden):`. Then clear the laptop's clipboard: `pbcopy < /dev/null`.
3. Box: note the Hermes home file, `sudo stat -c '%u %a %s' /opt/hermes-agent/data/.env` (owner and
   mode are `10000 600`). Recreate the gateway, because a restart keeps the old environment:
   `cd /opt/hermes-agent && sudo docker compose up -d --force-recreate hermes-agent`, then
   `cd /opt/hermes-agent && sudo docker compose ps -a` (`Up`, not `Restarting`) and the same `stat`
   again (owner, mode and size as before: the start-up wrote nothing new).
4. Box: prove the new key. `cd /opt/hermes-agent && sudo docker compose exec -it hermes-agent hermes chat`,
   ask for a one-word reply, and check that the new key's console page then shows a "Last Used"
   time.
5. OpenRouter console: only now delete the old key. Capture the new key's whole page (limit,
   reset, creation date, usage) and the API-keys list showing the old key gone. Both screens
   identify the account and show a masked fragment of a key: keep them in the git-ignored
   `security-reviews/` folder and never commit them.
6. Laptop: check that no copy of either key is there. Search `~/Projects`, `~/.hermes`,
   `~/.config` and the shell start-up files for OpenRouter-shaped keys with a command that prints
   file names only, never a value, and stop any laptop gateway that was started with the box's key
   (`docker compose down`). A laptop Hermes stack uses a key of its own.
7. Collect fresh evidence as for a security review (below): both probes, a new box bundle and a
   same-day laptop bundle. The box fingerprint does not change (no component covers a credential),
   but the authorised credential set does, and D10.5's statement is restated for the new key.

---

## A security review

Since checklist v1.17 it also needs the listener check installed and running ("The listener check"; D4.5), and reads the dashboard's secrets in whichever form Phase 7 left them (D2.1, D4.1); since v1.18 it also reads the accepted SSH keys (D1.7) and each service's start time (D4.6).
Run it after parts 1 and 2 are applied and the rollback backups are shredded (part 2 step 10;
the sweep reports a leftover `.env.pre-optb2` as `unlisted`, a FAIL). The three live refusal checks of part 2 step 11 must have been run within the last 30 days (D10.7). The chat audit of part 2 step 10 must have returned `ok` within the last 7 days (D10.8: the broker deletes a result 7 days after writing it): collect the evidence within 7 days of that audit, or run another chat audit first. Raw bundles live in the
gitignored `security-reviews/`; only the report is committed.

1. Laptop, once: `python3 infra/hermes-agent/bin/review-fp-key.py init` (never overwrite; `show-id` prints its id).
2. Box: `cd /opt/projects/claude_code && sudo git pull --ff-only`. First read each start time and the update log, and write any restart since the last PASS into the evidence (D4.6 asks): `for u in docker hermes-docker-proxy hermes-broker hermes-app-broker@ads-audit; do echo "$u $(systemctl show $u -p ActiveEnterTimestamp --value)"; done; uptime -s; grep -E 'Start-Date|Commandline' /var/log/apt/history.log | tail -6`. These lines only read, and they run for the first time on the box: the rehearsal's stand-in server has no systemd, so only `uptime -s` and the `grep` were run there. A healthy output is four lines, each a unit's name followed by a date and time (a name with nothing after it means that unit never became active since boot: stop and say so; the lines show when each unit last started, not that it is running now, which the collector's D4.2 and D10.3 report), then the box's boot time, then up to six lines of the update log. Then count the `Match` blocks in the sshd configuration (D1.7): `sudo sh -c 'cat /etc/ssh/sshd_config /etc/ssh/sshd_config.d/*.conf 2>/dev/null | grep -ciE "^[[:space:]]*match[[:space:]]"'` prints the number of `Match` lines; expected `0`. Put the number in the evidence file (D1.7 cannot pass without it); another number needs your statement of what each block sets. The command reads those two fixed places only: it also prints `0` when neither can be read, and a `Match` line in a file that an `Include` brings in from another directory is not counted, so say in the evidence that the count covers `/etc/ssh/sshd_config` and `/etc/ssh/sshd_config.d/*.conf` (rehearsed on a stand-in server: `0`, `1` and `2`; on the box it runs for the first time). After a pull that changed a file a service loads, restart that service before collecting (`sudo systemctl restart <unit>`): the trial collection's (the collector run once with a throwaway key before the real collection, to see that every item is observed: `K=$(openssl rand -hex 32); echo "throwaway key: $K"` prints the key, 64 characters, which is typed or pasted at the collector's key prompt and discarded afterwards) D4.6 `files_newer_than_start` names it. Then the probes: `sudo run-client-audit --probe-env; echo rc=$?` and `sudo run-client-audit --probe-egress; echo rc=$?` (both `rc=0`; the collector re-runs them). Each probe starts real containers: `--probe-env` can take about 8 minutes in the worst case and the collector allows 600 s per probe, so a slow run is not a hang. `rc=3` with no JSON on stdout (a line on stderr) means an audit holds the lock: wait for it and run the probe again.
3. Box, ALONE (it prompts for the key on the tty; paste it from `pbcopy < ~/.config/hermes-review/fp.key`):
   `cd /opt/projects/claude_code && sudo python3 infra/hermes-agent/bin/collect-review-evidence.py --fp-key-tty --last-pass-execstart <the last PASS report's execstart_sha256> --last-pass-collected-at <the last PASS box bundle's collected_at> > ~/bundle-box.json`
   (the collector re-runs both probes as D10.1 and D10.2, so this step takes as long as step 2 again; `--last-pass-execstart` is the last PASS report's D4.2 `execstart_sha256`, 64 lowercase hex characters. `--last-pass-collected-at` is in the last PASS report's header from review #9 on; for review #9 itself, read it from review #8's bundle.)
   Once the key is pasted, clear the laptop's clipboard: `pbcopy < /dev/null`.
   If the proxy's `ExecStart` hash will not match the last PASS (D4.2) because `systemctl daemon-reload` ran since
   then (part 2 step 4 runs one, and so does "The listener check"; the line then shows `start_time=[n/a]` and `pid=0` for a running proxy), put this
   output in the operator evidence file. Its first hash is the bundle's `execstart_sha256`; its second puts the
   running process's start time and pid back, and equals the last PASS value when the command line is unchanged:
   `L=$(systemctl show hermes-docker-proxy -p ExecStart --no-pager); P=$(systemctl show hermes-docker-proxy -p MainPID --value); T=$(systemctl show hermes-docker-proxy -p ExecMainStartTimestamp --value); echo "pid=$P start=$T"; printf '%s\n' "$L" | sha256sum; printf '%s\n' "$L" | sed "s/start_time=\[n\/a\] ; stop_time=\[n\/a\] ; pid=0/start_time=[$T] ; stop_time=[n\/a] ; pid=$P/" | sha256sum`
4. Laptop: `bin/collect-review-evidence-laptop.py --customer <dormant pilot id> --package-* ...` (reads the same key file, and refuses one with any group or other access: it is `0600`; the ads repo checked out at the pin, with `.claude/settings.json` stashed).
5. Copy the box bundle to the laptop's `security-reviews/`, and delete it from the box. Check that both bundles show the same `cid_key_id`.
6. Launch a fresh reviewer with only what REVIEWER-BRIEF lists: REVIEWER-BRIEF, CHECKLIST, REPORT-TEMPLATE, both bundles, the findings doc, `config.yaml.example` (D10.6) and the operator evidence file. That file holds the manual items' statements (D3.2, D8.1, D8.2, D9.1, and D10.5's limit and privacy routing with the console screens), D2.1's Anthropic-key statement, D2.1's dashboard statement (on, or off with a password left in the file; needed whenever the gateway row's `secrets_held` names `dashboard-password`) and the `ls` output of part 2 step 10, D4.2's baseline statement (when `matches_last_pass` is `null` or `false`), D10.8's statement that the `ok` run came from chat, D1.7's statement of whose each accepted key is (and the `Match` count of step 2), D4.6's statement of each restart since the last PASS (what started, when, why).

---

## Phase 7: Reach the Dashboard From the Laptop

Independent of phase 5 — needs only the phase 4 stack. Verified end to end on 2026-09-21.

The dashboard is **off by default**: with `HERMES_DASHBOARD` unset the container runs only
`s6-supervise dashboard` with nothing under it, and `127.0.0.1:9119` resets (curl exit 56) —
the host listener is Docker's port-forwarder, not proof that anything is serving.

**Basic auth is mandatory.** The dashboard binds `0.0.0.0` *inside* the container, which the
June-2026 hardening treats as a non-loopback bind requiring an auth provider. `--insecure` is a
documented no-op. Never publish 9119 on a public interface, and never open it in `ufw`.

### Step 7a: Set the credentials (`hermesops@<host>`)

Generate the password in a password manager first — **letters and digits, 24+**. `$` is
interpolated by Compose inside `.env` values; `#`, quotes, spaces and backslashes are parsed
unreliably. Paste the whole block at once — it is a single `if`, so a failed check writes
nothing. (The first run used a length check that only *printed* a warning; the next line ran
anyway and wrote a 13-character partial paste, and no password worked at login.)

```bash
cd /opt/hermes-agent
sudo grep -c '^HERMES_DASHBOARD' .env       # 0 on first setup; otherwise edit, do not append
read -rs -p "Paste password from manager: " P; echo
if [ ${#P} -ge 16 ] && case "$P" in *'$'*|*'#'*|*'"'*|*"'"*|*' '*|*'\'*) false;; *) true;; esac; then
  sudo install -m 600 /dev/null .env.new
  { sudo grep -v '^HERMES_DASHBOARD' .env
    printf 'HERMES_DASHBOARD=1\nHERMES_DASHBOARD_BASIC_AUTH_USERNAME=hermesadmin\nHERMES_DASHBOARD_BASIC_AUTH_PASSWORD=%s\n' "$P"
  } | sudo tee .env.new >/dev/null
  sudo install -m 600 .env.new .env && echo "WRITTEN len=${#P}"; sudo shred -u .env.new
else
  echo "REFUSED: length ${#P} (need >=16) or a forbidden character -- nothing written"
fi
unset P
```

`.env.new` is created at `600` *before* `tee` writes into it, so the password never sits in a
world-readable file. `printf` is a shell builtin, so the value never appears in `ps`.

### Step 7b: Restart and prove auth is enforced

```bash
sudo docker compose up -d; sleep 15
F=$(sudo grep '^HERMES_DASHBOARD_BASIC_AUTH_PASSWORD=' .env | cut -d= -f2-)
C=$(sudo docker compose exec -T hermes-agent printenv HERMES_DASHBOARD_BASIC_AUTH_PASSWORD)
echo "len: file=${#F} container=${#C}"; [ "$F" = "$C" ] && echo "file == container"; unset F C
curl -s -o /dev/null -w 'HTTP=%{http_code} -> %{redirect_url}\n' http://127.0.0.1:9119/
for p in /api/config /api/sessions /api/logs; do curl -s -o /dev/null -w "$p HTTP=%{http_code}\n" http://127.0.0.1:9119$p; done
curl -s http://127.0.0.1:9119/api/status | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("auth_required"), d.get("auth_providers"))'
sudo ss -tlnH | grep -v '127.0.0'            # :22 only
```

Measured 2026-09-21:

- `/` returns **`302 -> /login?next=%2F`**, a "Sign in — Hermes Agent" form. The provider
  is form-based, so **do not expect `401` from `/`**. An earlier draft of this step did, and
  read the `302` as ambiguous until the redirect was followed.
- `/api/config`, `/api/sessions`, `/api/logs` return `401`.
- `/api/status` returns `True ['basic']`.

**`/api/status` answers without credentials.** Its fields are operational: gateway state,
counts, version, `auth_required`, `auth_providers`, and profile names. No credentials or client
data. Accepted while it is loopback-only; recorded in the findings.

### Step 7c: Tunnel (laptop)

The laptop's own local Hermes stack also uses 9119, so forward to **19119** — then
`127.0.0.1:19119` is always the VPS and never the local dashboard:

```bash
ssh -N -o ExitOnForwardFailure=yes -L 19119:127.0.0.1:9119 -i ~/.ssh/vps-hermes hermesops@<ip>
```

Browse `http://127.0.0.1:19119`. **Control first:** sign in with a wrong password and confirm
it is refused, and only then with the real one. A wrong-password refusal proves nothing while
the right password is also failing. `Ctrl+C` closes the tunnel; the stack keeps running.

The Hermes Desktop app can use this gated dashboard as its backend, through the same forward:
README "Using the Hermes Desktop app against the box" has the set-up (a login item that keeps
the forward open) and the rules for using it (measured 2026-10-06).

### Step 7d: Switch to a hashed password and a signing secret

Since Hermes v0.21.5 the gateway `.env` can hold the password's scrypt hash, so no plaintext is at
rest (finding F47), and a signing secret, so a gateway restart does not sign the dashboard and the
Desktop app out. Measured on 2026-10-07
(`docs/evaluations/2026-10-07-dashboard-password-hash-and-session-secret.md`). Three things can
lock you out of the dashboard, and each step below guards one:

- **The hash holds `$`, and Docker Compose interpolates `$` in this file.** Written bare, the hash
  reaches the container cut short, with only a warning, and nobody can sign in (finding F52). The
  installer writes it inside single quotes and refuses to write it bare.
- **The plaintext line wins while it is set**, so the hash does nothing until that line is gone.
- **A mistyped password** makes a hash nobody knows the password of. The first block compares
  what you type with the password in use before it hashes anything.

You never see, copy or paste the hash or the secret. The plaintext line is removed only AFTER the
running gateway is shown to hold the exact hash, so sign-in keeps working at every point where
you might stop. SSH still works if the dashboard does not: the worst case is repeating this step.

The two blocks that ask for the password are each ONE function followed by its call, so the
prompt cannot take the next pasted line as your answer (step 7a's history has such a partial
paste). Run `sudo -v` alone first, so sudo's own prompt cannot take one either.

Block 0 (`hermesops@<host>`), alone:

```bash
cd /opt/hermes-agent && sudo -v
```

Block 1: type the password you sign in with today. It is compared with the one in use before
anything is hashed.

```bash
step7d_hash() {
  local P
  cd /opt/hermes-agent || return
  read -rs -p "Current dashboard password: " P; echo
  if [ "$P" = "$(sudo grep '^HERMES_DASHBOARD_BASIC_AUTH_PASSWORD=' .env | cut -d= -f2-)" ] && [ ${#P} -ge 16 ]; then
    printf '%s' "$P" | sudo docker compose exec -T -w /opt/hermes hermes-agent python3 -c 'import sys; from plugins.dashboard_auth.basic import hash_password; sys.stdout.write(hash_password(sys.stdin.read()))' \
      | sudo python3 bin/install-env-secret.py set --file /opt/hermes-agent/.env --name HERMES_DASHBOARD_BASIC_AUTH_PASSWORD_HASH --prefix 'scrypt$' --quote single --mode 0600 --owner-uid 0 --owner-gid 0 --stdin
  else
    echo "REFUSED: that is not the password in use (or it is under 16 characters) -- nothing written"
  fi
}; step7d_hash; unset -f step7d_hash
```

Expect `install-env-secret: HERMES_DASHBOARD_BASIC_AUTH_PASSWORD_HASH set in /opt/hermes-agent/.env (mode 0600)`.
On `REFUSED`, or any other message, stop: nothing was changed, and blocks 2 and 3 must not be run.

Block 2: the signing secret (made on the box, never shown), then the gateway recreated with BOTH
the old plaintext line and the new hash. The plaintext still wins, so sign-in is unchanged; the
point is to see what the gateway received.

```bash
cd /opt/hermes-agent
sudo python3 bin/install-env-secret.py generate --file /opt/hermes-agent/.env --name HERMES_DASHBOARD_BASIC_AUTH_SECRET --mode 0600 --owner-uid 0 --owner-gid 0
sudo docker compose up -d --force-recreate hermes-agent; echo "UP_EXIT=$?"
sleep 25; sudo docker compose ps -a hermes-agent --format '{{.Service}} {{.State}} {{.Status}}'
F=$(sudo python3 -c 'import sys; sys.path.insert(0, "bin"); import client_audit_lib as C; print((C.env_values(open(".env").read(), "HERMES_DASHBOARD_BASIC_AUTH_PASSWORD_HASH") or [""])[0])')
C=$(sudo docker compose exec -T hermes-agent printenv HERMES_DASHBOARD_BASIC_AUTH_PASSWORD_HASH)
[ -n "$C" ] && [ "$F" = "$C" ] && echo "hash: file == container (len ${#C})" || echo "HASH DIFFERS (file ${#F}, container ${#C}): STOP"; unset F C
sudo docker compose exec -T hermes-agent printenv HERMES_DASHBOARD_BASIC_AUTH_SECRET | awk '{print "secret: in the container (len " length($0) ")"}'
```

Expect `install-env-secret: HERMES_DASHBOARD_BASIC_AUTH_SECRET generated in …` (on a second run it
refuses, because the name already has a value: that is fine), `UP_EXIT=0` with no line saying
`variable is not set`, `hermes-agent running Up …`, `hash: file == container (len 86)` and
`secret: in the container (len 44)`. On `HASH DIFFERS`, stop: the hash line is not single-quoted
or is missing; run block 1 again. Nothing is broken at this point, because the plaintext line is
still there.

Block 3: only now the plaintext line goes, and only if the gateway holds the file's hash (the
block checks again by itself).

```bash
cd /opt/hermes-agent
F=$(sudo python3 -c 'import sys; sys.path.insert(0, "bin"); import client_audit_lib as C; print((C.env_values(open(".env").read(), "HERMES_DASHBOARD_BASIC_AUTH_PASSWORD_HASH") or [""])[0])')
C=$(sudo docker compose exec -T hermes-agent printenv HERMES_DASHBOARD_BASIC_AUTH_PASSWORD_HASH)
if [ ${#C} -eq 86 ] && [ "$F" = "$C" ]; then
  sudo python3 bin/install-env-secret.py strip --file /opt/hermes-agent/.env --name HERMES_DASHBOARD_BASIC_AUTH_PASSWORD
  sudo docker compose up -d --force-recreate hermes-agent; echo "UP_EXIT=$?"; sleep 25
else
  echo "NOT STRIPPED: the gateway does not hold the file's hash (file ${#F}, container ${#C})"
fi; unset F C
sudo docker compose ps -a hermes-agent --format '{{.Service}} {{.State}} {{.Status}}'
sudo docker compose exec -T hermes-agent printenv HERMES_DASHBOARD_BASIC_AUTH_PASSWORD >/dev/null && echo "PLAINTEXT STILL SET" || echo "plaintext: not in the container"
sudo grep -oE '^HERMES_DASHBOARD_BASIC_AUTH[A-Z_]*' .env | sort
sudo stat -c '%U %G %a' .env
```

Expect `install-env-secret: HERMES_DASHBOARD_BASIC_AUTH_PASSWORD removed from /opt/hermes-agent/.env (1 line(s))`,
`UP_EXIT=0`, `hermes-agent running Up …`, `plaintext: not in the container`, these three names and
no other, and `root root 600`:

```
HERMES_DASHBOARD_BASIC_AUTH_PASSWORD_HASH
HERMES_DASHBOARD_BASIC_AUTH_SECRET
HERMES_DASHBOARD_BASIC_AUTH_USERNAME
```

On `NOT STRIPPED`, nothing was removed: go back to block 2's check.

Block 4: prove sign-in, wrong password first. The password travels on stdin, never on a command
line.

```bash
step7d_login() {
  local P
  read -rs -p "Dashboard password: " P; echo
  login() { printf '{"provider":"basic","username":"hermesadmin","password":"%s"}' "$1" | curl -s -o /dev/null -w '%{http_code}\n' -H 'Content-Type: application/json' -H 'Origin: http://127.0.0.1:9119' --data @- http://127.0.0.1:9119/auth/password-login; }
  echo "wrong password -> $(login "not-the-password-0000")"
  echo "right password -> $(login "$P")"
  unset -f login
}; step7d_login; unset -f step7d_login
```

Expect `wrong password -> 401` and `right password -> 200`. (A password with a `"` or a `\`
would break this JSON; step 7a allows letters and digits only.) Then sign in from the laptop
(browser or the Desktop app), run `cd /opt/hermes-agent && sudo docker compose restart hermes-agent`
once, and confirm you are still signed in: that is the signing secret at work. Sessions refresh
for 30 days.

If sign-in fails with the right password: put a plaintext line back with step 7a's block (it wins
over a hash) and recreate. Step 7a's block rewrites every `HERMES_DASHBOARD…` line, so it also
removes the hash and the signing secret: once sign-in works again, find out why it failed, then
start this step over from block 0.

The plaintext password is now nowhere on the box, so a review's leak checks can no longer look
for it in the histories and the journals: they look for its hash and for the signing secret
(D10.7 says so). Keep the password in the password manager as before.

After this step the next security review's D2.1 shows the gateway row's `secrets_held` as
`["openrouter-key", "dashboard-password-hash", "dashboard-session-secret"]`, and D4.1's
`secret_env` shows `matches-file` for those three and `unset` for `dashboard-password`.

### Step 7e: Replace the dashboard password

Step 7d hashed the password but did not change it: the value that was in plaintext in the gateway
`.env` until 2026-10-07 still signs in. It must stop working (security review #8, finding F56).
This step sets a NEW password and replaces the signing secret in the same pass (operator decision,
2026-10-07), so every session that is open now ends.

The secret is replaced too because a new password alone would not end an old session. Measured on
2026-10-08, one change at a time, on a throwaway copy of the setup
(`docs/evaluations/2026-10-07-limited-ssh-key-and-dashboard-password-replacement.md`, section 2.4):
with only the password hash replaced, sessions opened with the old password kept answering
(control C); with the signing secret replaced they stopped (control B); a recreate of the container
alone left them alive (control A).

The new password is never on a command line, in a file or on the screen: it is typed at a hidden
prompt, hashed inside the gateway container, and only the hash is written. The recovery from any
failure below is to run the step again; SSH is not involved, so nothing here can lock you out of
the box. **Quit the Hermes Desktop app first, so nothing retries the old password while this
runs.**

**The sign-in limit.** The dashboard allows 10 sign-in attempts per 60 seconds from one address,
and successful attempts count. The eleventh is answered `429` whatever the password; a mistyped
password is answered `401`, not `429`. The limit ended 56 to 61 seconds after a burst in every
run, and refused attempts did not extend it. Recreating the gateway empties it, and block 2 does.
Block 3 makes 3 attempts, so it can be run three times within a minute. (Measured on a throwaway
setup, section 2.5 of the evaluation; the box itself has not run it yet.)

Run `sudo -v` alone first as in step 7d. The blocks that ask for the password are each ONE
function followed by its call and are pasted alone. Generate the new password in the password
manager first: letters and digits only, 24 or more.

Block 0 (`hermesops@<host>`), alone:

```bash
cd /opt/hermes-agent && sudo -v && sudo grep -oE '^HERMES_DASHBOARD_BASIC_AUTH[A-Z_]*' .env | sort
```

Expected: exactly `HERMES_DASHBOARD_BASIC_AUTH_PASSWORD_HASH`, `HERMES_DASHBOARD_BASIC_AUTH_SECRET` and
`HERMES_DASHBOARD_BASIC_AUTH_USERNAME`. A line `HERMES_DASHBOARD_BASIC_AUTH_PASSWORD` means step 7d
was not finished: stop, because a plaintext password would win over the new hash.

Block 1, alone (one function and its call). It asks for the new password twice and writes nothing
unless the two match, there are 24 or more characters and they are all letters and digits.

```bash
step7e_set() {
  local P Q
  cd /opt/hermes-agent || return
  read -rs -p "NEW dashboard password: " P; echo
  read -rs -p "The same again: " Q; echo
  if [ "$P" = "$Q" ] && [ ${#P} -ge 24 ] && case "$P" in *[!A-Za-z0-9]*) false;; *) true;; esac; then
    if printf '%s' "$P" | sudo docker compose exec -T -w /opt/hermes hermes-agent python3 -c 'import sys; from plugins.dashboard_auth.basic import hash_password; sys.stdout.write(hash_password(sys.stdin.read()))' \
      | sudo python3 bin/install-env-secret.py set --file /opt/hermes-agent/.env --name HERMES_DASHBOARD_BASIC_AUTH_PASSWORD_HASH --prefix 'scrypt$' --quote single --mode 0600 --owner-uid 0 --owner-gid 0 --stdin; then
      if sudo python3 bin/install-env-secret.py strip --file /opt/hermes-agent/.env --name HERMES_DASHBOARD_BASIC_AUTH_SECRET; then
        sudo python3 bin/install-env-secret.py generate --file /opt/hermes-agent/.env --name HERMES_DASHBOARD_BASIC_AUTH_SECRET --mode 0600 --owner-uid 0 --owner-gid 0
      fi
    fi
  else
    echo "REFUSED: the two entries differ, or it is under 24 characters, or it holds something other than letters and digits -- nothing written"
  fi
}; step7e_set; unset -f step7e_set
```

Expected: three `install-env-secret:` lines (`HERMES_DASHBOARD_BASIC_AUTH_PASSWORD_HASH set …`,
`HERMES_DASHBOARD_BASIC_AUTH_SECRET removed … (1 line(s))`, `HERMES_DASHBOARD_BASIC_AUTH_SECRET
generated …`). On `REFUSED`, or any other message, or fewer than three `install-env-secret:` lines,
stop: run block 1 again. (If the removal fails, the block stops there and never writes a new
secret: rehearsed on a throwaway copy; it prints the failure and ends without an error status, so
count the lines.) The running gateway still has the old password until block 2.

After a partial run (rehearsed: the hash's `set` line, then the removal's failure message, and no
`generated` line) the file holds the NEW hash and the OLD signing secret, nothing has been
recreated, and the running gateway is unchanged: the dashboard still works with the old password.
Running block 1 again is the remedy (rehearsed on that state: the second run set the hash again,
removed the secret and generated a new one). Not rehearsed: a removal that works followed by a
`generate` that fails, which would leave the file without a signing secret; block 2's `secret:`
line is where that would show. If block 1 fails twice, stop and report it, and do not run block 2.

Block 2: the gateway is stopped and recreated. The two listener-check runs are review #8's entry 10:
the first must fail because the gateway is down, the second must be `ok`.

```bash
cd /opt/hermes-agent
sudo docker compose stop hermes-agent; echo "STOP_EXIT=$?"
sudo systemctl start hermes-listener-check.service; echo "check_while_stopped_rc=$?"
sudo docker compose up -d --force-recreate hermes-agent; echo "UP_EXIT=$?"
sleep 25; sudo docker compose ps -a hermes-agent --format '{{.Service}} {{.State}} {{.Status}}'
F=$(sudo python3 -c 'import sys; sys.path.insert(0, "bin"); import client_audit_lib as C; print((C.env_values(open(".env").read(), "HERMES_DASHBOARD_BASIC_AUTH_PASSWORD_HASH") or [""])[0])')
C=$(sudo docker compose exec -T hermes-agent printenv HERMES_DASHBOARD_BASIC_AUTH_PASSWORD_HASH)
[ ${#C} -eq 86 ] && [ "$F" = "$C" ] && echo "hash: file == container (len ${#C})" || echo "HASH DIFFERS (file ${#F}, container ${#C}): STOP"; unset F C
sudo docker compose exec -T hermes-agent printenv HERMES_DASHBOARD_BASIC_AUTH_SECRET | awk '{print "secret: in the container (len " length($0) ")"}'
sudo docker compose exec -T hermes-agent printenv HERMES_DASHBOARD_BASIC_AUTH_PASSWORD >/dev/null && echo "PLAINTEXT STILL SET" || echo "plaintext: not in the container"
sudo systemctl start hermes-listener-check.service; echo "check_after_rc=$?"
sudo show-listener-check | tail -n 1
systemctl list-timers hermes-listener-check.timer --no-pager | head -3
```

Expected: `STOP_EXIT=0`; `check_while_stopped_rc` NOT `0` (systemd reports the job failed: the check
could not look); `UP_EXIT=0`; `hermes-agent running Up …`; `hash: file == container (len 86)`;
`secret: in the container (len 44)`; `plaintext: not in the container`; `check_after_rc=0`;
`listener check: OK`; a timer line with a NEXT time. Keep this output for the next review's
evidence (D4.5, D4.6). Every other output is listed below. **These instructions are reasoned from
the block's text, not measured:** every rehearsal of this block printed the expected lines, so none
of the outputs below has been produced.

- `STOP_EXIT` or `UP_EXIT` not `0`: the dashboard may be down. Run
  `sudo docker compose ps -a hermes-agent` and report what it prints. SSH is not affected.
- `check_while_stopped_rc=0`: the check did not find the gateway down. It harms nothing in this
  step; write it in the evidence, because the review expects this run to have failed.
- `HASH DIFFERS` together with a `secret:` line: run block 1 again, then this block.
- `HASH DIFFERS` and no `secret:` line: the `docker compose exec` itself failed, so the gateway is
  not up. See the `UP_EXIT` bullet above; do not run block 1 again for this.
- `secret: in the container (len N)` with N other than `44`: the signing secret is not the one
  block 1 generates. Run block 1 again, then this block.
- No `secret:` line while the `hash:` line is as expected: that line is printed once for each line
  the container returns, so no line means the container holds no signing secret. Run block 1 again,
  then this block.
- `PLAINTEXT STILL SET`: stop. Step 7d was not finished, and a plaintext password wins over the
  new hash.
- `check_after_rc` not `0`, or a last line other than `listener check: OK`: run
  `sudo show-listener-check` and report what it prints. A review fails while the last run is not
  `ok`.
- No timer line with a NEXT time: report it ("The listener check" has the timer's set-up).

The first proof on the box, as with the listener check itself. The laptop rehearsal ran this block
with these changes and no others: no `sudo`; the gateway's env file under another name, in a
scratch directory instead of `/opt/hermes-agent`; the installer and its library by their path in
the repository; no `--owner-uid 0 --owner-gid 0`; and without the four listener-check lines,
because the laptop has no systemd. Whether `check_while_stopped_rc` is not `0` and
`check_after_rc` is `0` is therefore seen here for the first time, and so are `sudo` and the root
ownership of the file.

Block 3, alone (one function and its call): the OLD password must now be refused.

```bash
step7e_login() {
  local OLD NEW
  read -rs -p "OLD dashboard password: " OLD; echo
  read -rs -p "NEW dashboard password: " NEW; echo
  login() { printf '{"provider":"basic","username":"hermesadmin","password":"%s"}' "$1" | curl -s -o /dev/null -w '%{http_code}\n' -H 'Content-Type: application/json' -H 'Origin: http://127.0.0.1:9119' --data @- http://127.0.0.1:9119/auth/password-login; }
  echo "old password -> $(login "$OLD")"
  echo "wrong password -> $(login "not-the-password-0000")"
  echo "new password -> $(login "$NEW")"
  unset -f login
}; step7e_login; unset -f step7e_login
```

Expected: `old password -> 401`, `wrong password -> 401`, `new password -> 200`. `old password -> 200`
means the new password is the old one, or block 2 did not recreate the gateway (look at its
`UP_EXIT` and its `hash:` line): run the step again with a different password. `new password
-> 401` means a typing slip in block 1: run the step again. A `429` on any of the three lines is the
sign-in limit, not a wrong password: wait two minutes and run block 3 again; nothing needs to be
redone.

`old password -> 401` shows only that the old password AS YOU TYPED IT HERE is refused: a mistyped
old password prints `401` too. The proof that the old password is dead is block 2's
`hash: file == container (len 86)`: the container holds block 1's new hash and no other, and block
1 hashed only what you typed twice.

If you pasted a password from the password manager, clear the laptop's clipboard after the last
paste, as other steps do: `pbcopy < /dev/null`. Then open the Desktop app, sign in with the new
password, and store it in the password manager.

After this step a review's header shows a new short fingerprint for `dashboard-session-secret`
(the hash is never fingerprinted), and D4.6 shows the gateway container started after the last
PASS: state "BRING-UP step 7e, <date and time UTC>" in the evidence.

### Step 7f: A key of its own for the laptop's forward

Until now the login item that keeps the laptop's forward open used the administrative key, whose
passphrase was in the macOS keychain: an unlocked laptop gave a shell on the box as well as the
dashboard's sign-in page (security review #8, entry 4; finding F57). This step gives the forward a
key of its own that the box limits to ONE thing: a local forward to the dashboard's port,
`127.0.0.1:9119`. The key cannot give a terminal, run a command, transfer a file, open any other
forward, or open a forward in the other direction (to a port other than 1, see the table; port 1
rests on a kernel setting, read by VPS 0 below). Then the administrative key leaves the keychain.

The line on the box carries five options. Each is listed with what was MEASURED for it, against a
throwaway OpenSSH server (Ubuntu 24.04, OpenSSH 9.6p1) with a control key that has no options
(`docs/evaluations/2026-10-07-limited-ssh-key-and-dashboard-password-replacement.md`, section 1):

| Option | What it is for | What was measured |
|---|---|---|
| `restrict` | no terminal, no agent or X11 forwarding, no `~/.ssh/rc` | A terminal request was refused (`PTY allocation request failed`). Agent and X11 forwarding were not run; they rest on the manual. |
| `port-forwarding` | puts forwarding back, which `restrict` removed | The forward to 9119 worked (`200`). |
| `permitopen="127.0.0.1:9119"` | a local forward may reach the dashboard's port and nothing else | A forward to another port was refused, and so was a forward to a unix socket, and so was a forward whose target is the NAME `localhost`: the link must say `127.0.0.1:9119` literally. The control key reached all of them. |
| `permitlisten="127.0.0.1:1"` | `port-forwarding` also puts REMOTE forwarding (`ssh -R`) back; the manual has no "none" form, so a port that cannot be bound stands in for it | A remote forward to any other port was refused outright. A remote forward to port 1 is refused only because an account without privileges cannot bind it, and that depends on the kernel setting `net.ipv4.ip_unprivileged_port_start`: at `0` the listener on `127.0.0.1:1` opened; at `1024`, a host's default, sshd logged `bind [127.0.0.1]:1: Permission denied`. **This one limit rests on that setting**, which review item D1.7 reads at every review. |
| `command="/bin/false"` | `restrict` does not stop `ssh host <command>`; a forced command does. The link uses `ssh -N`, which asks for no command, so it is unaffected | A command, `sftp` and `scp` (both protocols, both directions) were refused, and sshd logged the forced command each time. The control key ran all of them. |

Read on the box itself on 2026-10-08, read-only (the operator's look; `VPS look` below is its
main block): OpenSSH `9.6p1 Ubuntu-3ubuntu13.19`, the release the rehearsals used; the eight sshd
settings listed under `VPS look`; the kernel setting, `1024`. Not measured: the box's `Match`
blocks (counted at the review, "A security review" step 2) and its fail2ban jail, IPv6 and `-D`
forwards, and the refusals with the key the Desktop app's login item will use. LAPTOP 3a and
LAPTOP 3b below are where those refusals are first seen on the real box.

The order rule: **the box runs fail2ban, so a refused login may count against the laptop's address;
nothing that retries by itself is switched to the new key before the hand tests pass.** Whether the
box accepts the new key at all is the first thing tested, by ONE login that is run alone (LAPTOP 3a,
the gate). Nothing else runs until that one login prints the expected line. On a stand-in server
with Ubuntu 24.04's own fail2ban (1.0.2, its packaged settings except `maxretry`, which was raised
to 100 for the rehearsal so that no ban could interfere) one refused key did not raise fail2ban's
count, and a login as a user that does not exist did. The real box's jail was not measured, so this
step treats every refused login as counted. Two of the tests (T5b and T7)
were added after the first rehearsal: T5b because the port-1 limit depends on the kernel setting in
the table, T7 because the first file-transfer test had been written with the wrong port option for
`sftp`, so it failed whatever the key allowed and tested nothing.

How the blocks below were rehearsed (the evaluation's sections 1.8, 1.9 and 1.10 have every run):
`VPS look` is the one block of this step that has already been run on the box itself (by the
operator, as written, on 2026-10-08); it and the other box blocks (`VPS root key`, VPS 0, VPS 1)
ran in an interactive bash on a stand-in server; LAPTOP 1, 2, 3a, 3b and 6 in an interactive zsh
on a stand-in laptop (Linux) against that server; LAPTOP 1b, 4a, 5a and 5b in zsh on this Mac, with
the home directory pointed at a scratch directory. The `ssh-add` lines of LAPTOP 5c and LAPTOP 6b
were run for real on this Mac (macOS 27.0.1, OpenSSH 10.3p1) against the login keychain, with a
throwaway key and a private agent started for the test; they have not been run with the
administrative key or with the agent macOS itself provides. **LAPTOP 4b and 4c could not be run
for real** without changing the real login item: they ran only with `launchctl` replaced by a
stand-in, so their `launchctl` lines run for the first time on this laptop. The same holds for the
one-line stop command after LAPTOP 4c, which was not run at all. Each block says so where it
stands.

**Keep the administrative session on the box open from `VPS look` until the clean-up at the end of this
step, after LAPTOP 6 and LAPTOP 6b have succeeded.** It is
the way back in if anything goes wrong with a key. If that session is lost and `ssh hermes-box` no
longer gets in, the provider's browser terminal still reaches the box without SSH (step 1d, item 5).

`VPS look` (`hermesops@<host>`, the administrative session; run `sudo -v` alone first), read-only:
the sshd settings the limited key depends on, and which accounts hold a key file. **This is the
one block of this step already proven on the box**: the operator ran it there, as written, on
2026-10-08. It was also rehearsed on the stand-in server.

```bash
sudo sh -c 'sshd -T | grep -E "^(authorizedkeysfile|authorizedkeyscommand|trustedusercakeys|authorizedprincipalsfile|allowtcpforwarding|allowstreamlocalforwarding|gatewayports|permittunnel) "; getent passwd | while IFS=: read -r u _ _ _ _ h _; do for f in "$h/.ssh/authorized_keys" "$h/.ssh/authorized_keys2"; do [ -e "$f" ] && echo "$u $(basename "$f") lines=$(grep -cvE "^\s*(#|$)" "$f") types=$(grep -vE "^\s*(#|$)" "$f" | grep -oE "(ssh|ecdsa|sk)-[a-z0-9@.-]+" | sort | uniq -c | tr -s " " | tr "\n" ";") options=$(grep -vE "^\s*(#|$)" "$f" | grep -cvE "^(ssh|ecdsa|sk)-")"; done; done'
```

Expected: ten lines, eight settings and two key files. The values are the ones the box gave on
2026-10-08; the lines are written here as the stand-in server printed them, where the same block
gave the same ten:

- `gatewayports no`
- `allowtcpforwarding yes`
- `allowstreamlocalforwarding yes`
- `trustedusercakeys none`
- `authorizedprincipalsfile none`
- `authorizedkeyscommand none`
- `authorizedkeysfile .ssh/authorized_keys .ssh/authorized_keys2`
- `permittunnel no`
- `root authorized_keys lines=1 types= 1 ssh-ed25519; options=0`
- `hermesops authorized_keys lines=1 types= 1 ssh-ed25519; options=0`

What the parts mean. `authorizedkeysfile` names the two files under each account's `.ssh` folder
that sshd reads keys from. `authorizedkeyscommand none`, `trustedusercakeys none` and
`authorizedprincipalsfile none` say that nothing else can supply an accepted key: no command, no
certificate authority, no principals file. `allowtcpforwarding yes` is what the link needs.
`allowstreamlocalforwarding yes` means sshd itself would allow a forward to a unix socket: the key's
`permitopen` is what refuses it (test T6). `gatewayports no` keeps a forwarded port on the box's own
loopback. `permittunnel no`: no network tunnel device. Each further line is one key file: the
account, the file's name, `lines=` the number of key lines, `types=` how many keys of each type,
`options=` how many of those lines begin with options instead of a key type.

Every other output:

- Fewer than eight setting lines, or a setting that differs from the eight above: stop, do not add
  the key, and report which one.
- A line for an account other than `hermesops`. On 2026-10-08 there was one, `root`: see
  `VPS root key` below. A line for any other account: stop and report it.
- No line for `hermesops`, or a line that says `authorized_keys2`: stop and report it.
- `options=` above `0` before this step has added the limited key: a key line with options is
  already there. Stop and report it. (After VPS 1 the `hermesops` line reads `lines=2 types= 2
  ssh-ed25519; options=1`: rehearsed.)
- `lines=` above `1` for `hermesops` before VPS 1: more than one key is accepted for the
  administrative account. Stop and say whose each one is.
- Anything after `types=` other than the expected text. Before this step adds a key, this box
  prints exactly ` 1 ssh-ed25519;` after `types=` for each file (and ` 2 ssh-ed25519;` for
  `hermesops` after VPS 1). If anything else stands after `types=` on a line, the block's pattern
  has also caught a word of a key's comment when that word looks like a key type (rehearsed: a
  key whose comment is `ecdsa-test` added ` 1 ecdsa-test;`), and a comment can be part of a name
  or a host name. Do NOT paste that line anywhere; say only that the line had something else
  after `types=`, and stop.
- Nothing at all, or a message from `sudo`: run `sudo -v` alone, then the block again.

Rehearsed on the stand-in server (Ubuntu 24.04, OpenSSH 9.6p1, `sudo` with a password typed at
`sudo -v`): as built (the ten lines above); a second account holding a key in each of the two
files (two more lines, one of them `… authorized_keys2 …`); the limited key's line present; a
comment line, an empty line and a second plain key in the `hermesops` file (`lines=2`,
`options=0`); no key file at all (the eight settings and nothing else).

**A key on `root`.** As measured on 2026-10-08, `root` holds one key (`ssh-ed25519`, no options).
Root login is off (`permitrootlogin no`, review item D1.3), so that key cannot be used to log in.
But review item D1.7 fails a key file on an account other than `hermesops` unless the evidence
says whose key it is and why it stays. There are two choices: remove it, with part (b) of the
optional block below; or keep it, and state in every review's evidence whose it is and why it
stays. **The choice is the operator's, and nothing is removed without it.** Part (a) only reads,
and helps with either choice. `VPS root key` does not touch the `hermesops` file.

`VPS root key`, part (a) (optional; `hermesops@<host>`, after `sudo -v` alone), read-only: is
root's key the same key as the first key of `hermesops`? It prints one line and never a key.

```bash
sudo sh -c 'R=/root/.ssh/authorized_keys; H=$(getent passwd hermesops | cut -d: -f6)/.ssh/authorized_keys; body() { grep -vE "^\s*(#|$)" "$1" | awk "{for(i=1;i<NF;i++) if (\$i ~ /^(ssh|ecdsa|sk)-/) {print \$(i+1); next}}"; }; if [ ! -e "$R" ]; then echo "root key: root has no authorized_keys file"; elif [ ! -f "$H" ]; then echo "root key: NOT COMPARED: the hermesops file is missing -- stop"; else n=$(body "$R" | grep -c .); a=$(body "$R" | head -n 1); b=$(body "$H" | head -n 1); if [ "$n" != 1 ] || [ -z "$b" ]; then echo "root key: NOT COMPARED: root holds $n key(s), or the hermesops file holds none -- stop"; elif [ "$a" = "$b" ]; then echo "root key vs the first hermesops key: same"; else echo "root key vs the first hermesops key: different"; fi; fi'
```

Expected: one of two lines, and which one is not known before the block runs (it has not been run
on the box):

- `root key vs the first hermesops key: same`: root's file holds your own administrative key, the
  one you log in with as `hermesops`. That answers "whose it is" for the evidence.
- `root key vs the first hermesops key: different`: root holds a key that is not your
  administrative key. It still gives no way in while root login is off, but nobody has said whose
  it is: stop and report this line before choosing.

What is compared is the key itself (the long word after the key type), not the options before it
or the comment after it. Every other output:

- `root key: root has no authorized_keys file`: there is nothing to compare. If `VPS look` printed
  a `root` line all the same, stop and report both.
- `root key: NOT COMPARED: …` (the `hermesops` file is missing; or root holds a number of keys
  other than one, or the `hermesops` file holds none): stop and report the line.
- Nothing at all, or a message from `sudo`: run `sudo -v` alone, then the block again.

Rehearsed on the stand-in server: root holding the same key (`same`, twice in a row, both files
byte for byte unchanged); another key (`different`); the same key written with options and under a
comment line (`same`); the limited key with its options (`different`); the `hermesops` file
holding the administrative key and then the limited one (`same`); no root file; an empty root
file and two keys on root (`NOT COMPARED: root holds 0 key(s) …`, `… 2 key(s) …`); the
`hermesops` file missing, or holding only a comment. No output held a key.

`VPS root key`, part (b): **ONLY if the operator chose removal** (`hermesops@<host>`, after
`sudo -v` alone). It moves root's key file aside under a name sshd does not read. It deletes
nothing: the moved file is deleted in the clean-up at the end of this step.

```bash
sudo sh -c 'R=/root/.ssh/authorized_keys; M=$R.removed-by-step-7f; if [ -e "$M" ]; then echo "NOT MOVED: $M is already there (this block ran before) -- nothing changed now"; elif [ ! -f "$R" ] || [ -L "$R" ]; then echo "NOT MOVED: $R is missing or is a link -- nothing changed"; elif mv "$R" "$M" && [ ! -e "$R" ] && [ -f "$M" ]; then echo "MOVED: $R -> $M"; else echo "NOT MOVED: the move failed -- stop"; fi; for f in "$R" "${R}2"; do if [ -e "$f" ] || [ -L "$f" ]; then echo "root $(basename "$f"): STILL THERE, lines=$(grep -cvE "^\s*(#|$)" "$f")"; else echo "root $(basename "$f"): no file"; fi; done; [ -e "$M" ] && echo "kept aside: $M" || echo "kept aside: nothing"'
```

Expected, four lines: `MOVED: /root/.ssh/authorized_keys ->
/root/.ssh/authorized_keys.removed-by-step-7f`; `root authorized_keys: no file`;
`root authorized_keys2: no file`; `kept aside: /root/.ssh/authorized_keys.removed-by-step-7f`.
The second and third lines are the proof: root has no file left under either of the two names
`VPS look` showed sshd reading (`authorizedkeysfile`). Then run `VPS look` once more: it must
print no `root` line (rehearsed). If it still prints a `root` line, stop and report it. Every other output:

- `NOT MOVED: … is already there (this block ran before) -- nothing changed now`: fine after an
  earlier run, if the next two lines both say `no file`.
- `NOT MOVED: … is missing or is a link -- nothing changed`: stop and report all four lines.
- `NOT MOVED: the move failed -- stop`, with a message from `mv` above it: nothing was changed.
  Stop and report it. (Rehearsed with a folder made unchangeable: this line, then
  `root authorized_keys: STILL THERE, lines=1`.)
- `STILL THERE, lines=N` on the second or third line: root still has a key file that sshd reads.
  Stop and report it. The block moves `authorized_keys` only; it does not touch an
  `authorized_keys2`.

Rehearsed on the stand-in server: the move (the moved file byte for byte the file from before,
same owner and mode); the block again; no root file; a root file that is a link; an
`authorized_keys2` next to it; a moved file and a new `authorized_keys` both present; the made
failure. That sshd does not accept a key from the moved file was measured there too, with root
login allowed for the test only: a login as `root` with that key got in while the file was in
place, was refused after the move, and got in again after the way back. On the box root login is
off, so this cannot be shown there by a login.

The way back, until the clean-up has run (after `sudo -v` alone):

```bash
sudo sh -c 'R=/root/.ssh/authorized_keys; M=$R.removed-by-step-7f; if [ -e "$R" ] || [ -L "$R" ]; then echo "NOT PUT BACK: $R is there -- nothing changed"; elif [ ! -f "$M" ]; then echo "NOT PUT BACK: $M is missing -- nothing changed"; elif mv "$M" "$R" && [ -f "$R" ]; then echo "PUT BACK: $R, lines=$(grep -cvE "^\s*(#|$)" "$R"), mode $(stat -c %a "$R")"; else echo "NOT PUT BACK: the move failed -- stop"; fi'
```

Expected: `PUT BACK: /root/.ssh/authorized_keys, lines=1, mode 600`. A `NOT PUT BACK: …` line
(the file is there already; the moved file is missing; the move failed): nothing was changed;
stop and report it. Rehearsed: the way back after the move, the way back a second time (`… is
there -- nothing changed`), and after the clean-up (`… is missing -- nothing changed`).

If the key stays: write in the evidence file of every review whose key it is (part (a) says
whether it is your administrative key) and why it stays.

VPS 0 (`hermesops@<host>`, the administrative session), read-only: the kernel setting the table
depends on.

```bash
cat /proc/sys/net/ipv4/ip_unprivileged_port_start
```

Expected: `1024` or more (read on the box on 2026-10-08: `1024`). A smaller number: stop, do not
add the key, and report it.

LAPTOP 1: make the key, and nothing else.

```bash
[ -e ~/.ssh/hermes-box-tunnel ] && echo "EXISTS: not overwritten (fine if you made it a moment ago)" || { ssh-keygen -q -t ed25519 -N "" -C hermes-box-tunnel -f ~/.ssh/hermes-box-tunnel && echo "KEY MADE"; }
```

Expected: `KEY MADE`. `EXISTS: not overwritten …` means the key file is already there: fine if you
made it a moment ago with this block; if you did not, stop and say so. Any other message: stop.

**VPS 1 and LAPTOP 1b, in this order.** Copying a block replaces the clipboard, so the line for the
box cannot be copied first:

1. Paste VPS 1 (below) into the administrative session on the box. It stops at `Paste the line:`
   and waits. Leave it waiting.
2. On the laptop run LAPTOP 1b. It puts the line for the box on the clipboard (the key's comment is
   left out) and says how long the clipboard's content is.
3. Go back to the waiting prompt on the box and paste. The line ends with a line break, so it is
   taken at once.

LAPTOP 1b (it can be run as often as needed):

```bash
printf '%s %s\n' 'restrict,port-forwarding,permitopen="127.0.0.1:9119",permitlisten="127.0.0.1:1",command="/bin/false"' "$(cut -d' ' -f1,2 ~/.ssh/hermes-box-tunnel.pub)" | pbcopy && echo "line on the clipboard: $(pbpaste | wc -c | tr -d ' ') characters"
```

Expected: `line on the clipboard: 182 characters` (181 and a line break). Any other number: do not
paste; the key's public file is missing or is not as LAPTOP 1 made it (rehearsed with the file
missing: `102 characters`). VPS 1 is still waiting at `Paste the line:` on the box: press Return
there, with nothing pasted. Expected: `REFUSED: not the expected line (other options, a cut key, or
extra words) -- nothing written` after about a second, and the shell's prompt again (rehearsed on
the stand-in server: that line, `authorized_keys` byte for byte unchanged, no backup made). Then
stop and say so.

VPS 1 (`hermesops@<host>`, alone; one function and its call):

```bash
tunnel_key_add() {
  local L X N=0 F="$HOME/.ssh/authorized_keys" O='restrict,port-forwarding,permitopen="127.0.0.1:9119",permitlisten="127.0.0.1:1",command="/bin/false"'
  read -r -p "Paste the line: " L
  while read -r -t 1 X; do [ -z "$X" ] || N=1; done
  L=${L%$'\r'}
  [ "$N" = 0 ] || { echo "REFUSED: more than one line was pasted -- nothing written"; return; }
  [ -f "$F" ] || { echo "REFUSED: $F is missing -- nothing written"; return; }
  [ "$L" = "$O ssh-ed25519 ${L##* }" ] && [ ${#L} -eq $(( ${#O} + 81 )) ] || { echo "REFUSED: not the expected line (other options, a cut key, or extra words) -- nothing written"; return; }
  case "${L##* }" in *[!A-Za-z0-9+/]*) echo "REFUSED: the key holds a character that is not base64 -- nothing written"; return;; esac
  grep -qxF "$L" "$F" && { echo "already present: nothing to do"; return; }
  [ -e "$F.before-tunnel-key" ] || cp -p "$F" "$F.before-tunnel-key" || return
  [ -z "$(tail -c1 "$F")" ] || echo >> "$F"
  printf '%s\n' "$L" >> "$F" && echo "ADDED: $(grep -cvE '^\s*(#|$)' "$F") key line(s), mode $(stat -c %a "$F")"
}; tunnel_key_add; unset -f tunnel_key_add
```

Expected: `ADDED: 2 key line(s), mode 600`. `ADDED: 2 key line(s)` assumes the file held exactly one key before. The number to expect is the `lines=` number `VPS look` printed for `hermesops`, plus one (on 2026-10-08: 1, so `ADDED: 2 key line(s)`; D1.7 of a trial collection shows the same count, and "trial collection" is defined in "A security review", step 2); another number is not an error by itself, but stop and say so. `mode` must be `600`: sshd accepts other modes, but review item D1.7 fails them. A mode other than `600` in the `ADDED:` line is this case, not a "stop" case: the key was added. Run `chmod 600 ~/.ssh/authorized_keys; stat -c %a ~/.ssh/authorized_keys` in the administrative session. Expected: `600`. Say that you did it; if it prints anything else, stop and report it. (Rehearsed on the stand-in server with a file of mode 644: `ADDED: 2 key line(s), mode 644`, then `600`.) Every other output:

- `REFUSED: …` (more than one line was pasted; the file is missing; not the expected line; a
  character that is not base64): nothing was written. Run LAPTOP 1b again, paste VPS 1 again, and
  paste the line at its prompt. `more than one line was pasted` is what you get when the clipboard
  still held a block instead of the line: the function swallows the extra lines, so none of them
  runs as a command. If the second try is refused too, stop and report the message.
- `already present: nothing to do`: fine after an earlier successful run.
- No `ADDED` line and none of the above (for example an error from `cp`): stop and report it; the
  function ends before it writes when it cannot make its backup.

The line must be the five options, `ssh-ed25519`, and a key body of exactly 68 base64 characters:
a body cut by one character, a body with one character replaced, a bare key, a fourth word and
other options were each refused in the rehearsal, with the file byte for byte unchanged. Before the
first addition the function copies the file to `~/.ssh/authorized_keys.before-tunnel-key`; a later
addition does not overwrite that copy. Then on the laptop: `pbcopy < /dev/null`.

LAPTOP 2: the alias, with the address copied from the existing one and never printed.

```bash
A=$(ssh -G hermes-box | awk '$1=="hostname"{print $2}'); if grep -q '^Host hermes-box-tunnel$' ~/.ssh/config; then echo "alias exists"; elif [ -z "$A" ]; then echo "STOPPED: could not read the hermes-box alias -- nothing written"; elif [ "$A" = hermes-box ]; then echo "STOPPED: the hermes-box alias has no HostName of its own -- nothing written"; else printf '\nHost hermes-box-tunnel\n  HostName %s\n  User hermesops\n  IdentityFile ~/.ssh/hermes-box-tunnel\n  IdentitiesOnly yes\n  IdentityAgent none\n  ForwardAgent no\n  ServerAliveInterval 30\n  ServerAliveCountMax 3\n' "$A" >> ~/.ssh/config; fi; unset A
ssh -G hermes-box-tunnel | grep -cE '^(identityfile .*/hermes-box-tunnel|identitiesonly yes|identityagent none)$'
```

Expected: `3` (alias exists: it prints `alias exists` first, then `3`). Measured on a stand-in
laptop whose config held only the `hermes-box` block: `3`. A `Host *` block on the real laptop that
sets `IdentityAgent` or `IdentitiesOnly` would change the count (reasoned, not measured). Every
other output:

- `STOPPED: could not read the hermes-box alias -- nothing written`, then `0`: `ssh` could not read
  the `hermes-box` alias (its own message stands above the line; it names a file and a line number,
  not the address). Nothing was written. Stop and report it.
- `STOPPED: the hermes-box alias has no HostName of its own -- nothing written`, then `0`:
  `~/.ssh/config` has no `Host hermes-box` block with a `HostName` line (or there is no such file).
  For a name it has no block for, `ssh -G` answers with the name itself, so the new alias would
  point at the word `hermes-box` and not at the box; the block refuses to write that. Stop and
  report it.

Both were rehearsed on the stand-in laptop: a config with no `hermes-box` block, a `hermes-box`
block with no `HostName` line, no config file, and two configs `ssh` cannot read; each time the
config was byte for byte unchanged and the count was `0`. The same on this Mac's own `ssh` with
scratch configs (all but the missing file). The real `~/.ssh/config` was not read.

A number other than `3` with no `STOPPED` line before it: stop, and do not run
`ssh -G hermes-box-tunnel` by itself (its output holds the address).
Run this instead, which prints only the three settings, and say which one differs from the block
above; do not go on until the key, the agent setting and `IdentitiesOnly` are as that block writes
them:

```bash
ssh -G hermes-box-tunnel | grep -E '^(identityfile|identitiesonly|identityagent) '
```

Expected from it: `identitiesonly yes`, `identityagent none` and `identityfile ~/.ssh/hermes-box-tunnel`.

LAPTOP 3a, the gate: ONE login, alone. Nothing else may run until it prints the expected line.

```bash
ssh -n -o BatchMode=yes -o ConnectTimeout=10 hermes-box-tunnel 'echo MARK' 2>/dev/null; echo "gate rc=$?"
```

Expected: exactly `gate rc=1`. The box accepted the key and ran the forced command (`/bin/false`)
instead of ours. Error text is discarded on purpose: it would print the address. Every other output:

- `gate rc=255`: the box refused the key, or could not be reached. Count it as ONE failed attempt.
  STOP: run nothing else, do not run it again, and report it. (Rehearsed with the key's line taken
  off the stand-in server: `gate rc=255`, and one refused login in that server's log.)
- A line `MARK`, or `gate rc=0`: the key is NOT limited. Stop, and take its line out in the
  administrative session with `cp -p ~/.ssh/authorized_keys.before-tunnel-key ~/.ssh/authorized_keys`.
  (Rehearsed with the key on the stand-in server without its options: `MARK`, `gate rc=0`.)
- Any other number: stop and report it.

LAPTOP 3b, the other tests, only after `gate rc=1` (one function and its call; it takes about half
a minute):

```bash
tunnel_tests() {
  local c
  ssh -o BatchMode=yes -o ExitOnForwardFailure=yes -N -L 29119:127.0.0.1:9119 hermes-box-tunnel 2>/dev/null & sleep 4
  c=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 http://127.0.0.1:29119/); kill $! 2>/dev/null; wait $! 2>/dev/null
  echo "T1 forward to the dashboard -> $c"
  [ "$c" = 302 ] || { echo "STOPPED after T1: the other tests were NOT run"; return; }
  ssh -o BatchMode=yes -o ExitOnForwardFailure=yes -N -L 29122:127.0.0.1:22 hermes-box-tunnel 2>/dev/null & sleep 4
  echo "T4 forward to another port -> $(nc -w 3 127.0.0.1 29122 </dev/null | head -c 20 | wc -c | tr -d ' ') bytes, link $(kill -0 $! 2>/dev/null && echo up || echo DOWN)"; kill $! 2>/dev/null; wait $! 2>/dev/null
  ssh -o BatchMode=yes -o ExitOnForwardFailure=yes -N -R 127.0.0.1:29123:127.0.0.1:22 hermes-box-tunnel 2>/dev/null & sleep 5; if kill -0 $! 2>/dev/null; then kill $!; echo "T5a remote forward, another port -> OPENED (stop: this must be refused)"; else echo "T5a remote forward, another port -> refused"; fi; wait $! 2>/dev/null
  ssh -o BatchMode=yes -o ExitOnForwardFailure=yes -N -R 127.0.0.1:1:127.0.0.1:22 hermes-box-tunnel 2>/dev/null & sleep 5; if kill -0 $! 2>/dev/null; then kill $!; echo "T5b remote forward, port 1 -> OPENED (stop: this must be refused)"; else echo "T5b remote forward, port 1 -> refused"; fi; wait $! 2>/dev/null
  ssh -o BatchMode=yes -o ExitOnForwardFailure=yes -N -L 29124:/run/dbus/system_bus_socket hermes-box-tunnel 2>/dev/null & sleep 4
  echo "T6 unix socket -> $(printf '\0AUTH\r\n' | nc -w 3 127.0.0.1 29124 | wc -c | tr -d ' ') bytes, link $(kill -0 $! 2>/dev/null && echo up || echo DOWN)"; kill $! 2>/dev/null; wait $! 2>/dev/null
  echo "T7 file copy -> rc=$(scp -q -o BatchMode=yes ~/.ssh/hermes-box-tunnel.pub hermes-box-tunnel:/tmp/t7-must-not-arrive 2>/dev/null; echo $?)"
}; tunnel_tests; unset -f tunnel_tests
```

Expected, in this order: `T1 forward to the dashboard -> 302`; `T4 forward to another port -> 0
bytes, link up`; `T5a remote forward, another port -> refused`; `T5b remote forward, port 1 ->
refused`; `T6 unix socket -> 0 bytes, link up`; `T7 file copy -> rc=255`. Lines such as `[2] 1234`,
`[2]  + done ssh …`, `[2]  + terminated ssh …` and `[2]  + exit 255 ssh …` are zsh telling you
about a background `ssh`; they are not results. The block stops a background `ssh` by its process
number and hides the complaint when that `ssh` had already ended, so no `kill: … no such job` line
appears; whether the `ssh` was still running is what `link up` says. Every other output:

- `T1 … ->` anything but `302`, followed by `STOPPED after T1: the other tests were NOT run`: the
  block stopped by itself after ONE login. `000` means the link did not come up: the login was
  refused, the box was not reached, or port 29119 is in use on the laptop. Count it as one failed
  attempt, do not run the block again, and report it. Another code means the dashboard answered
  differently: report the code.
- `link DOWN` on T4 or T6: that test's `ssh` was not running when the test looked, so its `0 bytes`
  proves nothing. Stop and report it.
- More than `0 bytes` on T4 or T6, or `OPENED` on T5a or T5b, or `rc=0` on T7: the key allows what
  it must not. Stop, take its line out in the administrative session
  (`cp -p ~/.ssh/authorized_keys.before-tunnel-key ~/.ssh/authorized_keys`), after `rc=0` also
  delete the file that arrived (`rm -f /tmp/t7-must-not-arrive`, on the box), and report it.
- `T7 file copy -> rc=` another number: stop and report it.

`refused` on T5a and T5b and `rc=255` on T7 are also what a login that failed would print. They
count as results because T1, T4 and T6 of the same run show the key logging in before and after
them (`302`, `link up`, `link up`); if one of those three is not as expected, the other lines prove
nothing. Rehearsed against the stand-in server, whose page answers `302` as the dashboard does:
the six expected lines, six accepted logins and no refused one in that server's log. The same
block with the administrative key gave `20 bytes, link up`, `OPENED`, `13 bytes, link up` and
`rc=0`, so each test can tell allowed from refused; with the key's line taken off the server it
printed `T1 … -> 000` and `STOPPED after T1`, and the server logged ONE refused login. macOS's own
`nc`, `curl` and `ssh` against a real server were not rehearsed: pasted into zsh on this Mac the
block ran only with `ssh`, `scp` and `curl` replaced by stand-ins.

LAPTOP 4a: the login item's file, only after every line of LAPTOP 3b is as expected. It changes
the file's tenth argument from `hermes-box` to `hermes-box-tunnel`, and changes nothing when the
file is not the one the README describes (ten arguments, the last one `hermes-box`).

```bash
P=~/Library/LaunchAgents/com.dentaledge.hermes-box-tunnel.plist; K=~/hermes-box-tunnel.plist.before-tunnel-key; B=/usr/libexec/PlistBuddy
N=$($B -c 'Print :ProgramArguments' "$P" 2>/dev/null | grep -c .); A=$($B -c 'Print :ProgramArguments:9' "$P" 2>/dev/null)
if [ "$N" = 12 ] && [ "$A" = hermes-box ]; then command cp -p "$P" "$K" && $B -c 'Set :ProgramArguments:9 hermes-box-tunnel' "$P" >/dev/null 2>&1; [ "$($B -c 'Print :ProgramArguments:9' "$P" 2>/dev/null)" = hermes-box-tunnel ] && echo "SWITCHED IN THE FILE" || echo "NOT SWITCHED: the change did not reach the file -- stop"; elif [ "$N" = 12 ] && [ "$A" = hermes-box-tunnel ]; then echo "ALREADY SWITCHED: nothing changed"; else echo "NOT SWITCHED: the file is not as expected -- stop"; fi
A=$($B -c 'Print :ProgramArguments:9' "$P" 2>/dev/null); case "$A" in hermes-box-tunnel|hermes-box) echo "the alias the login item uses: $A";; *) echo "the alias the login item uses: something else (not shown)";; esac; unset P K B N A
```

Expected: `SWITCHED IN THE FILE`, then `the alias the login item uses: hermes-box-tunnel`. Every
other output:

- `ALREADY SWITCHED: nothing changed`, with `hermes-box-tunnel` on the second line: the block was
  run before. Go on.
- `NOT SWITCHED: the file is not as expected -- stop`: nothing was changed. The second line says
  which of three things stands in the tenth place: `hermes-box-tunnel`, `hermes-box`, or
  `something else (not shown)`. What it is, is not printed on purpose: a login item written with
  `user@address` instead of an alias would print the address. Stop and report both lines.
- `NOT SWITCHED: the change did not reach the file -- stop`: the file could not be written. Stop
  and report it.
- A second line that does not end in `hermes-box-tunnel`: stop. LAPTOP 4b and LAPTOP 5c refuse to
  run in that state, and must not be made to.

The file as it was is kept as `~/hermes-box-tunnel.plist.before-tunnel-key`, in the home directory
and not next to the login item (whether macOS would read a second file in that folder was not
measured). Rehearsed on scratch copies of a file built from the README's ten arguments: the good
file (ten arguments before and after, the tenth changed, every other value equal; the tool writes
the keys back in another order); a second run; a file with one more `-o` pair; no file; a file that
could not be written (second line: `hermes-box`); a file whose tenth argument is written
`user@host` (second line: `something else (not shown)`, as for the extra pair and for no file).
`plutil -replace` is not used: on this macOS it inserted an eleventh argument
instead of replacing the tenth (measured in the review of this runbook).

LAPTOP 4b: reload the login item, only after LAPTOP 4a's second line reads `hermes-box-tunnel`.
**First run on this laptop, not rehearsed**: the rehearsal replaced `launchctl` by a stand-in, so
only the block's own check and its order were run.

```bash
P=~/Library/LaunchAgents/com.dentaledge.hermes-box-tunnel.plist
if [ "$(/usr/libexec/PlistBuddy -c 'Print :ProgramArguments:9' "$P" 2>/dev/null)" = hermes-box-tunnel ]; then launchctl bootout gui/$(id -u)/com.dentaledge.hermes-box-tunnel; sleep 3; launchctl bootstrap gui/$(id -u) "$P"; echo "RELOADED: bootstrap rc=$?"; else echo "NOT RELOADED: the file does not name hermes-box-tunnel -- stop"; fi; unset P
```

Expected: `RELOADED: bootstrap rc=0`. A message from `launchctl bootout` before it (the item was
not loaded) is not a failure by itself. Every other output:

- `NOT RELOADED: the file does not name hermes-box-tunnel -- stop`: LAPTOP 4a did not switch the
  file. Nothing was touched. Do not go on to the next block.
- `RELOADED: bootstrap rc=` another number (`rc=5`, for example): this is NOT a success, although
  the line begins with `RELOADED`. Only `rc=0` is. One of two things is then true. Either the login
  item is not loaded now: the link and the Desktop app are down and nothing is retrying. Or
  `launchctl bootout` failed and the OLD definition is still loaded: the old item keeps running on
  the administrative key, which still works. LAPTOP 4c's counts tell which (`ssh on the old alias:
  1` is the second). The box is not affected in either case. Run LAPTOP 4b once more. If the number
  is again not `0`, run LAPTOP 4c, then stop and report both outputs; do not go on to LAPTOP 5a.

LAPTOP 4c: is the link up, and on which alias? Read-only; it can be run again. **First run on this
laptop, not rehearsed for real**: its `launchctl print` ran only as a stand-in, and the other two
lines ran with another port number against a scratch page and stand-in processes.

```bash
launchctl print gui/$(id -u)/com.dentaledge.hermes-box-tunnel | grep -E '^\s*state = '
curl -s -o /dev/null -w 'dashboard through the link -> %{http_code}\n' --max-time 5 http://127.0.0.1:19119/
echo "ssh on the new alias: $(pgrep -f '19119:127\.0\.0\.1:9119 hermes-box-tunnel$' | wc -l | tr -d ' '); ssh on the old alias: $(pgrep -f '19119:127\.0\.0\.1:9119 hermes-box$' | wc -l | tr -d ' ')"
```

Expected: `state = running`; `dashboard through the link -> 302`; `ssh on the new alias: 1; ssh on
the old alias: 0`. Every other output:

- No `state = ` line, or another state; or a code other than `302`; or `ssh on the new alias: 0`
  (no forward is running on the new key): the login item starts its `ssh` at most once every two
  minutes. Wait two minutes and run LAPTOP 4c again, ONCE. If any of the three is still not as
  expected, do not go on to the next block, and FIRST stop the login item (below), then report.
- `ssh on the old alias:` anything but `0`: a forward on the administrative key is still running.
  After LAPTOP 5c the box would refuse its next login every two minutes. Stop and report it; do not
  go on to the next block. (LAPTOP 5c counts these processes again and refuses to run while there
  is one.)

**To stop the login item, so that nothing retries by itself.** After LAPTOP 4b the item is loaded
on the new key, and macOS starts its `ssh` again every two minutes for as long as it is loaded:
each start is a login at the box. When the second run of LAPTOP 4c is still not as expected, run
this before you report anything. **First run on this laptop, not rehearsed** (it is the stop
command the README gives for the login item; what it prints was not seen):

```bash
launchctl bootout gui/$(id -u)/com.dentaledge.hermes-box-tunnel
```

Then run LAPTOP 4c once more and report its lines with the rest: both counts must now be `0`, and
there must be no `state = running` line. What this leaves: the link and the Desktop app are down;
nothing is retrying; the administrative key is untouched (its passphrase is still in the keychain,
because LAPTOP 5b and 5c have not run), and `ssh hermes-box` works as before.

To go back to the working state from before the laptop part of this step, two commands, in this
order: `command cp -p ~/hermes-box-tunnel.plist.before-tunnel-key ~/Library/LaunchAgents/com.dentaledge.hermes-box-tunnel.plist`
puts back the file as LAPTOP 4a found it (rehearsed on a scratch copy, with `cp` set up to ask: no
question, the file byte for byte as before, its tenth argument `hermes-box`), and
`launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.dentaledge.hermes-box-tunnel.plist`
starts the login item from it (the README's start command; **not rehearsed**). The old alias still
works at this point, because nothing of LAPTOP 5b and 5c has run. Then LAPTOP 4c must print
`state = running`, `302` and `ssh on the new alias: 0; ssh on the old alias: 1`. The new key's line
stays on the box; it harms nothing there.

LAPTOP 5a: a check of the passphrase, BEFORE anything is removed (alone: it asks). It makes no
connection; it only opens the key file on the laptop.

```bash
ssh-keygen -y -f ~/.ssh/vps-hermes >/dev/null && echo "PASSPHRASE OK" || echo "NOT OK: stop, nothing was changed"
```

Expected: it ASKS (`Enter passphrase for "…/.ssh/vps-hermes":`), you type the administrative key's
passphrase, and it prints `PASSPHRASE OK`. Every other output:

- `NOT OK: stop, nothing was changed` (after `incorrect passphrase supplied`): the passphrase you
  typed is not the key's. It asks once; run it again for a typing slip. Without `PASSPHRASE OK`
  nothing further runs: taking the keychain's copy away would leave a key nobody can open.
- `PASSPHRASE OK` WITHOUT having asked: stop. Either the key has no passphrase or something
  answered for you, and the check proved nothing. (Rehearsed: a key with no passphrase prints
  `PASSPHRASE OK` without asking.)
- No line at all (you pressed Ctrl+C): nothing was proven. Run it again.

Rehearsed on this Mac with a scratch key: the right passphrase, a wrong one, Return alone, Ctrl+C,
a key with no passphrase, no key file. Not shown: whether the keychain can answer this prompt for
the real key, which is why it must be seen to ask.

LAPTOP 5b: the two settings leave the `hermes-box` alias. Without that, the next typed passphrase
would be stored in the keychain again. The edited text goes to a new file first; `~/.ssh/config` is
replaced only when every step before it worked, and the file as it was is kept as
`~/.ssh/config.before-tunnel-key`.

```bash
C=~/.ssh/config
if [ -e "$C.before-tunnel-key" ]; then echo "A BACKUP EXISTS: this block was run before -- nothing changed now"; elif [ ! -f "$C" ] || [ -L "$C" ]; then echo "NOT EDITED: ~/.ssh/config is missing or is a link -- stop"; elif awk '{k=tolower($1); sub(/=.*/,"",k)} k=="host"||k=="match"{inblk=(k=="host" && NF==2 && $2=="hermes-box")} !(inblk && (k=="usekeychain"||k=="addkeystoagent"))' "$C" >| "$C.new" && chmod 600 "$C.new" && cp -p "$C" "$C.before-tunnel-key" && mv -f "$C.new" "$C"; then echo "EDITED: $(( $(grep -c '' "$C.before-tunnel-key") - $(grep -c '' "$C") )) line(s) removed"; else echo "NOT EDITED: a command failed -- stop"; fi
ssh -G hermes-box | grep -i '^addkeystoagent '; echo "UseKeychain lines left in the file: $(grep -ciE '^[[:space:]]*usekeychain([[:space:]=]|$)' "$C" 2>/dev/null)"; unset C
```

Expected: `EDITED: 2 line(s) removed`, `addkeystoagent false`, `UseKeychain lines left in the file: 0`.
Every other output:

- `EDITED: 1 line(s) removed` or `EDITED: 0 line(s) removed`: the `hermes-box` block held only one
  of the two settings, or none, or it is not written `Host hermes-box` on a line of its own. The
  two lines that follow decide.
- `A BACKUP EXISTS: this block was run before -- nothing changed now`: nothing was changed this
  time. The two lines that follow show the state: as expected, go on.
- `NOT EDITED: ~/.ssh/config is missing or is a link -- stop`, or `NOT EDITED: a command failed --
  stop`: `~/.ssh/config` is unchanged (rehearsed: byte for byte). Stop and report it.
- `addkeystoagent` anything but `false`: another block that also applies to `hermes-box` (a
  `Host *` block, for example) sets it. Stop and report it; do not go on to the next block.
- `UseKeychain lines left in the file:` anything but `0`: a `UseKeychain` line stands somewhere
  else in the file. macOS's `ssh -G` does not print this setting (measured on this Mac), so the
  block cannot tell whether that line applies to `hermes-box`. Stop and report the number; do not
  go on to the next block.

To put the file back as it was: `command cp -p ~/.ssh/config.before-tunnel-key ~/.ssh/config`
(written with `command` so that a `cp` set up to ask before it overwrites does not stop to ask).
Rehearsed on scratch files with this Mac's own `awk` and zsh: a config where the block is followed
by `HOST` and `MATCH` in capitals, an indented `Host`, a `Match`, `hermes-box-tunnel` and
`hermes-box other` blocks (exactly two lines removed, every other line byte for byte); a second
run; zsh's `noclobber`; `UseKeychain=yes` and a block written `Host=…`; `cp`, `mv` and `rm` set up
to ask; a made failure; a config that is a link; no config.

LAPTOP 5c: only now, the administrative key leaves the agent and the keychain (one function and
its call). Run it only after LAPTOP 4c printed its three expected lines and LAPTOP 5a printed
`PASSPHRASE OK` after asking. **Its three `ssh-add` lines were rehearsed for real on this Mac**
(macOS 27.0.1, OpenSSH 10.3p1, the login keychain) **with a throwaway key and a private agent
started for the test. They have NOT been run with the administrative key or with the agent macOS
itself provides: for that key this is their first run.** What the rehearsal showed: the first
line asked for the throwaway key's passphrase once and stored it (run again on an emptied agent,
the same line added the key without asking); the second line took the key out of the agent, and
the keychain no longer supplied it; the third line printed `keychain load rc=0` and `supplied by
the keychain: 0`. Run BEFORE the removal, that third line printed `supplied by the keychain: 1`,
so the last count can tell the two states apart. The function as a whole (its three refusals and
the order of its lines) ran only with `ssh-add` replaced by a stand-in that drops the two
`--apple-…` options and talks to a scratch agent. The line that counts `ssh` processes was run
with another port number (`39119`) against stand-in processes, as in LAPTOP 4c.

```bash
keychain_out() {
  local FP K="$HOME/.ssh/vps-hermes"
  [ "$(/usr/libexec/PlistBuddy -c 'Print :ProgramArguments:9' "$HOME/Library/LaunchAgents/com.dentaledge.hermes-box-tunnel.plist" 2>/dev/null)" = hermes-box-tunnel ] || { echo "STOPPED: the login item's file does not name hermes-box-tunnel -- nothing removed"; return; }
  [ "$(pgrep -f '19119:127\.0\.0\.1:9119 hermes-box$' | wc -l | tr -d ' ')" = 0 ] || { echo "STOPPED: an ssh on the old alias (hermes-box) is still running -- nothing removed"; return; }
  FP=$(ssh-keygen -lf "$K.pub" 2>/dev/null | awk '{print $2}')
  [ -n "$FP" ] || { echo "STOPPED: could not read $K.pub -- nothing removed"; return; }
  ssh-add --apple-use-keychain "$K"; echo "in the agent before: $(ssh-add -l | grep -cF "$FP")"
  ssh-add --apple-use-keychain -d "$K"; echo "in the agent after: $(ssh-add -l | grep -cF "$FP")"
  ssh-add --apple-load-keychain >/dev/null 2>&1; echo "keychain load rc=$?"; echo "supplied by the keychain: $(ssh-add -l | grep -cF "$FP")"
}; keychain_out; unset -f keychain_out
```

Expected: `Identity added: …`, `in the agent before: 1`, `Identity removed: …`, `in the agent
after: 0`, `keychain load rc=0`, `supplied by the keychain: 0`. If the first line asks for the
passphrase (the keychain did not hold it, as on a second run), type it: that line stores it and the
next line removes it again. Every other output:

- `STOPPED: the login item's file does not name hermes-box-tunnel -- nothing removed`: LAPTOP 4a
  was not done. Stop; with the key gone the login item would be refused every two minutes.
- `STOPPED: an ssh on the old alias (hermes-box) is still running -- nothing removed`: the FILE
  names the new alias, but macOS runs the definition it LOADED, and an `ssh` of the old one is
  still there: LAPTOP 4b's reload did not take. Stop, run LAPTOP 4c, and report its lines.
  (Rehearsed with a stand-in process: this line, and the stand-in for `ssh-add` received no call.
  The count is also `0` when `pgrep` itself cannot run; LAPTOP 4c's `ssh on the new alias: 1`, just
  before, is what shows that it can.)
- `keychain load rc=` anything but `0`: the laptop could not ask the keychain, so the
  `supplied by the keychain: 0` under it proves nothing. Stop and report both lines; do not go on
  to LAPTOP 6. (Rehearsed with a stand-in that ends with `1`: `keychain load rc=1`, then `0`.
  Measured for real on this Mac with the throwaway key: `rc=0` both while the keychain held that
  key's passphrase and after it was removed; in every one of those runs the keychain still
  supplied one other key. Not measured: what the real `ssh-add --apple-load-keychain` ends with
  when the keychain holds no SSH passphrase at all, which is the state here if the administrative
  key's was the only one stored. `rc=0` is what is expected of it; if the laptop prints another
  number in that state, this stop is a false alarm, and it is still the right thing to report.) At this point the key has already left the agent and the keychain. You are not locked out: the first administrative session is still open, and LAPTOP 5a showed that you can type the passphrase. Report it before going on.
- `STOPPED: could not read …/vps-hermes.pub -- nothing removed`: the key's public file is missing.
  Stop and report it.
- `in the agent before: 0`: the key could not be loaded, so the removal had nothing to act on.
  Report it together with the last line.
- `in the agent after:` anything but `0`: the key is still in the agent. Stop and report it.
- `supplied by the keychain:` anything but `0`: the keychain still holds the passphrase, and the
  key is in the agent again. Stop and report it; do not go on to LAPTOP 6.

The last line asks the keychain for every passphrase it holds, so any other key whose passphrase is
stored there is in the agent afterwards, as it is after a login (from the manual; in the rehearsal
with the throwaway key, measured as a count only: an emptied private agent held one key that was
not the throwaway key after this line).
The key is counted by its fingerprint, which is read from the public file and never printed:
`ssh-add -l` lists fingerprints and comments, not file names.

LAPTOP 6: the proof that you still have a way in. Alone; it asks for the passphrase.

```bash
ssh hermes-box
```

Expected: it asks (`Enter passphrase for key '…/.ssh/vps-hermes':`), you type it, and you are at a
prompt on the box. Type `exit` to come back. Every other output:

- You are at the box's prompt WITHOUT having typed the passphrase: something still supplies it.
  Type `exit`, run LAPTOP 6b, and report both.
- `Permission denied`, or no prompt on the box: do NOT close the first administrative session.
  Describe the message, do not paste it (it prints the address). Put the config back
  (`command cp -p ~/.ssh/config.before-tunnel-key ~/.ssh/config`), put the passphrase back where it
  was with `ssh-add --apple-use-keychain ~/.ssh/vps-hermes` (it asks for the passphrase; rehearsed
  on this Mac with a throwaway key: it asked once, and afterwards the keychain supplied that
  passphrase without asking; not run with the real key), and report it. Do not try more than once more: on the stand-in server three wrong
  passphrases at this prompt reached the server as ONE closed connection.
- If the first session is already gone and this does not get in: the provider's browser terminal
  (step 1d, item 5) is the way back.

Rehearsed on the stand-in laptop with a throwaway key that has a passphrase: the right passphrase
(a prompt on the server), a wrong one three times, Ctrl+C. Not rehearsed: the same on macOS, where
the keychain could answer.

LAPTOP 6b: after `exit`, on the laptop: did that login put the key back (one function and its
call)? **Its `ssh-add` lines were rehearsed for real on this Mac with a throwaway key and a
private agent, as for LAPTOP 5c. They have NOT been run with the administrative key, with the
agent macOS itself provides, or after a real login** (LAPTOP 6 has not been run on macOS); the
function as a whole ran with stand-ins only.

```bash
keychain_check() {
  local FP K="$HOME/.ssh/vps-hermes"
  FP=$(ssh-keygen -lf "$K.pub" 2>/dev/null | awk '{print $2}')
  [ -n "$FP" ] || { echo "STOPPED: could not read $K.pub"; return; }
  echo "in the agent after the login: $(ssh-add -l | grep -cF "$FP")"
  ssh-add --apple-load-keychain >/dev/null 2>&1; echo "keychain load rc=$?"; echo "supplied by the keychain after the login: $(ssh-add -l | grep -cF "$FP")"
}; keychain_check; unset -f keychain_check
```

Expected: `in the agent after the login: 0`, `keychain load rc=0` and `supplied by the keychain
after the login: 0`. These counts are only meaningful if `ssh-add -l` reached the agent: a line "Could not open a connection to your authentication agent" above them means it did not; stop and report. Every other output:

- `STOPPED: could not read …/vps-hermes.pub`: report it.
- `keychain load rc=` anything but `0`: the laptop could not ask the keychain, so the `0` under it
  proves nothing. Stop and report both lines; the step is not complete, and the clean-up below
  waits. (Rehearsed with a stand-in that ends with `1`. Measured for real with the throwaway key:
  `rc=0` with that key's passphrase not in the keychain, while the keychain supplied one other
  key. With no SSH passphrase at all in the keychain: not measured, as in LAPTOP 5c.)
- `in the agent after the login:` anything but `0`: `AddKeysToAgent` still applies to `hermes-box`,
  and the key stays in the agent until you log out of the laptop. Take it out with
  `ssh-add -d ~/.ssh/vps-hermes` (not rehearsed) and report it.
- `supplied by the keychain after the login:` anything but `0`: `UseKeychain` still applies to
  `hermes-box`, and the passphrase is in the keychain again. The step is NOT complete. Report it;
  do not run LAPTOP 5c again by yourself.

ONLY when LAPTOP 6 got you to the box's prompt by typing the passphrase, AND LAPTOP 6b printed its
three expected lines: remove the three backups, then close the first administrative session. On
the box, in the FIRST administrative session (the one kept open since `VPS look`; the session LAPTOP 6
opened was closed with `exit`): `rm -f ~/.ssh/authorized_keys.before-tunnel-key`. On the laptop:
`rm -f ~/.ssh/config.before-tunnel-key ~/hermes-box-tunnel.plist.before-tunnel-key`. ONLY if part
(b) of `VPS root key` was run (the operator chose removal): also delete the file it moved aside,
on the box, in the first administrative session, after `sudo -v` alone:
`sudo sh -c 'M=/root/.ssh/authorized_keys.removed-by-step-7f; rm -f "$M"; [ -e "$M" ] && echo "STILL THERE: $M -- stop" || echo "the moved file is gone"'`.
Expected: `the moved file is gone` (rehearsed on the stand-in server, also a second time; it
prints the same line when there was no such file, so run it only after part (b)). After it the
way back of `VPS root key` no longer works. Then type `exit` in the first administrative session.

After this step a review's D1.7 shows two keys for `hermesops`: one with no options and one with the five limited options. Put in the evidence file: whose each key is (the administrative key; the forward's key made in this step, with the date), and the `Match` count of "A security review" step 2. If root's key was kept, D1.7 also shows a row for `root`: the evidence says whose that key is and why it stays, at every review. If root's key was removed with `VPS root key`, say so in the evidence file, with the date: the review then shows one key file, `hermesops`'s. The first review after this step has no earlier header to compare the keys' short fingerprints with; from the next one on the report header carries them.

For a work session with several connections, `ssh-add -t 1h ~/.ssh/vps-hermes` keeps the key in
memory for an hour and stores nothing in the keychain. To replace the limited key later: make a new
one, add its line, test, switch, then delete the old line; the next review's D1.7 shows a new
`sha12`, and the evidence says so.

---

## What This Runbook Does Not Do

- Create the Hermes users (`hermes`, `hermes-broker`, `hermes-docker-proxy`, `hermes-rail`) or
  groups. The README "VPS deploy sequence" owns this.
- Install the systemd units. The README "VPS deploy sequence" owns this.
- Provision real credentials. Mutation stays disabled.
- Enable the kill switch. The handoff's §6 owns this.

---

## What Is Proven, and What Phase 1 Is the First to Prove

`provision.sh` is covered by the tests in `provision.test.py`: text assertions about the
script's contents plus behavioural tests driven by **mock executables**.

**First real run: 2026-09-21**, Ubuntu 24.04.4 LTS, x86_64, Docker 29.8.1, compose 5.5.1.
`provision.sh` applied cleanly, and `--check` reported **17 checks, all passed, exit 0**
against real `ufw`, `sshd`, `getent` and Docker. Root login was shown refused from outside, not
only reported as `no`. What the real box found that the mocks could not, all recorded above
and in the findings record:

- **The deploy user has no usable sudo** (step 1b-2). `--check` passed because it tests group
  membership, not usability. This is the same class as every earlier defect: it was in the
  code that *verifies*, not the code that acts.
- **apt waits on the box's own unattended-upgrades** on first boot. Harmless.
- **`data/` and `data/skills` are root-owned on Linux.** Docker Desktop's ownership remapping
  hid this on the laptop.
