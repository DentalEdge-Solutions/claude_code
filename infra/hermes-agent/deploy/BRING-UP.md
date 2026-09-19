# VPS Bring-Up: From a Bought Box to Docker-Ready

> **For provisioning an Ubuntu 24.04 box on Hostinger KVM 2 and running the systemd units
> listed in the README at line 957.** This runbook covers phases 0–5 (buying and hardening
> the host, the on-box layout these units require, `.env`, the compose build, and the bind-path
> measurement); it then hands off to the README sequence.

Spec: `docs/superpowers/specs/2026-09-18-vps-provisioning-and-bring-up-design.md`

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

```bash
scp -i ~/.ssh/vps-hermes provision.sh root@<ip>:~/
```

### Step 1b: Run as root (via the root console session)

Keep the **original root SSH session open** — do not close it yet. If SSH hardening goes
wrong, this is your only recovery path.

```bash
DEPLOY_USER=hermesops SSH_PUBKEY="ssh-ed25519 AAAA..." bash ~/provision.sh
```

Replace `ssh-ed25519 AAAA...` with the full content of `~/.ssh/vps-hermes.pub` (the one
line, from `ssh-ed25519` to the trailing comment).

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
  OK    sshd: passwordauthentication no
  OK    sshd: permitrootlogin no
  OK    sshd: kbdinteractiveauthentication no
  OK    sshd: pubkeyauthentication yes
  OK    firewall active
  OK    default incoming policy is deny
  OK    no inbound rule beyond SSH
  OK    fail2ban running
  OK    docker running
  OK    docker group has no members beyond hermes-docker-proxy
[provision] all checks passed (12 checks)
```

### Step 1d: Lockout protocol (SSH hardening is dangerous)

1. **Keep the root session open.** Do not close it.
2. In a **second terminal**, prove `ssh hermesops@<ip>` works with the key:
   ```bash
   ssh -i ~/.ssh/vps-hermes hermesops@<ip> 'id'
   ```
   You should see output like `uid=1002(hermesops) gid=1003(hermesops) groups=...`.

3. Prove `sudo` works as `hermesops`:
   ```bash
   ssh -i ~/.ssh/vps-hermes hermesops@<ip> 'sudo -v'
   ```
   This should exit cleanly with no output.

4. **Only then** close the root session. If you get locked out after this, skip to recovery
   below.

5. **If you are locked out:** Hostinger's browser console (VPS → Overview → Browser terminal)
   does not use SSH, so you can still reach the box. Log in as root there and reconcile the
   issue.

### Step 1e: Verify the gid-10000 precondition (before README:957 runs)

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
| `/opt/hermes-agent` | `bin/`, `registry/`, `data/spool` | `hermes-broker.service:17,22,27,29`; `hermes-docker-proxy.service:26,37,38` |
| `/var/lib/hermes/governance` | the governance store | `hermes-broker.service:20,21,28,36`; `hermes-docker-proxy.service:32-35` |

As `hermesops` (or under `sudo`):

```bash
# Create the directories
sudo mkdir -p /opt/projects
sudo mkdir -p /opt/hermes-agent
sudo mkdir -p /var/lib/hermes

# Clone the repos to /opt/projects
cd /opt/projects
sudo git clone <url-to-claude_code-repo> claude_code
sudo git clone <url-to-claude-google-ads-repo> claude-google-ads

# Set up /opt/hermes-agent
# You can either copy the repo's infra/hermes-agent or symlink it.
# Open question (phase 5 measures): whether a symlink satisfies Docker's bind-source comparison.
# For now, we recommend a symlink:
sudo ln -s /opt/projects/claude_code/infra/hermes-agent /opt/hermes-agent

# OR copy it:
# sudo cp -r /opt/projects/claude_code/infra/hermes-agent /opt/hermes-agent

# Create the governance store, mode 700
sudo mkdir -p /var/lib/hermes/governance
sudo chmod 700 /var/lib/hermes/governance
```

**Important:** `/opt/hermes-agent` and `/opt/projects/claude_code/infra/hermes-agent` must end
up being the same directory (either by symlink or by copy). Whether a symlink satisfies Docker's
bind-source comparison is the **open question phase 5 measures** — do not assume it either way.

---

## Phase 3: `.env`

Copy the example to `.env`:

```bash
cd /opt/hermes-agent
cp .env.example .env
```

Edit `.env` and set:

```bash
ANTHROPIC_API_KEY=dummy-key-this-wave
HERMES_GOVERNANCE_DIR=/var/lib/hermes/governance
```

Two prohibitions:

- **Never run `docker compose config`** — it renders `env_file` secrets in cleartext to stdout.
- **No real client credentials this wave.** Use dummy values. Real money-spending credentials
  are gated behind a security review that is downstream of this runbook.

---

## Phase 4: Build and Start

```bash
cd /opt/hermes-agent
sudo docker compose up -d --build
```

Then run the README "First run" smoke checks (README.md:957, step 5 onwards):

```bash
hermes gateway status
claude --version
```

Both should complete without error.

---

## Phase 5: Measure the Bind Paths

This phase measures the bind sources Docker Compose sends to the allow-list proxy. The proxy
is not running yet, so its log is not the instrument; instead, we inspect the container's
`HostConfig.Binds` after it is created but before it starts.

```bash
sudo docker compose --profile tools create ads-mutator
CONTAINER_ID=$(sudo docker ps -a --filter "name=ads-mutator" --format "{{.ID}}")
sudo docker inspect "$CONTAINER_ID" --format '{{json .HostConfig.Binds}}'
```

This returns a JSON array of strings like:

```json
["/var/lib/hermes/governance/approvals:/opt/governance/approvals:ro",
 "/var/lib/hermes/governance/control:/opt/governance/control:ro",
 ...]
```

Each bind source (the part before the colon) must exactly match one of the seven `--allow-bind`
values in `hermes-docker-proxy.service:32-38`:

```bash
sed -n '32,38p' /opt/hermes-agent/deploy/hermes-docker-proxy.service
```

Expected (from the design spec):
- `/var/lib/hermes/governance/approvals`
- `/var/lib/hermes/governance/control`
- `/var/lib/hermes/governance/registry`
- `/var/lib/hermes/governance/log`
- `/opt/projects/claude-google-ads`
- `/opt/hermes-agent/registry`
- `/opt/hermes-agent/bin`

**On any mismatch:** stop here. Record the finding. Do not widen the allow-list. A rail that
refuses is a refusal, not a breach, and widening a policy to make bring-up pass is the reflex
the handoff's §3 and §5 name explicitly. The mismatch is worth investigating — it may reveal
that the symlink strategy (or copy strategy) needs adjustment, or that Compose resolves paths
differently than expected.

Clean up:

```bash
sudo docker rm "$CONTAINER_ID"
```

---

## Phase 6: Hand Off

Once the bind paths match (or are reconciled), hand off to:

1. `README.md:957` steps 1–5 (create the Hermes users and groups, install the systemd units,
   run the preflight checks)
2. `docs/superpowers/handoffs/2026-09-17-vps-deploy-and-remeasurement.md` §2–§5 (the 2026-09-17
   handoff sequence)

**Note:** This runbook does not create the kill switch, and mutation stays disabled throughout.
The handoff's §6 gates (F3 hardening, `UMask=0077`, audit-log truncation) are where the kill
switch lives.

---

## What This Runbook Does Not Do

- Create the Hermes users (`hermes`, `hermes-broker`, `hermes-docker-proxy`, `hermes-rail`) or
  groups. The README:957 sequence owns this.
- Install the systemd units. The README:957 sequence owns this.
- Provision real credentials. Mutation stays disabled.
- Enable the kill switch. The handoff's §6 owns this.

---

## What Is Proven, and What Phase 1 Is the First to Prove

`provision.sh` is covered by 50 tests in `provision.test.py`, all green. But they are text
assertions about the script's contents plus behavioural tests driven by **mock executables**
(`ensure_*` and `check_*` functions are tested against fixtures), verified against upstream
formats. **No artifact here has ever run on a Linux host.**

The hardening is textually correct, the guards are reachable, and the refusals work as written.
But `bash provision.sh --check` on the real box in phase 1 is the first time any of it is
observed against a real system, against real `ufw`, real `sshd`, real `getent`, and a real
Docker install.
