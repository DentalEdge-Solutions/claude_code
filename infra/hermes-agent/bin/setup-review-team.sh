#!/bin/sh
# Create the four confined review-team profiles (idempotent). Each profile is
# no-skills, described for its role, and confined at the GROUP level via its own
# config.yaml: allow-list platform_toolsets.cli=[file, skills] + a deny-list of
# every dangerous group (agent.disabled_toolsets). kanban is auto-injected for
# kanban workers. Run inside the container (HERMES_HOME=/opt/data).
set -eu
PROFILES_ROOT="${HERMES_HOME:-/opt/data}/profiles"

# The deny-list: every configurable group that a read-only analyst must NOT hold.
DENY='terminal, code_execution, browser, web, delegation, computer_use, memory, vision, image_gen, video, video_gen, x_search, tts, todo, context_engine, session_search, cronjob, homeassistant, spotify, discord, discord_admin, yuanbao'

set_profile() {  # name  description
  name="$1"; desc="$2"
  hermes profile show "$name" >/dev/null 2>&1 || hermes profile create "$name" --no-skills
  hermes profile describe "$name" --text "$desc" || true
  cfg="$PROFILES_ROOT/$name/config.yaml"
  mkdir -p "$PROFILES_ROOT/$name"
  # Merge the confinement keys into any existing config.yaml (idempotent).
  DENY="$DENY" python3 - "$cfg" <<'PY'
import os, sys
try:
    import yaml
except Exception:
    yaml = None
path = sys.argv[1]
deny = [t.strip() for t in os.environ["DENY"].split(",") if t.strip()]
data = {}
if yaml and os.path.exists(path):
    with open(path) as f:
        data = yaml.safe_load(f) or {}
data.setdefault("platform_toolsets", {})["cli"] = ["file", "skills"]  # allow-list
data.setdefault("agent", {})["disabled_toolsets"] = deny             # deny-list
if yaml:
    with open(path, "w") as f:
        yaml.safe_dump(data, f, default_flow_style=False, sort_keys=False)
else:  # stdlib fallback — write a minimal valid YAML
    with open(path, "w") as f:
        f.write("platform_toolsets:\n  cli: [file, skills]\n")
        f.write("agent:\n  disabled_toolsets: [" + ", ".join(deny) + "]\n")
print("confined:", path)
PY
  # A kanban worker runs under its profile's HERMES_HOME, so it resolves skills
  # from the profile's OWN skills dir ($HERMES_HOME/profiles/<name>/skills), not
  # the global mount. Symlink the read-only reviewer skill in so `--skill
  # claude-code-reviewer` resolves for the worker (idempotent). Without this the
  # worker crashes at spawn with "Unknown skill(s): claude-code-reviewer".
  mkdir -p "$PROFILES_ROOT/$name/skills"
  ln -sfn "${HERMES_HOME:-/opt/data}/skills/claude-code-reviewer" \
    "$PROFILES_ROOT/$name/skills/claude-code-reviewer"
  echo "profile ready: $name"
}

set_profile architect     "Read-only software architecture analyst: structure, boundaries, coupling, design risks. Never writes."
set_profile test-analyst  "Read-only test/quality analyst: coverage gaps, test design, CI. Never writes."
set_profile risk-analyst  "Read-only risk/security analyst: failure modes, unsafe patterns, security gaps. Never writes."
set_profile synthesizer   "Read-only synthesis coordinator: fuses specialist handoffs into one prioritized improvement proposal. Never writes."
