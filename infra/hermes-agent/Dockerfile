# Derived Hermes Agent image.
#
# Purpose: the official Nous Hermes Agent image + the Claude Code CLI, so Hermes
# can run `claude -p` inside mounted project directories (terminal.backend: local).
# The official base image's install tree (/opt/hermes) is immutable at runtime,
# so tools like `claude` must be added in a derived image (documented pattern).
#
# Pinned to v2026.7.20 (Hermes Agent v0.19.0 "Quicksilver") — digest verified by the
# P0 security audit on 2026-07-21 (see infra/hermes-agent/SECURITY-AUDIT.md).
# Re-pin AND re-run the audit on every upgrade (Hermes ships ~weekly; :latest is a
# moving target retagged on every push to main — never build against :latest).
FROM nousresearch/hermes-agent@sha256:f7b35053268f532f98955195c909f15a230470fbcbdacaa9fdecb95707dad04a

USER root

# Claude Code CLI — Node 22 is present in the base image.
RUN npm install -g @anthropic-ai/claude-code && claude --version

# Auth bootstrap for the Hermes-launched `claude` executor. Hermes scrubs the
# env of terminal subprocesses, so `claude` reads its key from settings.json at
# HOME=/opt/data/home; this script materializes it from $ANTHROPIC_API_KEY.
# Run once by the `claude-auth-init` compose sidecar before the gateway starts.
COPY bootstrap-claude-auth.sh /usr/local/bin/bootstrap-claude-auth.sh
RUN chmod 0755 /usr/local/bin/bootstrap-claude-auth.sh

# Read-execute (Increment 3): a pinned, isolated venv carrying the target's Google
# Ads reader deps, so run-ads-report.py can execute reader scripts without pip or
# runtime network. Deps pinned from a vendored copy of the target's requirements
# (resync + rebuild on target churn). Built as root; world-readable so the hermes
# UID (10000) can execute it. Isolated from the Hermes base python.
COPY ads-requirements.txt /opt/ads-requirements.txt
RUN python3 -m venv /opt/ads-venv \
 && /opt/ads-venv/bin/pip install --no-cache-dir -r /opt/ads-requirements.txt \
 && /opt/ads-venv/bin/python3 -c "import google.ads.googleads, dotenv; print('ads-venv OK')"

# Drop back to the non-root runtime user shipped by the base image (UID 10000).
# NOTE: verify the username (`hermes`) against the base image before building.
USER hermes
