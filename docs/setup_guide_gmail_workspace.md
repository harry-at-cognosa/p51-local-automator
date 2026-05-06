# Gmail / Google Workspace setup guide

This is the one-time setup an instance administrator does to enable Gmail
integration on a deployed p51_local_automator. Each customer registers
their own GCP project — Cognosa does not operate a shared GCP project.

This is a draft. Harry will polish it on his first walk-through of his
own dev project. Track B scoping doc: `docs/track_b_gmail_workspace_scoping_260426.md`.

## Prerequisites

- Google Workspace organization (consumer @gmail.com is deferred — see
  Track B Phase B4).
- Workspace admin access to allowlist the application internally (so users
  skip the "unverified app" warning).
- Server admin access to the p51 deployment for env-var configuration.

## Step 1 — Create a GCP project

1. Visit `https://console.cloud.google.com`. Create a new project. Free tier
   is fine — no billing required for the API quotas this app uses.
2. Project name and project ID are not customer-visible; pick anything.

## Step 2 — Enable the Gmail API

1. APIs & Services → Library → search "Gmail API" → Enable.

## Step 3 — Configure the OAuth consent screen

1. APIs & Services → OAuth consent screen.
2. User type: **Internal** (Workspace-only) for B1. External is for
   consumer @gmail.com support which is deferred.
3. App name, support email, developer contact email — fill in.
4. Scopes — add:
   - `https://www.googleapis.com/auth/gmail.readonly` — required for B1.
   - When B2 ships you will add `gmail.send` and `gmail.compose` here too;
     users will be prompted to re-consent at that point.
5. Test users (External only): not applicable for Internal apps.
6. Save and continue.

## Step 4 — Create the OAuth client ID

1. APIs & Services → Credentials → Create Credentials → OAuth Client ID.
2. Application type: **Web application**.
3. Name: anything (e.g., "p51 local automator").
4. Authorized JavaScript origins: not required for this flow.
5. Authorized redirect URIs:
   - For local dev: `http://localhost:8000/api/v1/gmail/oauth/callback`
   - For production: `https://<your-host>/api/v1/gmail/oauth/callback`
   The exact path matters — Google rejects mismatches.
6. Create. Note the `Client ID` and `Client secret`.

## Step 5 — Allowlist the app in Workspace admin (Internal apps)

1. admin.google.com → Apps → Web and mobile apps.
2. Add custom OAuth app → use the Client ID from step 4.
3. Set access to allowed for the user OUs that will use p51.

## Step 6 — Configure the p51 server env vars

Add to `.env` (or your deployment's secret store):

```
GOOGLE_CLIENT_ID=<from step 4>
GOOGLE_CLIENT_SECRET=<from step 4>
GOOGLE_REDIRECT_URI=http://localhost:8000/api/v1/gmail/oauth/callback
TOKEN_ENCRYPTION_KEY=<see below>
```

Generate the encryption key once per deployment — never share across
deployments, never commit to git:

```
python -c 'import os, base64; print(base64.b64encode(os.urandom(32)).decode())'
```

Restart the backend after editing `.env`.

## Step 7 — Connect the first user

1. Log into the p51 web app as the user whose Gmail will be connected.
2. Side menu → Connections.
3. "Connect a Gmail account" → Google OAuth flow runs.
4. After consent, the user lands back at Connections with the new account
   showing status "active".

## Verifying

- Create a new Email Topic Monitor workflow. Pick "Gmail (Workspace)" as
  the service. Pick the connected account. Save.
- Click Run Now. Confirm the run completes and an Excel digest artifact
  appears.
- Check the `gmail_token_usage` table for an `oauth_connect` row plus
  the `list_messages` calls from the run.

## Revoking

- The user clicks Revoke on the Connections page. Behind the scenes, p51
  hits Google's revoke endpoint with the refresh token (best-effort) and
  flips the row's status to `revoked`. The row stays for audit history.
- The user can reconnect the same email; the OAuth callback UPSERTs the
  existing row and flips status back to `active`.

## Troubleshooting

**OAuth start returns 503 with "Gmail integration is not configured."**
The three env vars (`GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REDIRECT_URI`)
aren't all set. Double-check `.env` and that the backend was restarted after editing.

**Google rejects the callback with "redirect_uri_mismatch."**
The URL Google posts to must match exactly what's in step 4's "Authorized
redirect URIs." Trailing slashes, http-vs-https, and port numbers all matter.

**Refresh token revoked at Google side.**
The user clicked "remove access" in their Google account settings, or the
Workspace admin disabled the connected app. The next API call from p51
will fail; the account flips to status `disconnected`. The user reconnects
to fix it.

**TOKEN_ENCRYPTION_KEY changed.**
All previously stored Gmail tokens are now un-decryptable. There is no
recovery — every connected account must be revoked and re-connected.
The encryption helper raises a clear error on decrypt failure.
