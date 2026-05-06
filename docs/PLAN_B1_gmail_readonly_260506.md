# B1 Implementation Plan — Read-only Gmail for Type 1

**Date planned:** 2026-05-06
**Status:** Planned, not yet executed.
**Strategic context:**
- Strategic build plan: `/Users/harry/p51_automator_project_info/p521_agentic_workflows/awf1_build_plan_260505.md` (Track B section).
- Scoping doc with locked-in decisions: `docs/track_b_gmail_workspace_scoping_260426.md`.
- Memory: `feedback_product_over_technical_shortcut.md` (the "don't tell customers to configure Gmail in Apple Mail.app" rationale that drove Track B in the first place).

## Goal

Add read-only Gmail support to the email category. Type 1 (Email Topic Monitor) becomes the first workflow type that can run against either Apple Mail (existing) or Gmail (new). Send/draft Gmail support (types 5 and 6) is deferred to B2.

## Design decisions confirmed in `docs/track_b_gmail_workspace_scoping_260426.md`

1. One GCP project per customer. Cognosa does NOT operate a shared GCP project.
2. Workspace-first ship; consumer @gmail.com deferred.
3. Per-user OAuth first; domain-wide delegation deferred to B3.
4. Phase B1 ships only the `gmail.readonly` scope. Send/compose scopes added in B2.

Harry walks through the customer setup checklist in his own dev GCP project as part of B1 verification (see scoping doc § "Customer-side setup"). Code lands first; end-to-end run blocked on env vars until then.

## New design decisions surfaced during planning (resolved 2026-05-06)

1. **Where the encryption key lives.** AES-GCM with key from env var `TOKEN_ENCRYPTION_KEY` (32-byte base64; renamed from the scoping doc's Gmail-specific name since the same helper will later wrap type-4 connection strings). Generate a key once for dev (`python -c 'import os, base64; print(base64.b64encode(os.urandom(32)).decode())'`), put it in `.env`, document that production deployments must generate their own and never share.

2. **Ship code without GCP creds set.** The backend should boot fine without `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` / `GOOGLE_REDIRECT_URI` set. The OAuth-start endpoint returns 503 with detail "Gmail integration not configured on this server" until they're present. This means we can ship B1.1–B1.6 incrementally; only B1's verification step needs the env vars.

3. **OAuth state-signing mechanism.** OAuth's `state` param needs to be tamper-proof. Cheapest: sign with the existing `SECRET` config var via JWT (or HMAC). Alternative: store a server-side state row keyed by random nonce. JWT is simpler and matches how the rest of the app handles signed payloads. Going with JWT-signed state containing `{user_id, exp, nonce}`.

4. **Token-refresh strategy.** The Gmail API access token expires after ~1 hour; the refresh token is long-lived. Decision: `gmail_client` lazily refreshes when an access token call returns 401, using the stored refresh token. Re-encrypts the new access token to DB. If the refresh token itself has been revoked at Google's side, mark the account as `disconnected` and surface to the user.

5. **Type 4 secrets reuse.** The plan-plan said `backend/services/secrets.py` would also wrap the type-4 plaintext `connection_string`. B1 ships ONLY the helper; actually migrating type 4's existing rows is a separate small phase ("type-4 connection_string encryption") not blocked by B1. Surfacing here so we don't conflate scopes.

6. **Frontend Connections page placement.** Top-level nav item (side menu) at `/app/connections`. Confirmed.

7. **Account-picker conditional on service.** Type 1's existing form uses a hand-tuned branch in `WorkflowConfigForm.tsx`. Adding Gmail means: (a) a new `service: "apple_mail" | "gmail"` select at the top of the type 1 form; (b) when `service === "gmail"`, the `account` field becomes a Gmail-account dropdown populated from `/api/v1/gmail/accounts`; otherwise it stays the existing apple-mail account select. Implemented inside the existing typeId === 1 branch — no schema-driven generic conditional needed.

8. **Audit log scope.** The scoping doc said every `gmail_client.py` call writes a `gmail_token_usage` row with `(account_id, workflow_id, run_id, action, timestamp)`. workflow_id and run_id may be NULL when the call is made outside a workflow context (e.g., listing accounts, OAuth flow itself). Allow nullable.

## Commit boundaries

Ten commits. Each independently shippable (with the OAuth-start endpoint returning 503 until env vars are set). No commit relies on GCP creds being present.

---

### B1.1 — Encryption helper

**New file** `backend/services/secrets.py`:

- `encrypt(plaintext: str) -> bytes` — AES-GCM with 12-byte random nonce. Returns `nonce || ciphertext || tag`.
- `decrypt(blob: bytes) -> str` — Reverse.
- Reads the 32-byte key from env `TOKEN_ENCRYPTION_KEY` (base64-decoded). Raises `RuntimeError` at import time if not set, with a clear message.
- Uses `cryptography` library (`Cipher(algorithms.AES(key), modes.GCM(nonce))`).

**New dependency** in `backend/requirements.txt`: `cryptography>=42.0` (already a transitive dep of `fastapi-users`; pin explicitly so the secrets module's import doesn't depend on transitives).

**Verification:** unit-style script: encrypt + decrypt a known string, assert equality. Verify two encrypt calls of the same plaintext produce different ciphertexts (unique nonce).

Reversible — pure additive. Importing `secrets.py` requires the env var; no other module imports it yet.

---

### B1.2 — Migration: gmail_accounts + gmail_token_usage

**Alembic migration** at `backend/alembic/versions/<new>_gmail_tables.py`:

Creates two tables.

`gmail_accounts`:
- `id` BIGSERIAL PK
- `user_id` INT FK → `api_users.user_id`
- `group_id` INT FK → `api_groups.group_id` (denormalized for query convenience; consistent with other tables)
- `email` VARCHAR(255) NOT NULL — the account's Gmail address
- `refresh_token_encrypted` BYTEA NOT NULL
- `access_token_encrypted` BYTEA — nullable (refreshed lazily)
- `access_token_expires_at` TIMESTAMPTZ — nullable
- `scopes` TEXT NOT NULL — space-separated, e.g. `"https://www.googleapis.com/auth/gmail.readonly"`
- `status` VARCHAR(20) NOT NULL DEFAULT `'active'` — one of `active | disconnected | revoked`
- `created_at` TIMESTAMPTZ NOT NULL DEFAULT now()
- `last_used_at` TIMESTAMPTZ — nullable
- UNIQUE(`user_id`, `email`) — a user can connect a given Gmail address once.

`gmail_token_usage`:
- `id` BIGSERIAL PK
- `account_id` BIGINT FK → `gmail_accounts.id`
- `workflow_id` INT — nullable
- `run_id` INT — nullable
- `action` VARCHAR(50) NOT NULL — e.g. `list_messages`, `get_message`, `search`, `oauth_refresh`, `oauth_connect`, `oauth_revoke`
- `timestamp` TIMESTAMPTZ NOT NULL DEFAULT now()
- `error_detail` TEXT — nullable
- INDEX on (`account_id`, `timestamp` desc) for "recent activity" queries.

**Verification:** apply locally, `\d gmail_accounts` and `\d gmail_token_usage` show expected schemas, FKs in place.

---

### B1.3 — Models for gmail_accounts + gmail_token_usage

**Code edit** at `backend/db/models.py`: add `GmailAccounts` and `GmailTokenUsage` SQLAlchemy classes mirroring the migration. Standard `Mapped[]` typing per existing patterns.

**Pydantic schemas** at `backend/db/schemas.py`: `GmailAccountRead` (omits encrypted-token columns and the refresh token; surfaces `email`, `status`, `created_at`, `last_used_at`, `scopes` as a list).

**Verification:** import the models in a Python REPL, run a SELECT, no errors.

Reversible — pure additive.

---

### B1.4 — OAuth flow endpoints

**New file** `backend/api/gmail_oauth.py`:

- Reads `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REDIRECT_URI` from `backend/config.py` (added there with defaults of empty string).
- `POST /api/v1/gmail/oauth/start` — auth required. Constructs the Google OAuth URL with the readonly scope, signs a state JWT containing `{user_id, exp: now+10min, nonce}` using existing `SECRET`. Returns `{auth_url}`. If env vars missing, returns 503.
- `GET /api/v1/gmail/oauth/callback` — receives `code` and `state`. Verifies state JWT and matches `user_id` to the currently-authenticated user. Exchanges `code` for tokens via `google-auth-oauthlib`. Calls `userinfo` to get the connected email. Encrypts and persists to `gmail_accounts` (UPSERT on user_id+email — re-connecting an existing account replaces tokens). Logs `oauth_connect` to `gmail_token_usage`. Redirects to `/app/connections?connected=<email>`.
- `GET /api/v1/gmail/accounts` — auth required. Returns `[GmailAccountRead]` for the current user.
- `DELETE /api/v1/gmail/accounts/{id}` — auth required + ownership check. Calls Google's revoke endpoint with the refresh token (best-effort; logs success/failure). Logs `oauth_revoke`. Soft-deletes the row by setting `status='revoked'` (preserves audit history). The unique constraint allows reconnecting the same email later.

**Wire-up** in `backend/api/__init__.py`.

**New dependencies**: `google-auth-oauthlib>=1.2`, `google-api-python-client>=2.130` in `requirements.txt`.

**Verification:** with env vars set, `POST /api/v1/gmail/oauth/start` returns a Google URL; clicking it through to consent and back produces a row in `gmail_accounts` with encrypted tokens; `GET /accounts` lists it; `DELETE /accounts/{id}` removes/revokes. Without env vars, `/oauth/start` returns 503 with a clear message.

---

### B1.5 — gmail_client.py

**New file** `backend/services/gmail_client.py`:

- `gmail_list_messages(account_id, query, max_results, workflow_id=None, run_id=None) -> list[dict]` — equivalent to `mcp_client.mail_list_messages`. Returns `[{id, snippet, from, subject, date}]`.
- `gmail_get_message(account_id, message_id, workflow_id=None, run_id=None) -> dict` — full message with body, headers.
- `gmail_search(account_id, query, max_results, ...)` — alias for list with a query.
- All three: load the `GmailAccount`, decrypt access token, call Gmail API. On 401, refresh via the refresh token, re-encrypt, retry. On refresh failure, mark account `status='disconnected'` and raise.
- Each call writes a `gmail_token_usage` row with `action`, optional `workflow_id`/`run_id`, and `error_detail` if the call failed.

**Verification:** with a real connected account, `gmail_list_messages` returns recent inbox messages. With a deliberately-corrupted access token (and a valid refresh token), the function refreshes and succeeds. With both tokens revoked at Google, the account flips to `disconnected` and the call raises.

---

### B1.6 — email_monitor.py: gmail branch

**Code edit** at `backend/services/workflows/email_monitor.py`:

- Read `service = config.get("service", "apple_mail")`.
- If `service == "apple_mail"`: existing logic unchanged.
- If `service == "gmail"`: read `account_id = config["account_id"]` (an integer — the gmail_accounts.id). Call `gmail_client.gmail_list_messages(account_id, ...)`. Same downstream LLM categorization.
- The existing config field name `account` (a string like "iCloud") stays for apple_mail; for gmail, a new field `account_id` (int) is used. Cleaner than overloading one field.

**Type 1 config_schema migration** — add a new field descriptor for `service` (select: apple_mail | gmail) and update the schema accordingly. Existing rows whose config has no `service` default to `apple_mail` (handled by the engine's `.get("service", "apple_mail")`).

**Verification:** an existing type 1 workflow with no `service` field runs unchanged. A new type 1 workflow with `service: "gmail"` and `account_id: <id>` runs against Gmail and produces the same Excel digest.

---

### B1.7 — Connections page

**New file** `frontend/src/pages/Connections.tsx`:

- Lists the current user's connected Gmail accounts via `GET /gmail/accounts`.
- "Connect a Gmail account" button posts to `/gmail/oauth/start`, gets the auth URL, navigates the browser to it. Google's redirect comes back to the callback endpoint which redirects to `/app/connections?connected=<email>`.
- Per-row "Revoke" button posts `DELETE /gmail/accounts/{id}` with a confirmation.
- Status badge per row: green for `active`, gray for `disconnected`, red for `revoked`.
- Empty-state message guides to the customer setup steps; links out to the scoping doc text.

**Routing** in `App.tsx` or wherever routes are declared: add `/app/connections` → `<Connections />`.

**Nav**: top-level link in the side menu. Visible to all roles (every user manages their own Gmail accounts).

**Verification:** with no accounts connected, page shows the empty state. Clicking "Connect" opens Google OAuth. Coming back lists the new account. Revoke removes it.

---

### B1.8 — Type 1 form: gmail account picker

**Code edit** at `frontend/src/components/WorkflowConfigForm.tsx` (typeId === 1 branch):

- Add a new `service` select at the top: `apple_mail` (default) | `gmail`.
- When `service === "apple_mail"`: existing apple-mail account dropdown shows.
- When `service === "gmail"`: replace the apple-mail dropdown with a fetch-driven dropdown populated from `GET /gmail/accounts` (filtering to `status === 'active'`). Stores `account_id` as int (NOT `account` as string).
- If the user has no active Gmail accounts and selects gmail: show a hint "No Gmail accounts connected yet — visit Connections to add one."

**Verification:** create a new type 1 workflow, switch service to gmail, see Gmail account dropdown populated. Save. The stored config has `service: "gmail"` and `account_id: <int>`. Backend run logs match.

---

### B1.9 — Type 1 default_config + config_schema update

**Alembic data migration**: update `workflow_types.default_config` and `workflow_types.config_schema` for type_id=1 to include the new `service` field. Done as a small migration so it's reproducible across deployments.

This is split from B1.6 because the config_schema metadata drives the schema-driven form display (for any future caller), and is naturally a data-only migration.

**Verification:** `SELECT default_config, config_schema FROM workflow_types WHERE type_id=1;` shows the `service` field present.

---

### B1.10 — Docs + BACKLOG

- `docs/BACKLOG.md`: mark B1 shipped under a new "Track B" section. Note that B2 (send/draft) is the next dependency.
- `CLAUDE.md`: add Gmail to the Services list in the Architecture section.
- Add a customer-facing setup guide stub at `docs/setup_guide_gmail_workspace.md` based on the scoping doc's customer setup checklist; Harry will polish it as he walks through it himself.

---

## Risks and mitigations

**OAuth redirect URI mismatch.** Google rejects callbacks if the redirect URI doesn't match exactly what was registered. Mitigation: document the exact URL format expected (`http://localhost:8000/api/v1/gmail/oauth/callback` for dev). Mismatch produces a clear error to the user, not a silent failure.

**Encryption key loss.** If `TOKEN_ENCRYPTION_KEY` is regenerated, all stored tokens become un-decryptable. Mitigation: the secrets helper raises a clear "key change detected" error on decrypt failure. Recovery is to revoke all gmail_accounts and reconnect — the customer setup doc warns about this.

**Refresh-token revocation surprise.** Google can revoke a refresh token (user clicks "remove access" in their Google account settings; org admin disables the connected app). Mitigation: `gmail_client` catches the refresh failure, marks the account `disconnected`, surfaces in the UI. User reconnects.

**Test users limit.** The scoping doc covers this — Workspace internal apps don't hit the 100-test-user cap. Harry's setup is internal-mode for his Workspace org.

**Concurrent OAuth flows.** Two browser windows starting OAuth at the same time both produce valid state JWTs. Both will succeed but the second UPSERT replaces the first. Acceptable behavior.

**B1 + F5 interaction.** Once B1 lands, gmail-flavored type 1 runs go through the same `_run_workflow_background` and inherit the F5 lock. No special handling needed.

**Pre-existing axios advisory.** Still in `dependencies`. F2 surfaced it; not addressed in B1. Worth a separate small phase.

---

## Critical files for implementation

- `backend/services/secrets.py` (new)
- `backend/db/models.py` (add 2 classes)
- `backend/db/schemas.py` (add GmailAccountRead)
- `backend/alembic/versions/` (2 new migration files: gmail tables, type 1 config_schema update)
- `backend/api/gmail_oauth.py` (new)
- `backend/api/__init__.py` (router wire-up)
- `backend/services/gmail_client.py` (new)
- `backend/services/workflows/email_monitor.py` (gmail branch)
- `backend/config.py` (env var declarations)
- `backend/requirements.txt` (cryptography pin, google-auth-oauthlib, google-api-python-client)
- `frontend/src/pages/Connections.tsx` (new)
- `frontend/src/components/WorkflowConfigForm.tsx` (type 1 branch update)
- `frontend/src/App.tsx` and the side menu (new route + nav link)
- `docs/BACKLOG.md` (mark shipped)
- `docs/setup_guide_gmail_workspace.md` (new stub)

---

## End-to-end verification

Once Harry's GCP setup is done and env vars are set:

1. Visit `/app/connections`, click "Connect a Gmail account."
2. Google OAuth flow runs; consent screen shows the readonly scope.
3. Redirect back lands on Connections with the new account listed as `active`.
4. Create a type 1 workflow with `service: gmail`, pick the connected account, run it.
5. Confirm the run completes and produces a categorized inbox digest as Excel artifact.
6. Open `gmail_token_usage` table; see rows for the OAuth connect, the list_messages calls during the run, and any auto-refreshes.
7. Click Revoke on the account. Confirm the row's `status` flips to `revoked` and that re-using a stored access token directly against Gmail returns 401.
8. Reconnect the same email; new tokens are stored and the workflow runs again.

## What gets verified BEFORE harry-side GCP setup

Everything except the OAuth round-trip:
- Migration applies cleanly (B1.2).
- Models and schemas import clean (B1.3).
- Encryption helper unit-tests pass (B1.1).
- `/oauth/start` returns 503 with helpful detail when env vars unset (B1.4).
- Connections page loads and shows empty state (B1.7).
- Type 1 form's gmail branch renders with empty dropdown when no accounts exist (B1.8).
- The default_config / config_schema migration runs (B1.9).
