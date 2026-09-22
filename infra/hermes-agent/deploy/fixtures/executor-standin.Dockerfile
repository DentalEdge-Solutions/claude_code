# CI ONLY — a stand-in for hermes-agent-claude, built by bind-agreement-integration.test.py.
# The proxy pins the image NAME and the entrypoint `python3 /opt/cc-bin/apply-changeset.py`
# (docker-create-proxy.py PINNED_ENTRYPOINT); the executor and its libraries are stdlib-only,
# so an official python image runs the REAL executor from the bind-mounted bin/. uid 10000
# matches the real image's `USER hermes`. What this does NOT prove: anything about the real
# image (its Python, its layers) — BRING-UP Phase 6 runs the real image on the box.
FROM python:3.12-slim@sha256:2f17fc044b579bab302c2e8054d3a686e2cb9a83de48e70534b94cd8ebbe06a9
RUN groupadd -g 10000 hermes && useradd -u 10000 -g 10000 -M -s /usr/sbin/nologin hermes
USER hermes
