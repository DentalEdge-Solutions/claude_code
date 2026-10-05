# Derived Hermes Agent image.
#
# Purpose: the official Nous Hermes Agent image + the Claude Code CLI, so Hermes
# can run `claude -p` inside mounted project directories (terminal.backend: local).
# The official base image's install tree (/opt/hermes) is immutable at runtime,
# so tools like `claude` must be added in a derived image (documented pattern).
#
# Pinned to v2026.9.24 (Hermes Agent v0.21.5), digest verified and the image audit re-run
# on 2026-10-05 (see infra/hermes-agent/SECURITY-AUDIT.md); previous pin v2026.7.20 (v0.19.0).
# Re-pin AND re-run the audit on every upgrade (Hermes ships ~weekly; :latest is a
# moving target retagged on every push to main — never build against :latest).
FROM nousresearch/hermes-agent@sha256:fca358f12efd65bfaaca05884166f15c0e2788375ca30d77061ac1ebc96452b7

USER root

# Claude Code CLI — Node 26 is present in the base image (v0.21.5).
RUN npm install -g @anthropic-ai/claude-code && claude --version

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
