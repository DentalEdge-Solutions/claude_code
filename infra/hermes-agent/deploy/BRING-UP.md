# VPS Bring-Up: From a Bought Box to Docker-Ready

> **For provisioning an Ubuntu 24.04 box on Hostinger KVM 2 and running the systemd units
> listed in the README at line 957.** This runbook covers phases 0–5 (buying and hardening
> the host, the on-box layout these units require, `.env`, the compose build, and the bind-path
> measurement); it then hands off to the README sequence. Phase 7 covers reaching the
> dashboard from a laptop.

Spec: `docs/superpowers/specs/2026-09-18-vps-provisioning-and-bring-up-design.md`
First real run (2026-09-21), and every correction below that it earned:
`docs/superpowers/specs/2026-09-21-vps-first-bring-up-findings.md`

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

In a `hermesops@<host>` session:

```bash
sudo mkdir -p /opt/projects /var/lib/hermes
# claude_code is public — no credential on the box for it
sudo git clone https://github.com/DentalEdge-Solutions/claude_code.git /opt/projects/claude_code
sudo ln -s /opt/projects/claude_code/infra/hermes-agent /opt/hermes-agent
sudo install -d -m 700 /var/lib/hermes/governance
# verify
sudo git -C /opt/projects/claude_code log -1 --oneline     # must equal origin/main
readlink -f /opt/hermes-agent                               # /opt/projects/claude_code/infra/hermes-agent
sudo stat -c '%a %U:%G %n' /var/lib/hermes/governance       # 700 root:root
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

Copy the example to `.env` at mode 600 and set the dummy key. `HERMES_GOVERNANCE_DIR`
already defaults to `/var/lib/hermes/governance` in the example.

```bash
sudo install -m 600 /opt/hermes-agent/.env.example /opt/hermes-agent/.env
sudo sed -i 's/^ANTHROPIC_API_KEY=$/ANTHROPIC_API_KEY=dummy-key-this-wave/' /opt/hermes-agent/.env
# verify — key NAMES only, never values
sudo grep -Ev '^\s*(#|$)' /opt/hermes-agent/.env | cut -d= -f1       # ANTHROPIC_API_KEY, HERMES_GOVERNANCE_DIR
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
phase 5 — the wrong order: if compose had resolved paths from the symlink lexically, the
gateway's `../..` mount would have been the host root, and `up` would have started a container
with it. `create` builds containers without running them, and `inspect` shows only paths (this
is not `docker compose config`; no secret is rendered).

```bash
cd /opt/hermes-agent && sudo docker compose build; echo "BUILD_EXIT=$?"
sudo docker compose create hermes-agent
sudo docker inspect $(sudo docker compose ps -a -q hermes-agent) --format '{{range .HostConfig.Binds}}{{println .}}{{end}}'
sudo docker compose down
```

Every source must be under `/opt/projects/`. Measured 2026-09-21 — identical from
`/opt/hermes-agent` and from the physical path, i.e. compose **resolves** the symlink:
`/opt/projects/claude_code:/projects/claude_code:ro`,
`/opt/projects/claude-google-ads:/projects/claude_google_ads:ro`,
`/opt/projects/claude_code/infra/hermes-agent/{bin,registry,data,skills/...,masks/empty}`.
Any source of `/` or outside `/opt/projects/` is a stop.

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

**Result of the first run (2026-09-21): MISMATCH — open.** Compose resolves the symlink, so
`./bin` and `./registry` arrive as `/opt/projects/claude_code/infra/hermes-agent/{bin,registry}`,
not the allow-listed `/opt/hermes-agent/{bin,registry}` (`hermes-docker-proxy.service:37-38`);
the proxy requires the bind set to equal the pinned set exactly (`docker-create-proxy.py:231-232`). The ads-repo entry matches.
No layout satisfies all three today: a real directory at `/opt/hermes-agent` fixes `bin` and
`registry` but sends `../../../claude-google-ads` to `/claude-google-ads`. This was measured on
the `hermes-agent` service, which uses the same relative forms; `ads-mutator` itself was
**not** created, because creating it before README step 2 would make Docker lay down the
governance subdirectories as root. Mutation is disabled, so this blocks nothing yet; the fix
is a design change landed by PR, not an allow-list edit on the box.

---

## Phase 6: Hand Off

**Blocked as of 2026-09-21 — do not start until the layout below is designed and landed.**
README step 1 (users and groups) was run and verified. Step 2 onwards assumes a governance
store that already has content; on a fresh box nothing creates it:

- `approvals/`, `control/`, `registry/`, `log/`, `seen/` and `registry/clients.json` are only
  ever created by `migrate()` from existing local vaults. The VPS has none.
  `--bootstrap-logs` deliberately refuses a missing `log/` (`migrate_governance_shim.py:153`).
- The store's **owner** is unspecified beyond "deploy/broker user" (README:894), but the
  broker writes `seen/`, `approvals/` and `control/.locks/`.
- `data/spool/` must exist for the broker unit's `ReadWritePaths=`, is written by uid 10000
  and read, deleted and quarantined by `hermes-broker` — and `data/` is `700` uid 10000.
  The spool is the only channel between agent and broker, so its permissions are a security
  design decision, not a bring-up chmod.

The pre-flight, run as `hermes-broker` against the empty store, refuses (exit 2) — correctly —
but cannot distinguish "missing" from "unreadable", and its suggested fix `chmod`s a `log/`
that does not exist yet.

Once the bind paths match (or are reconciled) **and the store/spool layout is landed**, hand
off to:

1. `README.md:957` steps 1–5 (create the Hermes users and groups, install the systemd units,
   run the preflight checks)
2. `docs/superpowers/handoffs/2026-09-17-vps-deploy-and-remeasurement.md` §2–§5 (the 2026-09-17
   handoff sequence)

**Note:** This runbook does not create the kill switch, and mutation stays disabled throughout.
The handoff's §6 gates (F3 hardening, `UMask=0077`, audit-log truncation) are where the kill
switch lives.

---

## Phase 7: Reach the Dashboard From the Laptop

Independent of phase 6 — needs only the phase 4 stack. Verified end to end on 2026-09-21.

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
  groups. The README:957 sequence owns this.
- Install the systemd units. The README:957 sequence owns this.
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
