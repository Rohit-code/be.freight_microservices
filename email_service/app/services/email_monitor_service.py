"""
Email Monitor Service - Manual fetch functions only.
Automatic polling removed - using Gmail webhooks instead.
"""
import httpx
from typing import Dict, Any, List
from datetime import datetime
from ..models import EmailCreate
from ..services.email_service import store_email, get_email_by_gmail_id
from ..core.config import settings
import logging

logger = logging.getLogger(__name__)


async def get_gmail_connected_users() -> List[Dict[str, Any]]:
    """Get all users with Gmail connected from auth service"""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{settings.AUTH_SERVICE_URL}/api/auth/internal/gmail-users",
                timeout=30.0
            )
            
            if response.status_code == 200:
                data = response.json()
                return data.get('users', [])
            else:
                logger.error(f"Failed to get Gmail users: {response.status_code}")
                return []
                
    except Exception as e:
        logger.error(f"Error getting Gmail users: {e}")
        return []


async def fetch_gmail_for_user(user_id: int, max_results: int = 50) -> Dict[str, Any]:
    """Fetch Gmail messages for a user using internal API (refresh token based)"""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{settings.AUTH_SERVICE_URL}/api/auth/internal/gmail/{user_id}/list",
                params={"max_results": max_results},
                timeout=60.0
            )
            
            if response.status_code == 200:
                return response.json()
            else:
                logger.warning(f"Failed to fetch Gmail for user {user_id}: {response.status_code}")
                return {"messages": []}
                
    except Exception as e:
        logger.error(f"Error fetching Gmail for user {user_id}: {e}")
        return {"messages": []}


async def fetch_gmail_detail_for_user(user_id: int, message_id: str) -> Dict[str, Any]:
    """Get Gmail message detail using internal API"""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{settings.AUTH_SERVICE_URL}/api/auth/internal/gmail/{user_id}/detail/{message_id}",
                timeout=30.0
            )
            
            if response.status_code == 200:
                return response.json()
            else:
                return {}
                
    except Exception as e:
        logger.error(f"Error getting Gmail detail for message {message_id}: {e}")
        return {}


async def process_user_emails(user_id: int, max_results: int = 50) -> Dict[str, Any]:
    """Fetch and store emails for a single user"""
    try:
        # Fetch emails using internal API (uses refresh token)
        gmail_result = await fetch_gmail_for_user(user_id, max_results)
        messages = gmail_result.get('messages', [])
        
        if not messages:
            return {"user_id": user_id, "fetched": 0, "new": 0, "existing": 0}
        
        new_count = 0
        existing_count = 0
        
        for msg_data in messages:
            gmail_message_id = msg_data.get('id', '')
            
            if not gmail_message_id:
                continue
            
            # Check if email already exists
            existing_email = await get_email_by_gmail_id(user_id, gmail_message_id)
            
            if existing_email:
                existing_count += 1
                continue
            
            # Fetch full email details
            try:
                email_detail = await fetch_gmail_detail_for_user(user_id, gmail_message_id)
                
                body = ""
                body_html = None
                body_plain = None
                
                if email_detail:
                    body = email_detail.get('body', '')
                    body_html = body if '<' in body else None
                    body_plain = body if '<' not in body else None
                
                # Create email data
                email_data = EmailCreate(
                    user_id=user_id,
                    gmail_message_id=gmail_message_id,
                    gmail_thread_id=msg_data.get('threadId') or (email_detail.get('threadId') if email_detail else None),
                    subject=msg_data.get('subject') or (email_detail.get('subject') if email_detail else None),
                    from_email=msg_data.get('from') or (email_detail.get('from') if email_detail else None),
                    to_email=msg_data.get('to') or (email_detail.get('to') if email_detail else None),
                    cc_email=msg_data.get('cc') or (email_detail.get('cc') if email_detail else None),
                    bcc_email=msg_data.get('bcc') or (email_detail.get('bcc') if email_detail else None),
                    snippet=msg_data.get('snippet') or (email_detail.get('snippet') if email_detail else None),
                    body_html=body_html,
                    body_plain=body_plain,
                    date=msg_data.get('date') or (email_detail.get('date') if email_detail else None),
                    has_attachments=msg_data.get('hasAttachments', False) or (email_detail.get('attachmentCount', 0) > 0 if email_detail else False),
                    attachment_count=msg_data.get('attachmentCount', 0) or (email_detail.get('attachmentCount', 0) if email_detail else 0),
                    is_sent=email_detail.get('isSent', False) if email_detail else False,
                )
                
                # Store email in Vector DB
                result = await store_email(email_data)
                if result:
                    new_count += 1
                    
            except Exception as e:
                logger.error(f"Error processing email {gmail_message_id}: {e}")
                # Store basic info without full detail
                email_data = EmailCreate(
                    user_id=user_id,
                    gmail_message_id=gmail_message_id,
                    gmail_thread_id=msg_data.get('threadId'),
                    subject=msg_data.get('subject'),
                    from_email=msg_data.get('from'),
                    snippet=msg_data.get('snippet'),
                    date=msg_data.get('date'),
                    has_attachments=msg_data.get('hasAttachments', False),
                    attachment_count=msg_data.get('attachmentCount', 0),
                )
                result = await store_email(email_data)
                if result:
                    new_count += 1
        
        return {
            "user_id": user_id,
            "fetched": len(messages),
            "new": new_count,
            "existing": existing_count
        }
        
    except Exception as e:
        logger.error(f"Error processing emails for user {user_id}: {e}")
        return {"user_id": user_id, "fetched": 0, "new": 0, "existing": 0, "error": str(e)}


# Legacy function for backward compatibility
async def fetch_and_store_emails(user_id: int, token: str = None, max_results: int = 50) -> Dict[str, Any]:
    """
    Fetch and store emails for a user.
    Uses internal API (refresh token) - token parameter ignored.
    """
    return await process_user_emails(user_id, max_results)


# Stub functions for backward compatibility (no-op since we use webhooks now)
async def start_email_monitoring(user_id: int = None, token: str = None, interval_minutes: int = 5):
    """No-op: Email monitoring now uses Gmail webhooks instead of polling"""
    logger.info("Email monitoring uses Gmail webhooks - no polling needed")
    pass


async def stop_email_monitoring(user_id: int = None):
    """No-op: Email monitoring now uses Gmail webhooks instead of polling"""
    pass
