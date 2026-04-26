# Gmail Access & Security: Consumer vs. Workspace Accounts

**Date:** 2026-04-22
**Purpose:** Capture what's the same and what differs between free consumer Gmail (`@gmail.com`) and Google Workspace Gmail (`@customdomain`) when integrating them into the p51 platform via OAuth 2.0 + Gmail API.

---

## Same for both account types

- Same Gmail API, same endpoints, same scopes
- Same OAuth 2.0 flow (authorization code → refresh token)
- Same refresh-token behavior (long-lived, can be revoked)
- Same rate limits (per GCP project, shared pool)
- Platform code is identical for both

## Where they diverge

| Dimension | Consumer Gmail (@gmail.com) | Workspace Gmail (@customdomain) |
|---|---|---|
| **Who can grant consent** | The end user | The end user, unless their admin requires admin approval first |
| **Admin controls** | None | Admin can allowlist/blocklist apps, require review, or install domain-wide delegation so users don't consent individually |
| **"This app isn't verified" warning** | Shown until you complete Google's verification | Shown unless admin allowlists the app |
| **Testing limit (unverified)** | 100 total test users | Same limit but admin can bypass via allowlist |
| **Centralized revocation** | User-only | User OR admin |
| **Security policy enforcement** | User controls 2FA, session, etc. | Admin policies apply |

## The piece that will actually bite you: app verification

Gmail scopes are classified "restricted" under Google's policy — this includes `gmail.readonly`, `gmail.send`, `gmail.compose`, and `gmail.modify`. Any GCP project using those scopes for more than ~100 test users must go through Google's verification process:

- **Unverified app (default):** works in testing, but end users see "Google hasn't verified this app" and have to click "Advanced → Go to app (unsafe)" to proceed. Workspace admins can allowlist you past that; consumer users cannot.
- **Verified app:** submit to Google, they review scope justifications, and for restricted scopes you typically need a **CASA Tier 2 security assessment** (third-party security audit, costs in the low thousands, takes weeks). Once verified, no warning, unlimited users.

For a SOHO product where some customers are on free Gmail, this is a real piece of the roadmap — not a blocker for learning/testing, but a blocker for shipping publicly to consumer accounts. Workspace-only customers can be onboarded via admin allowlisting without the verification.

## Practical path for our current testing

- Create the GCP project, configure OAuth, test against your own Gmail accounts (consumer and Workspace) without verification — up to 100 test users you add to the OAuth consent screen
- The Squarespace form submissions going to `harry@cognosa.net` (Workspace) are fine to test against today
- When shipping to paying customers, budget for either:
  - (a) Workspace-only customer base + admin allowlisting, OR
  - (b) completing Google's CASA Tier 2 verification

## Security note worth calling out

When the platform stores refresh tokens for users, those tokens are the crown jewels — possession equals the ability to read and send as that user. Non-negotiables when we build this out:

- **Encryption at rest**: AES-GCM with a key stored separately from the DB (env var, or a secrets manager), rotated periodically
- **Scoped access**: only the running user's workflow can read their own tokens; no cross-user leakage even under a bug
- **Revocation hooks**: removing a connected account calls Google's revoke endpoint so the token is dead at the source, not just hidden in our DB
- **Audit log**: every use of a token (fetch message, send email, save draft) writes a row with workflow_id, run_id, timestamp, action

Budget for these when we implement; they're not afterthoughts.
