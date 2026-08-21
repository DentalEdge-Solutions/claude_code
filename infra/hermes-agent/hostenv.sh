# Host-side environment for the mutation rail. SOURCED (never executed) by
# run-ads-mutate.sh and changeset.sh; the sourcing script sets `here` to its own
# directory first.
#
# WHY THIS EXISTS. `HERMES_GOVERNANCE_DIR` is documented in `.env` and `.env.example`,
# but `.env` is Docker Compose *interpolation* input: Compose reads it when rendering
# docker-compose.yml, the shell does not, and nothing exports it. So anything that
# needs the value shell-side has to read the file itself. Without that, the README's
# own documented sequence could not run — `run-ads-mutate.sh` refused at its R4 guard
# with the variable "unset", and `propose-changeset.py` / `approve-changeset.py`
# resolved CONTAINER paths (`/opt/governance/registry/clients.json`, `/opt/data/vaults`)
# and died with "client registry not found".
#
# `.env` is parsed as DATA, never sourced — the same rule run-ads-mutate.sh applies to
# `.env.gaw`, and the rule this capsule writes down. Only `HERMES_GOVERNANCE_DIR` is
# read; every other line, including every credential, is ignored and never evaluated.
#
# An explicit environment value always wins over `.env`, so a one-off run against a
# different store stays a prefix on the command line.

if [ -z "${HERMES_GOVERNANCE_DIR:-}" ] && [ -f "$here/.env" ]; then
  while IFS= read -r _line || [ -n "$_line" ]; do
    case "$_line" in
      HERMES_GOVERNANCE_DIR=*) : ;;
      *) continue ;;
    esac
    _val=${_line#HERMES_GOVERNANCE_DIR=}
    case "$_val" in
      \"*\") _val=${_val#\"}; _val=${_val%\"} ;;
      \'*\') _val=${_val#\'}; _val=${_val%\'} ;;
    esac
    HERMES_GOVERNANCE_DIR=$_val
  done < "$here/.env"
fi

# R4 guard: an unset or empty value makes Docker Compose substitute "" for
# ${HERMES_GOVERNANCE_DIR} in docker-compose.yml, which would bind-mount /approvals,
# /control, /registry and /log at the FILESYSTEM ROOT. Refuse before anything runs.
if [ -z "${HERMES_GOVERNANCE_DIR:-}" ]; then
  echo "hermes: HERMES_GOVERNANCE_DIR is unset or empty — refusing (an empty value would make Docker Compose bind-mount the governance paths at the filesystem root). Set it in $here/.env (see .env.example) or pass it as a command prefix." >&2
  exit 1
fi
case "$HERMES_GOVERNANCE_DIR" in
  /*) : ;;
  *) echo "hermes: HERMES_GOVERNANCE_DIR must be an ABSOLUTE path (got '$HERMES_GOVERNANCE_DIR'); Compose does not expand ~" >&2; exit 1 ;;
esac

# The two roots every host-side tool in this tier resolves paths from. governance_lib
# and vault_lib both default to the CONTAINER paths, which is correct in the executor
# and wrong on the host — these overrides are what make the host tools address the
# same store the container does.
export HERMES_GOVERNANCE_DIR
export HERMES_GOVERNANCE_ROOT="$HERMES_GOVERNANCE_DIR"
export VAULT_ROOT="$here/data/vaults"
