"""Gmail OAuth flow + connected-account management (Track B Phase B1).

Endpoints (all under the API prefix):

    POST /gmail/oauth/start       → returns Google auth URL (state JWT)
    GET  /gmail/oauth/callback    → receives code, persists encrypted tokens
    GET  /gmail/accounts          → list current user's connected accounts
    DELETE /gmail/accounts/{id}   → revoke at Google + flip status to revoked

The flow:
1. User clicks "Connect a Gmail account" in the SPA.
2. SPA POSTs to /oauth/start; receives an auth URL with a signed state JWT.
3. SPA opens that URL in the browser; Google shows consent.
4. Google redirects to /oauth/callback?code=...&state=<jwt>.
5. The callback verifies the state JWT (matches the current user, not
   expired), exchanges code for tokens, encrypts and persists them, and
   redirects the SPA to /app/connections?connected=<email>.

Boots cleanly without GOOGLE_CLIENT_ID / _SECRET / _REDIRECT_URI set —
the OAuth-start endpoint returns 503 with a helpful message until they are.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import secrets as stdlib_secrets
from urllib.parse import urlencode

import jwt as pyjwt
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.auth.users import current_active_user
from backend.config import (
    GOOGLE_CLIENT_ID,
    GOOGLE_CLIENT_SECRET,
    GOOGLE_REDIRECT_URI,
    SECRET,
)
from backend.db.models import GmailAccounts, GmailTokenUsage, User
from backend.db.schemas import GmailAccountRead
from backend.db.session import async_get_session
from backend.services import secrets as crypto
from backend.services.logger_service import get_logger


log = get_logger("gmail_oauth")

router_gmail_oauth = APIRouter(prefix="/gmail")


# Read-only scope only for B1. B2 will add gmail.send + gmail.compose.
SCOPES = "https://www.googleapis.com/auth/gmail.readonly"

# State JWT lifetime: longer than a slow Google OAuth round-trip but short
# enough that a stale state token can't be replayed weeks later.
STATE_TTL_SECONDS = 600  # 10 minutes
STATE_AUDIENCE = "gmail-oauth-state"


def _config_ready() -> bool:
    """All three Google OAuth env vars must be set for the flow to work."""
    return bool(GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET and GOOGLE_REDIRECT_URI)


def _require_config() -> None:
    if not _config_ready():
        raise HTTPException(
            status_code=503,
            detail=(
                "Gmail integration is not configured on this server. "
                "An administrator must set GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, "
                "and GOOGLE_REDIRECT_URI per docs/track_b_gmail_workspace_scoping_260426.md."
            ),
        )


def _sign_state(user_id: int) -> str:
    payload = {
        "user_id": user_id,
        "nonce": stdlib_secrets.token_urlsafe(16),
        "exp": datetime.now(timezone.utc) + timedelta(seconds=STATE_TTL_SECONDS),
        "aud": STATE_AUDIENCE,
    }
    return pyjwt.encode(payload, SECRET, algorithm="HS256")


def _verify_state(token: str) -> int:
    try:
        payload = pyjwt.decode(
            token, SECRET, algorithms=["HS256"], audience=STATE_AUDIENCE
        )
    except pyjwt.ExpiredSignatureError:
        raise HTTPException(status_code=400, detail="OAuth state expired; restart the flow.")
    except pyjwt.InvalidTokenError as e:
        raise HTTPException(status_code=400, detail=f"Invalid OAuth state: {e}")
    user_id = payload.get("user_id")
    if not isinstance(user_id, int):
        raise HTTPException(status_code=400, detail="Malformed OAuth state.")
    return user_id


async def _log_event(
    session: AsyncSession,
    account_id: int,
    action: str,
    error_detail: str | None = None,
    workflow_id: int | None = None,
    run_id: int | None = None,
) -> None:
    session.add(
        GmailTokenUsage(
            account_id=account_id,
            workflow_id=workflow_id,
            run_id=run_id,
            action=action,
            error_detail=error_detail,
        )
    )
    await session.flush()


@router_gmail_oauth.post("/oauth/start")
async def oauth_start(
    user: User = Depends(current_active_user),
):
    """Return the Google auth URL the SPA should navigate to."""
    _require_config()
    state = _sign_state(user.user_id)
    params = {
        "response_type": "code",
        "client_id": GOOGLE_CLIENT_ID,
        "redirect_uri": GOOGLE_REDIRECT_URI,
        "scope": SCOPES,
        "access_type": "offline",        # request a refresh token
        "prompt": "consent",             # force consent so we always get refresh token
        "include_granted_scopes": "true",
        "state": state,
    }
    auth_url = f"https://accounts.google.com/o/oauth2/v2/auth?{urlencode(params)}"
    return {"auth_url": auth_url}


@router_gmail_oauth.get("/oauth/callback")
async def oauth_callback(
    code: str = Query(...),
    state: str = Query(...),
    session: AsyncSession = Depends(async_get_session),
):
    """Receive Google's redirect, exchange code for tokens, persist."""
    _require_config()
    user_id = _verify_state(state)

    # Lazy import: google_auth_oauthlib pulls in a chunk of dependencies we
    # don't want loaded for unrelated requests (memory + cold-start).
    from google_auth_oauthlib.flow import Flow

    flow = Flow.from_client_config(
        client_config={
            "web": {
                "client_id": GOOGLE_CLIENT_ID,
                "client_secret": GOOGLE_CLIENT_SECRET,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [GOOGLE_REDIRECT_URI],
            }
        },
        scopes=SCOPES.split(),
        redirect_uri=GOOGLE_REDIRECT_URI,
    )
    try:
        flow.fetch_token(code=code)
    except Exception as e:
        log.warning("oauth_callback_token_exchange_failed", error=str(e)[:200])
        raise HTTPException(status_code=400, detail=f"OAuth token exchange failed: {e}")

    creds = flow.credentials
    if not creds.refresh_token:
        # Google omits refresh_token if the user has previously consented and
        # we didn't pass prompt=consent. We do pass it — so this is a real
        # error if we hit it.
        raise HTTPException(
            status_code=400,
            detail="Google did not return a refresh token. Try disconnecting any prior consent at https://myaccount.google.com/permissions and retry.",
        )

    # Look up the connected email via the Gmail API itself. users.getProfile
    # returns emailAddress and is permitted by the gmail.readonly scope we
    # already requested — avoids needing to also ask for openid/email/profile
    # scopes (which the deprecated /oauth2/v2/userinfo endpoint requires).
    from googleapiclient.discovery import build
    try:
        service = build("gmail", "v1", credentials=creds, cache_discovery=False)
        profile = service.users().getProfile(userId="me").execute()
        email = profile.get("emailAddress")
    except Exception as e:
        log.warning("oauth_callback_userinfo_failed", error=str(e)[:200])
        raise HTTPException(status_code=502, detail=f"Failed to fetch userinfo from Google: {e}")
    if not email:
        raise HTTPException(status_code=502, detail="Gmail users.getProfile did not include an email.")

    # Resolve the user's group_id via the api_users row.
    user_row = await session.scalar(select(User).where(User.user_id == user_id))
    if not user_row:
        raise HTTPException(status_code=404, detail="User not found.")

    refresh_blob = crypto.encrypt(creds.refresh_token)
    access_blob = crypto.encrypt(creds.token) if creds.token else None
    expiry = creds.expiry
    if expiry and expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=timezone.utc)

    existing = await session.scalar(
        select(GmailAccounts).where(
            GmailAccounts.user_id == user_id,
            GmailAccounts.email == email,
        )
    )
    if existing:
        existing.refresh_token_encrypted = refresh_blob
        existing.access_token_encrypted = access_blob
        existing.access_token_expires_at = expiry
        existing.scopes = SCOPES
        existing.status = "active"
        existing.last_used_at = datetime.now(timezone.utc)
        account_id = existing.id
    else:
        new_acct = GmailAccounts(
            user_id=user_id,
            group_id=user_row.group_id,
            email=email,
            refresh_token_encrypted=refresh_blob,
            access_token_encrypted=access_blob,
            access_token_expires_at=expiry,
            scopes=SCOPES,
            status="active",
        )
        session.add(new_acct)
        await session.flush()
        account_id = new_acct.id

    await _log_event(session, account_id, "oauth_connect")
    await session.commit()

    return RedirectResponse(url=f"/app/connections?connected={email}", status_code=302)


@router_gmail_oauth.get("/accounts", response_model=list[GmailAccountRead])
async def list_accounts(
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(async_get_session),
):
    """Return the current user's connected Gmail accounts."""
    result = await session.execute(
        select(GmailAccounts)
        .where(GmailAccounts.user_id == user.user_id)
        .order_by(GmailAccounts.created_at.desc())
    )
    return result.scalars().all()


@router_gmail_oauth.delete("/accounts/{account_id}")
async def revoke_account(
    account_id: int,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(async_get_session),
):
    """Revoke at Google (best-effort) and flip the row's status to revoked.

    Soft-delete (status flip) preserves audit history. The unique
    constraint on (user_id, email) blocks reconnect-via-INSERT — the
    OAuth callback handles reconnect by UPSERTing the existing row.
    """
    acct = await session.get(GmailAccounts, account_id)
    if not acct or acct.user_id != user.user_id:
        raise HTTPException(status_code=404, detail="Account not found.")

    error_detail: str | None = None
    try:
        # Best-effort: hit Google's revoke endpoint with the refresh token.
        # If it fails, we still mark the row revoked locally — the user
        # can revoke at https://myaccount.google.com/permissions if needed.
        import httpx
        refresh_token = crypto.decrypt(acct.refresh_token_encrypted)
        async with httpx.AsyncClient(timeout=10.0) as http:
            resp = await http.post(
                "https://oauth2.googleapis.com/revoke",
                params={"token": refresh_token},
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            if resp.status_code != 200:
                error_detail = f"Google revoke returned {resp.status_code}: {resp.text[:200]}"
                log.warning("gmail_revoke_non200", account_id=account_id, status=resp.status_code)
    except Exception as e:
        error_detail = f"Local revoke call failed: {str(e)[:200]}"
        log.warning("gmail_revoke_failed", account_id=account_id, error=str(e)[:200])

    acct.status = "revoked"
    acct.access_token_encrypted = None
    acct.access_token_expires_at = None
    await _log_event(session, account_id, "oauth_revoke", error_detail=error_detail)
    await session.commit()

    return {"detail": f"Gmail account {acct.email} revoked.", "account_id": account_id}
