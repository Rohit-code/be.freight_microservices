"""Service to interact with authentication service"""
import httpx
from typing import Dict, Any, Optional
from ..core.config import settings
import logging

logger = logging.getLogger(__name__)


async def verify_token_and_get_user(token: str) -> Optional[Dict[str, Any]]:
    """Verify JWT token with auth service and get user info"""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{settings.AUTH_SERVICE_URL}/api/auth/me",
                headers={"Authorization": f"Bearer {token}"},
                timeout=10.0
            )
            
            if response.status_code == 200:
                return response.json()
            else:
                logger.warning(f"Token verification failed: {response.status_code}")
                return None
    except Exception as e:
        logger.error(f"Error verifying token: {str(e)}")
        return None


async def get_user_id_from_token(token: str) -> Optional[int]:
    """Get user ID from JWT token"""
    auth_data = await verify_token_and_get_user(token)
    if auth_data and auth_data.get('user'):
        return int(auth_data['user']['id'])
    return None
