"""Gmail integration service - fetches emails from auth service's Gmail API"""
import httpx
from typing import Dict, Any, List
from ..core.config import settings
import logging

logger = logging.getLogger(__name__)


async def fetch_emails_from_auth_service(user_id: int, token: str, max_results: int = 50) -> Dict[str, Any]:
    """Fetch emails from Gmail via auth service"""
    try:
        async with httpx.AsyncClient() as client:
            # Call auth service's Gmail list endpoint
            response = await client.get(
                f"{settings.AUTH_SERVICE_URL}/api/auth/gmail/list",
                headers={"Authorization": f"Bearer {token}"},
                params={"max_results": max_results},
                timeout=30.0
            )
            
            if response.status_code != 200:
                logger.error(f"Failed to fetch emails from auth service: {response.status_code}")
                return {"messages": [], "total": 0}
            
            return response.json()
            
    except Exception as e:
        logger.error(f"Error fetching emails from auth service: {str(e)}")
        return {"messages": [], "total": 0}


async def get_email_detail_from_auth_service(message_id: str, token: str) -> Dict[str, Any]:
    """Get email detail from Gmail via auth service"""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{settings.AUTH_SERVICE_URL}/api/auth/gmail/detail",
                headers={"Authorization": f"Bearer {token}"},
                params={"message_id": message_id},
                timeout=30.0
            )
            
            if response.status_code != 200:
                logger.error(f"Failed to get email detail: {response.status_code}")
                return {}
            
            return response.json()
            
    except Exception as e:
        logger.error(f"Error getting email detail: {str(e)}")
        return {}
