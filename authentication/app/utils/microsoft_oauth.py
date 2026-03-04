"""Microsoft (Azure AD) OAuth utilities."""
import urllib.parse
from datetime import datetime, timezone, timedelta
from typing import Optional

from ..core.config import settings

# Scopes: openid profile email for login; User.Read for /me; Mail/Files for parity with Google
DEFAULT_SCOPES = "openid profile email User.Read Mail.Read Mail.Send Files.Read"


def get_microsoft_authorization_url(state: str) -> str:
    """Build Azure AD v2 authorization URL."""
    if not settings.microsoft_client_id or not settings.microsoft_tenant_id:
        raise ValueError("Microsoft Client ID or Tenant ID not configured")

    base = f"https://login.microsoftonline.com/{settings.microsoft_tenant_id}/oauth2/v2.0/authorize"
    params = {
        "client_id": settings.microsoft_client_id,
        "response_type": "code",
        "redirect_uri": settings.effective_microsoft_redirect_uri,
        "scope": DEFAULT_SCOPES,
        "response_mode": "query",
        "state": state,
    }
    return f"{base}?{urllib.parse.urlencode(params)}"


async def exchange_microsoft_code_for_token(code: str) -> dict:
    """
    Exchange authorization code for tokens and fetch user info from Microsoft Graph.
    Returns dict with: email, name, picture, microsoft_id, access_token, refresh_token, token_expiry.
    """
    import httpx

    if not settings.microsoft_client_id or not settings.microsoft_client_secret or not settings.microsoft_tenant_id:
        raise ValueError("Microsoft OAuth not configured")

    token_url = f"https://login.microsoftonline.com/{settings.microsoft_tenant_id}/oauth2/v2.0/token"
    redirect_uri = settings.effective_microsoft_redirect_uri

    async with httpx.AsyncClient() as client:
        # Token exchange
        token_resp = await client.post(
            token_url,
            data={
                "client_id": settings.microsoft_client_id,
                "client_secret": settings.microsoft_client_secret,
                "code": code,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=30.0,
        )
        token_resp.raise_for_status()
        token_data = token_resp.json()

    access_token = token_data.get("access_token")
    if not access_token:
        raise ValueError("No access_token in Microsoft token response")

    refresh_token = token_data.get("refresh_token")
    expires_in = token_data.get("expires_in", 3600)
    token_expiry = datetime.now(timezone.utc) + timedelta(seconds=expires_in)

    # User info from Microsoft Graph
    async with httpx.AsyncClient() as client:
        me_resp = await client.get(
            "https://graph.microsoft.com/v1.0/me",
            params={"$select": "id,displayName,mail,userPrincipalName"},
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=15.0,
        )
        me_resp.raise_for_status()
        me = me_resp.json()

    microsoft_id = me.get("id")
    if not microsoft_id:
        raise ValueError("No id in Microsoft Graph /me response")

    # Prefer mail over userPrincipalName for email
    email = (me.get("mail") or me.get("userPrincipalName") or "").strip()
    if not email:
        raise ValueError("No email (mail or userPrincipalName) in Microsoft Graph /me response")

    name = (me.get("displayName") or "").strip()

    # Optional: fetch profile photo (Graph returns 404 if no photo)
    picture: Optional[str] = None
    try:
        async with httpx.AsyncClient() as client:
            photo_resp = await client.get(
                "https://graph.microsoft.com/v1.0/me/photo/$value",
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=5.0,
            )
            if photo_resp.status_code == 200 and photo_resp.content:
                # Store as data URL or skip; backend often stores picture URL. Graph doesn't give a public URL easily.
                # We could skip picture or pass a placeholder; User model has picture as string (URL). Skip for now.
                picture = None
    except Exception:
        picture = None

    return {
        "email": email,
        "name": name,
        "picture": picture,
        "microsoft_id": microsoft_id,
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_expiry": token_expiry,
    }
