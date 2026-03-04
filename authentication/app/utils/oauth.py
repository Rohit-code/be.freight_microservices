"""Google OAuth utilities"""
from google_auth_oauthlib.flow import Flow
from google.oauth2 import id_token
from google.auth.transport import requests
from datetime import datetime, timedelta
from ..core.config import settings


def get_google_oauth_flow():
    """Create and return Google OAuth flow"""
    if not settings.google_client_id or not settings.google_client_secret:
        raise ValueError('Google Client ID or Secret not configured')
    
    scopes = [
        'openid',
        'https://www.googleapis.com/auth/userinfo.email',
        'https://www.googleapis.com/auth/userinfo.profile',
        'https://www.googleapis.com/auth/gmail.readonly',
        'https://www.googleapis.com/auth/gmail.send',
        'https://www.googleapis.com/auth/drive.readonly',
    ]
    
    redirect_uri = settings.effective_google_redirect_uri

    flow = Flow.from_client_config(
        {
            "web": {
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [redirect_uri],
            }
        },
        scopes=scopes,
        redirect_uri=redirect_uri
    )
    return flow


def exchange_code_for_token(code: str) -> dict:
    """Exchange OAuth authorization code for tokens"""
    try:
        # Create flow
        flow = get_google_oauth_flow()
        
        # Exchange code for token
        flow.fetch_token(code=code)
        
        # Get credentials
        credentials = flow.credentials
        id_token_jwt = credentials.id_token
        
        # Verify ID token
        idinfo = id_token.verify_oauth2_token(
            id_token_jwt,
            requests.Request(),
            settings.google_client_id
        )
        
        # Verify issuer
        if idinfo['iss'] not in ['accounts.google.com', 'https://accounts.google.com']:
            raise ValueError('Wrong issuer.')
        
        # Extract access token, refresh token, and expiry
        access_token = credentials.token
        refresh_token = credentials.refresh_token
        expiry = credentials.expiry
        
        return {
            'email': idinfo['email'],
            'name': idinfo.get('name', ''),
            'picture': idinfo.get('picture', ''),
            'google_id': idinfo['sub'],
            'access_token': access_token,
            'refresh_token': refresh_token,
            'token_expiry': expiry,
        }
    except Exception as e:
        raise ValueError(f'Failed to exchange code for token: {str(e)}')
