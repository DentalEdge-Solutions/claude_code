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
- **Real clone**, only after the review: a read-only deploy key scoped to that one repo,
  generated on the VPS. Never a token in the clone URL — it lands in `.git/config` in plaintext.

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
systemctl show -p ProtectHome -p NRestarts hermes-broker                                 # ProtectHome=tmpfs, NRestarts=0
sudo systemd-run --quiet --pipe --wait --collect -p User=hermes-broker -p ProtectHome=tmpfs \
  docker compose version; echo rc=$?                                                     # Docker Compose version v…, rc=0
```

Only the broker unit changes; the proxy unit is untouched and needs no `cp`. Then continue the
rehearsal below **from step 4**: attempt 1's approval is consumed and cannot be reused.

### Running the rehearsal

**Attempt 1 (2026-09-25) stopped at step 6 — F22.** Steps 0–5 matched; the request came back
`failed`/`failed_unverified_exit`, exit 4: Compose, run by the broker under its sandbox, could
not find its own plugin (compose rc=125, no container created). Nothing could have been touched
(kill switch absent, dummy credential, fake customer id; log 0 lines, no run record). The fix is
F22 ("After pulling F22" above). After it, re-run **from step 4** in a fresh session: first set
`cd /opt/hermes-agent; G=/var/lib/hermes/governance` (step 0's first two lines). `rehearsal` is
already registered and sealed, and the dummy `.env.gaw` is already installed.


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
`exit_code 4` (`failed_unverified_exit`) is also a finding, not a hazard: this is the first time
the wrapper runs Compose inside the broker unit's sandbox (Phase 6 ran it from a shell), and the
kill switch is absent either way. Record it with step 7's journal output; change nothing.

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

### Before creating the kill switch

The rehearsal never checked the credential. Before `control/mutation-enabled` is ever created:
put the **real** WRITE credential in `/opt/hermes-agent/.env.gaw` as its own deliberate step
(`install -o hermes-broker -g hermes-broker -m 0600`, never pasted into a chat or a doc), and
register the first real client with `--bootstrap-logs --apply` so its log is sealed (§6B). When
adding that client, **merge** it into `clients.json` and keep the `rehearsal` entry (status
`retired`) — do not reuse the rehearsal's replace-the-whole-file commands.
Creating the kill switch itself remains the operator's decision.

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
  sudo install -m 600 .env.new .env && sudo rm -f .env.new && echo "WRITTEN len=${#P}"
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

The Hermes Desktop app is out of scope. Whether it can authenticate against this gated
dashboard has not been measured.

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
