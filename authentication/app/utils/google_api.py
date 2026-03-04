"""Google API service utilities"""
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request as GoogleRequest
from google.auth.exceptions import RefreshError
from googleapiclient.discovery import build
from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from ..models import User
from ..core.database import AsyncSessionLocal
from ..core.config import settings


async def get_user_from_token(token: str) -> User:
    """Get user from JWT token"""
    from .jwt import verify_jwt_token
    import logging
    
    logger = logging.getLogger(__name__)
    try:
        payload = verify_jwt_token(token)
    except ValueError as e:
        logger.warning("JWT decode failed in get_user_from_token: %s (token_len=%s)", str(e), len(token))
        raise
    user_id = payload.get('user_id')
    
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(User).where(User.id == user_id)
        )
        user = result.scalar_one_or_none()
        if not user:
            raise ValueError('User not found')
        return user


async def refresh_user_google_token(user: User) -> Credentials:
    """Refresh a user's Google OAuth access token"""
    if not user.google_refresh_token:
        raise ValueError('User does not have a refresh token')
    
    credentials = Credentials(
        token=None,
        refresh_token=user.google_refresh_token,
        token_uri='https://oauth2.googleapis.com/token',
        client_id=settings.google_client_id,
        client_secret=settings.google_client_secret,
    )
    
    try:
        import asyncio
        request_obj = GoogleRequest()
        # Refresh token in a thread to avoid blocking the event loop
        await asyncio.to_thread(credentials.refresh, request_obj)
        
        # Update user with new token
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(User).where(User.id == user.id)
            )
            db_user = result.scalar_one()
            db_user.google_access_token = credentials.token
            if credentials.expiry:
                db_user.google_token_expiry = credentials.expiry
            await session.commit()
            await session.refresh(db_user)
            
            # Update the user object passed in
            user.google_access_token = db_user.google_access_token
            user.google_token_expiry = db_user.google_token_expiry
        
        return credentials
    except RefreshError as e:
        raise ValueError(f'Failed to refresh token: {str(e)}')


async def get_user_google_credentials(user: User) -> Credentials:
    """Get valid Google OAuth credentials for a user, refreshing if necessary"""
    if not user.google_access_token:
        raise ValueError('User does not have Google OAuth tokens')
    
    # Check if token is expired or will expire soon (within 5 minutes)
    if user.google_token_expiry:
        expiry_time = user.google_token_expiry
        if isinstance(expiry_time, str):
            expiry_time = datetime.fromisoformat(expiry_time.replace('Z', '+00:00'))
        if expiry_time <= datetime.now(expiry_time.tzinfo) + timedelta(minutes=5):
            await refresh_user_google_token(user)
    
    credentials = Credentials(
        token=user.google_access_token,
        refresh_token=user.google_refresh_token,
        token_uri='https://oauth2.googleapis.com/token',
        client_id=settings.google_client_id,
        client_secret=settings.google_client_secret,
    )
    
    return credentials


DEFAULT_GOOGLE_HTTP_TIMEOUT = 20


def _apply_service_timeout(service) -> None:
    """Apply request timeout to Google API client if supported."""
    try:
        if hasattr(service, "_http") and service._http:
            service._http.timeout = DEFAULT_GOOGLE_HTTP_TIMEOUT
    except Exception:
        # Best-effort; avoid breaking service creation
        pass


async def get_gmail_service(user: User):
    """Get Gmail API service for a user"""
    credentials = await get_user_google_credentials(user)
    service = build('gmail', 'v1', cache_discovery=False, credentials=credentials)
    _apply_service_timeout(service)
    return service


async def get_sheets_service(user: User):
    """Get Google Sheets API service for a user"""
    credentials = await get_user_google_credentials(user)
    service = build('sheets', 'v4', cache_discovery=False, credentials=credentials)
    _apply_service_timeout(service)
    return service


async def get_docs_service(user: User):
    """Get Google Docs API service for a user"""
    credentials = await get_user_google_credentials(user)
    service = build('docs', 'v1', cache_discovery=False, credentials=credentials)
    _apply_service_timeout(service)
    return service


async def get_drive_service(user: User):
    """Get Google Drive API service for a user"""
    credentials = await get_user_google_credentials(user)
    service = build('drive', 'v3', cache_discovery=False, credentials=credentials)
    _apply_service_timeout(service)
    return service
