from fastapi import APIRouter, HTTPException, Header, Query, Request
from typing import Optional, List, Dict, Any
from ..services.email_service import (
    store_email,
    get_new_emails,
    get_user_emails,
    mark_email_as_read,
    mark_email_as_processed,
    search_emails_semantic,
)
from ..services.email_monitor_service import (
    fetch_and_store_emails,
)
from ..models import Email, EmailCreate
from ..core.config import settings
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/email", tags=["email"])


async def get_user_from_token(token: str) -> Dict[str, Any]:
    """Get user data from auth service"""
    import httpx
    async with httpx.AsyncClient() as client:
        auth_response = await client.get(
            f"{settings.AUTH_SERVICE_URL}/api/auth/me",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10.0
        )
        
        if auth_response.status_code != 200:
            raise HTTPException(
                status_code=401,
                detail="Invalid authentication token",
            )
        
        return auth_response.json()


@router.post("/store")
async def store_email_endpoint(request: Request):
    """Store an email in vector DB"""
    try:
        body_data = await request.json()
        
        # Validate required fields
        if not body_data.get('user_id') or not body_data.get('gmail_message_id'):
            raise HTTPException(
                status_code=400,
                detail="Missing required fields: user_id, gmail_message_id",
            )
        
        email_data = EmailCreate(
            user_id=body_data['user_id'],
            gmail_message_id=body_data['gmail_message_id'],
            gmail_thread_id=body_data.get('gmail_thread_id'),
            subject=body_data.get('subject'),
            from_email=body_data.get('from_email') or body_data.get('from'),
            to_email=body_data.get('to_email') or body_data.get('to'),
            cc_email=body_data.get('cc_email') or body_data.get('cc'),
            bcc_email=body_data.get('bcc_email') or body_data.get('bcc'),
            snippet=body_data.get('snippet'),
            body_html=body_data.get('body_html'),
            body_plain=body_data.get('body_plain'),
            date=body_data.get('date'),
            has_attachments=body_data.get('has_attachments', False),
            attachment_count=body_data.get('attachment_count', 0),
            is_sent=body_data.get('is_sent', False),
        )
        
        email = await store_email(email_data)
        
        if not email:
            raise HTTPException(
                status_code=500,
                detail="Failed to store email in vector DB",
            )
        
        return {
            "id": email.id,
            "gmail_message_id": email.gmail_message_id,
            "message": "Email stored successfully in vector DB"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to store email: {str(e)}",
        )


@router.get("/new")
async def get_new_emails_endpoint(
    authorization: str = Header(default=""),
    limit: int = Query(default=50, ge=1, le=200),
):
    """Get new/unread emails for the current user"""
    if not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=403,
            detail="Authorization header missing or invalid",
        )
    
    token = authorization.replace("Bearer ", "")
    
    try:
        auth_data = await get_user_from_token(token)
        user_id = int(auth_data['user']['id'])
        
        emails = await get_new_emails(user_id, limit=limit)
        
        return {
            "emails": [
                {
                    "id": email.id,
                    "gmail_message_id": email.gmail_message_id,
                    "subject": email.subject,
                    "from": email.from_email,
                    "to": email.to_email,
                    "snippet": email.snippet,
                    "date": email.date,
                    "has_attachments": email.has_attachments,
                    "attachment_count": email.attachment_count,
                    "is_read": email.is_read,
                    "is_processed": email.is_processed,
                    "is_rate_sheet": email.is_rate_sheet,
                    "created_at": email.created_at,
                }
                for email in emails
            ],
            "total": len(emails)
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get emails: {str(e)}",
        )


@router.get("/list")
async def list_emails_endpoint(
    authorization: str = Header(default=""),
    limit: int = Query(default=100, ge=1, le=500),
):
    """List all emails for the current user"""
    if not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=403,
            detail="Authorization header missing or invalid",
        )
    
    token = authorization.replace("Bearer ", "")
    
    try:
        auth_data = await get_user_from_token(token)
        user_id = int(auth_data['user']['id'])
        
        emails = await get_user_emails(user_id, limit=limit)
        
        return {
            "emails": [
                {
                    "id": email.id,
                    "gmail_message_id": email.gmail_message_id,
                    "subject": email.subject,
                    "from": email.from_email,
                    "to": email.to_email,
                    "snippet": email.snippet,
                    "date": email.date,
                    "has_attachments": email.has_attachments,
                    "attachment_count": email.attachment_count,
                    "is_read": email.is_read,
                    "is_processed": email.is_processed,
                    "is_rate_sheet": email.is_rate_sheet,
                }
                for email in emails
            ],
            "total": len(emails)
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to list emails: {str(e)}",
        )


@router.post("/search")
async def search_emails_endpoint(
    request: Request,
    authorization: str = Header(default="")
):
    """Search emails using semantic search with BGE embeddings"""
    if not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=403,
            detail="Authorization header missing or invalid",
        )
    
    token = authorization.replace("Bearer ", "")
    
    try:
        body_data = await request.json()
        query = body_data.get('query', '')
        limit = body_data.get('limit', 10)
        
        if not query:
            raise HTTPException(
                status_code=400,
                detail="Missing required field: query",
            )
        
        auth_data = await get_user_from_token(token)
        user_id = int(auth_data['user']['id'])
        
        emails = await search_emails_semantic(user_id, query, limit=limit)
        
        return {
            "emails": [
                {
                    "id": email.id,
                    "gmail_message_id": email.gmail_message_id,
                    "subject": email.subject,
                    "from": email.from_email,
                    "snippet": email.snippet,
                    "date": email.date,
                }
                for email in emails
            ],
            "total": len(emails),
            "query": query
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to search emails: {str(e)}",
        )


@router.post("/{email_id}/read")
async def mark_email_read(
    email_id: str,
    authorization: str = Header(default="")
):
    """Mark an email as read"""
    if not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=403,
            detail="Authorization header missing or invalid",
        )
    
    try:
        success = await mark_email_as_read(email_id)
        if success:
            return {"message": "Email marked as read", "email_id": email_id}
        else:
            raise HTTPException(
                status_code=404,
                detail="Email not found or update failed",
            )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to mark email as read: {str(e)}",
        )


@router.post("/{email_id}/processed")
async def mark_email_processed(
    email_id: str,
    authorization: str = Header(default="")
):
    """Mark an email as processed"""
    if not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=403,
            detail="Authorization header missing or invalid",
        )
    
    try:
        success = await mark_email_as_processed(email_id)
        if success:
            return {"message": "Email marked as processed", "email_id": email_id}
        else:
            raise HTTPException(
                status_code=404,
                detail="Email not found or update failed",
            )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to mark email as processed: {str(e)}",
        )


@router.post("/fetch")
async def fetch_emails_endpoint(
    request: Request,
    authorization: str = Header(default="")
):
    """Manually fetch emails from Gmail and store them in vector DB"""
    if not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=403,
            detail="Authorization header missing or invalid",
        )
    
    token = authorization.replace("Bearer ", "")
    
    try:
        auth_data = await get_user_from_token(token)
        user_id = int(auth_data['user']['id'])
        
        # Check if Gmail is connected
        if not auth_data['user'].get('has_google_connected'):
            return {
                "message": "Gmail not connected",
                "user_id": user_id,
                "stored": 0
            }
        
        # Fetch and store emails
        result = await fetch_and_store_emails(user_id, token, max_results=50)
        
        logger.info(f"Manual email fetch for user {user_id}: fetched={result.get('fetched', 0)}, new={result.get('new', 0)}")
        
        return {
            "message": "Email fetch completed",
            "user_id": user_id,
            "fetched": result.get('fetched', 0),
            "new": result.get('new', 0),
            "existing": result.get('existing', 0),
            "note": "New emails are automatically captured via Gmail webhooks"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to fetch emails: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch emails: {str(e)}",
        )
