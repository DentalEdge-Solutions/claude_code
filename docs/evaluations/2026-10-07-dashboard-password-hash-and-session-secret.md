# Evaluation — the dashboard's hashed password and session-signing secret on Hermes v0.21.5

> **Date:** 2026-10-07 · **Asked:** can the box drop the plaintext dashboard password from the gateway `.env`
> (finding F47) and stop signing the operator out at every gateway restart, now that the Desktop app is the
> everyday client? · **Answer:** yes to both, with one trap: the hash must be written so that Docker Compose
> does not rewrite it. **Method:** official documentation read on 2026-10-07, the image's own source, and
> measurements on the laptop against the derived v0.21.5 image in an isolated Compose project (local-first
> canon). Nothing in the repo's code or on the box was changed by this evaluation; the test container and its
> volume were removed afterwards.

## 1 · Sources, authority and what each verified (accessed 2026-10-07)

| Source | Authority | Verified there |
|---|---|---|
| [Hermes docs: Web dashboard](https://hermes-agent.nousresearch.com/docs/user-guide/features/web-dashboard) | primary | `HERMES_DASHBOARD_BASIC_AUTH_PASSWORD_HASH` is the preferred form ("no plaintext at rest"), scrypt, format `scrypt$16384$8$1$…$…`, computed with `hash_password` from `plugins.dashboard_auth.basic`. The plaintext `HERMES_DASHBOARD_BASIC_AUTH_PASSWORD` wins over a hash. `HERMES_DASHBOARD_BASIC_AUTH_SECRET` is the token-signing key; unset, a random one is generated per process, so sessions end at a restart. `HERMES_DASHBOARD_BASIC_AUTH_TTL_SECONDS` defaults to 12 hours. |
| Image source, `hermes_cli/dashboard_auth/routes.py` and `plugins/dashboard_auth/basic/` (image `hermes-eval-derived:v0.21.5`, base digest as pinned in the Dockerfile) | primary | `POST /auth/password-login` takes `provider`, `username`, `password`; `GET /api/auth/me` needs a session; `GET /api/auth/providers` lists the provider. Access tokens last 12 hours and refresh tokens 30 days (`_DEFAULT_TTL_SECONDS`, `_REFRESH_TTL_SECONDS`). A native client's sign-in goes through the same form with a broker handle, which is why the Desktop app records its sign-in type as `oauth`. |
| `infra/hermes-agent/docker-compose.yml` | repo | The gateway reads `.env` through `env_file:`, so Compose parses every value. |
| `infra/hermes-agent/bin/install-env-secret.py` | repo | `set` writes `NAME=value` as typed, unquoted, and needs a `--prefix`. |

## 2 · Measurements (laptop, 2026-10-07, isolated Compose project, dashboard on a spare loopback port)

Test values only: user `measure`, a throwaway password, a throwaway signing secret.

| What was measured | Result |
|---|---|
| The hash generated inside the image | `scrypt$16384$8$1$<salt>$<hash>`, 86 characters, with `$`, `/`, `+` and `=` |
| The hash written raw into the `env_file` | **Corrupted, silently.** The container received 39 characters: Compose treated `$<salt>` and `$<hash>` as variables and replaced them with nothing, with only a warning on `up` ("variable is not set. Defaulting to a blank string"). The `$16384$8$1` part survived because a variable name cannot start with a digit. |
| The hash written with every `$` doubled (`$$`) | The container received the exact hash; no warning |
| The hash written inside single quotes | The container received the exact hash; no warning |
| Sign-in with the hash and no plaintext variable | wrong password 401, right password 200, `GET /api/auth/me` 200 with the session and 401 without |
| Session after a gateway restart, **no** signing secret | 401: signed out |
| Session after a restart, and after a recreate, **with** the signing secret (a base64 value written raw) | 200 both times: still signed in. The secret reached the container unchanged. |
| Both the plaintext variable and the hash set, with different passwords | the hash's password 401, the plaintext password 200: the plaintext wins, as documented |

Not measured: the Desktop app itself against a hashed password (only the HTTP sign-in it uses); a base64 secret
that happens to contain a character Compose treats specially (base64 has no `$`).

## 3 · What this means for the box

1. **F47 can be fixed.** The gateway `.env` can hold the hash and no plaintext password.
2. **The hash must be single-quoted (or `$$`-escaped) in the gateway `.env`.** Written raw it is truncated
   and nobody can sign in. `install-env-secret.py` writes raw today, so it needs a way to write a quoted value,
   and the rollout must check the value in the running container before the old password is removed.
3. **The plaintext line must be removed in the same step.** While it is present it wins, and the hash does
   nothing.
4. **A signing secret keeps the Desktop app signed in across restarts.** It is one more secret in the gateway
   `.env`: the review collector must list it and search for it, and the checklist must expect it.
5. **Both changes alter what D2.1 and D4.1 expect**, so they go with a checklist version bump and a review.
