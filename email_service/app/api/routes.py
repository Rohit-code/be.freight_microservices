from fastapi import APIRouter, HTTPException, Header, Query, Request
from typing import Optional, List, Dict, Any
from fastapi import Query
import httpx
from ..services.email_service import (
    store_email,
    get_new_emails,
    get_user_emails,
    get_user_drafts,
    mark_email_as_read,
    mark_email_as_processed,
    search_emails_semantic,
)
from ..services.email_service import EMAILS_COLLECTION, _metadata_to_email
from ..services.email_monitor_service import (
    fetch_and_store_emails,
)
from ..models import Email, EmailCreate
from ..core.config import settings
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/email", tags=["email"])

"""
IMPORTANT: User-Level Email Privacy (Different from Rate Sheets)

Email Model:
- Emails are USER-SPECIFIC and PRIVATE to each individual user
- Unlike rate sheets (which are organization-wide), emails are NOT shared within organizations
- Each user can ONLY see and manage their own emails
- When an email is received, it's associated with the specific user who received it
- Users within the same organization CANNOT see each other's emails

This ensures complete privacy between users, even within the same organization.
"""


async def get_user_from_token(token: str) -> Dict[str, Any]:
    """Get user data from auth service"""
    import httpx
    try:
        async with httpx.AsyncClient() as client:
            auth_response = await client.get(
                f"{settings.AUTH_SERVICE_URL}/api/auth/me",
                headers={"Authorization": f"Bearer {token}"},
                timeout=30.0  # Increased timeout for auth service calls
            )
            
            if auth_response.status_code != 200:
                raise HTTPException(
                    status_code=401,
                    detail="Invalid authentication token",
                )
            
            return auth_response.json()
    except (httpx.TimeoutException, httpx.ReadTimeout, httpx.ConnectTimeout) as e:
        logger.error(f"Timeout getting user from token - auth service unavailable: {type(e).__name__}")
        raise HTTPException(
            status_code=503,
            detail="Authentication service unavailable: Request timeout"
        )
    except httpx.RequestError as e:
        logger.error(f"Error connecting to auth service: {e}")
        raise HTTPException(
            status_code=503,
            detail=f"Authentication service unavailable: {str(e)}"
        )
    except Exception as e:
        logger.error(f"Unexpected error getting user from token: {e}", exc_info=True)
        raise HTTPException(
            status_code=503,
            detail=f"Authentication service error: {str(e)}"
        )


@router.post("/store")
async def store_email_endpoint(request: Request):
    """
    Store an email in vector DB and automatically draft a response
    
    Body can include:
    - organization_id: Optional, if provided will auto-draft response
    - auto_draft: Optional, defaults to True if organization_id is provided
    """
    logger.info("=" * 80)
    logger.info("📥 EMAIL STORE ENDPOINT CALLED")
    
    try:
        body_data = await request.json()
        logger.info(f"Request body keys: {list(body_data.keys())}")
        logger.info(f"user_id: {body_data.get('user_id')}")
        logger.info(f"gmail_message_id: {body_data.get('gmail_message_id')}")
        logger.info(f"subject: {body_data.get('subject', 'No Subject')}")
        logger.info(f"organization_id: {body_data.get('organization_id')}")
        logger.info(f"auto_draft: {body_data.get('auto_draft', True)}")
        
        # Validate required fields
        if not body_data.get('user_id') or not body_data.get('gmail_message_id'):
            logger.error("❌ Missing required fields: user_id or gmail_message_id")
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
        
        # Get organization_id and auto_draft flag
        organization_id = body_data.get('organization_id')
        auto_draft = body_data.get('auto_draft', True)  # Default to True if org_id provided
        
        # Store email with auto-draft enabled
        logger.info(f"📦 Calling store_email (org_id: {organization_id}, auto_draft: {auto_draft})")
        email = await store_email(email_data, organization_id=organization_id, auto_draft=auto_draft)
        
        if not email:
            logger.error("❌ store_email returned None")
            raise HTTPException(
                status_code=500,
                detail="Failed to store email in vector DB",
            )
        
        logger.info(f"✅ Email stored successfully: {email.id}")
        
        response_data = {
            "id": email.id,
            "gmail_message_id": email.gmail_message_id,
            "message": "Email stored successfully in vector DB"
        }
        
        # Include drafted response if available
        if email.drafted_response:
            logger.info("✅ Drafted response included in email")
            response_data["drafted_response"] = email.drafted_response
            response_data["has_draft"] = True
        else:
            logger.info("ℹ️  No drafted response (may be skipped if org_id missing)")
        
        logger.info("=" * 80)
        return response_data
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error storing email: {e}", exc_info=True)
        logger.info("=" * 80)
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
    organization_id: Optional[int] = Query(None),
    include_drafts: bool = Query(default=False),
):
    """
    List all emails for the current user
    If include_drafts=True, automatically drafts responses for pending emails
    """
    if not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=403,
            detail="Authorization header missing or invalid",
        )
    
    token = authorization.replace("Bearer ", "")
    
    try:
        auth_data = await get_user_from_token(token)
        user_id = int(auth_data['user']['id'])
        org_id = organization_id or auth_data['user'].get('organization_id')
        
        try:
            emails = await get_user_emails(user_id, limit=limit)
        except Exception as e:
            logger.error(f"Error getting user emails for user {user_id}: {e}", exc_info=True)
            raise HTTPException(
                status_code=500,
                detail="Failed to retrieve emails"
            )
        
        # Build email list with optional drafted responses
        email_list = []
        for email in emails:
            email_data = {
                "id": email.id,
                "gmail_message_id": email.gmail_message_id,
                "subject": email.subject,
                "from_email": email.from_email,
                "to_email": email.to_email,
                "snippet": email.snippet,
                "body_plain": email.body_plain,
                "body_html": email.body_html,
                "date": email.date,
                "has_attachments": email.has_attachments,
                "attachment_count": email.attachment_count,
                "is_read": email.is_read,
                "is_processed": email.is_processed,
                "is_rate_sheet": email.is_rate_sheet,
            }
            
            # Check if email already has a drafted response (from auto-draft on storage)
            if email.drafted_response:
                email_data["drafted_response"] = email.drafted_response
                logger.debug(f"Email {email.id} already has auto-drafted response")
            
            # If include_drafts and email is pending and no draft exists, draft a response
            elif include_drafts and not email.is_processed and org_id:
                logger.info(f"Drafting response for email {email.id} (gmail_id: {email.gmail_message_id}), org_id: {org_id}, is_processed: {email.is_processed}")
                try:
                    import httpx
                    # Use email content as query to draft response
                    email_query = email.body_plain or email.snippet or email.subject or ""
                    logger.info(f"Email query extracted: {email_query[:200]}... (length: {len(email_query)})")
                    
                    if email_query:
                        draft_url = f"{settings.RATE_SHEET_SERVICE_URL}/api/rate-sheets/draft-email-response?organization_id={org_id}"
                        logger.info(f"Calling draft endpoint: {draft_url}")
                        
                        async with httpx.AsyncClient(timeout=30.0) as client:
                            draft_response = await client.post(
                                draft_url,
                                json={
                                    "email_query": email_query,
                                    "original_email_subject": email.subject,
                                    "original_email_from": email.from_email,
                                    "limit": 5
                                },
                                headers={"Content-Type": "application/json"},
                                timeout=30.0
                            )
                            
                            logger.info(f"Draft response status: {draft_response.status_code} for email {email.id}")
                            
                            if draft_response.status_code == 200:
                                draft_data = draft_response.json()
                                email_data["drafted_response"] = draft_data
                                logger.info(f"Successfully drafted response for email {email.id}")
                            else:
                                error_text = draft_response.text[:500] if hasattr(draft_response, 'text') else "No error text"
                                logger.error(f"Draft endpoint returned {draft_response.status_code}: {error_text}")
                                email_data["draft_error"] = f"HTTP {draft_response.status_code}: {error_text}"
                    else:
                        logger.warning(f"No email query content found for email {email.id}")
                        email_data["draft_error"] = "No email content available for query"
                except Exception as e:
                    logger.error(f"Failed to draft response for email {email.id}: {e}", exc_info=True)
                    email_data["draft_error"] = str(e)
            elif include_drafts:
                # Log why draft was skipped
                if email.is_processed:
                    logger.debug(f"Skipping draft for email {email.id} - already processed")
                elif not org_id:
                    logger.warning(f"Skipping draft for email {email.id} - no organization_id (org_id: {org_id})")
            
            email_list.append(email_data)
        
        return {
            "emails": email_list,
            "total": len(email_list)
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to list emails: {str(e)}",
        )


@router.get("/drafts")
async def list_drafts_endpoint(
    authorization: str = Header(default=""),
    page: int = Query(default=1, ge=1, description="Page number (1-indexed)"),
    page_size: int = Query(default=10, ge=1, le=100, description="Number of drafts per page")
):
    """
    List all drafted email responses for the current user with pagination.
    
    IMPORTANT: User-Level Privacy
    - Returns ONLY drafts for the authenticated user (user-specific)
    - Users can ONLY see their own drafts
    - Drafts are filtered by user_id from the auth token
    
    Returns emails that have auto-drafted responses, including:
    - Email details (subject, from, to, body, etc.)
    - Drafted response (subject, body, confidence scores)
    - Rate sheets used for drafting
    
    Pagination: 10 drafts per page by default
    """
    if not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=403,
            detail="Authorization header missing or invalid",
        )
    
    token = authorization.replace("Bearer ", "")
    
    try:
        auth_data = await get_user_from_token(token)
        user_id = int(auth_data['user']['id'])
        
        logger.info(f"📋 Listing drafts for user {user_id} (page: {page}, page_size: {page_size})")
        
        # Calculate offset
        offset = (page - 1) * page_size
        
        # Get drafts with pagination (user-specific filtering)
        drafts, total_count = await get_user_drafts(user_id, limit=page_size, offset=offset)
        
        logger.info(f"✅ Returning {len(drafts)} drafts for user {user_id} (total: {total_count})")
        
        # Build response with all draft data
        drafts_list = []
        for email in drafts:
            draft_data = {
                # Email information
                "email": {
                    "id": email.id,
                    "gmail_message_id": email.gmail_message_id,
                    "gmail_thread_id": email.gmail_thread_id,
                    "subject": email.subject,
                    "from_email": email.from_email,
                    "to_email": email.to_email,
                    "cc_email": email.cc_email,
                    "bcc_email": email.bcc_email,
                    "snippet": email.snippet,
                    "body_plain": email.body_plain,
                    "body_html": email.body_html,
                    "date": email.date,
                    "has_attachments": email.has_attachments,
                    "attachment_count": email.attachment_count,
                    "is_read": email.is_read,
                    "is_processed": email.is_processed,
                    "is_rate_sheet": email.is_rate_sheet,
                    "created_at": email.created_at,
                    "updated_at": email.updated_at,
                },
                # Drafted response (complete data)
                "draft": email.drafted_response if email.drafted_response else None,
            }
            drafts_list.append(draft_data)
        
        # Calculate pagination info
        total_pages = (total_count + page_size - 1) // page_size if total_count > 0 else 0
        
        return {
            "drafts": drafts_list,
            "pagination": {
                "page": page,
                "page_size": page_size,
                "total_count": total_count,
                "total_pages": total_pages,
                "has_next": page < total_pages,
                "has_previous": page > 1
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to list drafts: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to list drafts: {str(e)}",
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
    """
    Mark an email as read
    
    IMPORTANT: Emails are user-private. Users can only mark their own emails as read.
    """
    if not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=403,
            detail="Authorization header missing or invalid",
        )
    
    try:
        token = authorization.replace("Bearer ", "")
        auth_data = await get_user_from_token(token)
        user_id = int(auth_data['user']['id'])
        
        # Verify user ownership before marking as read
        success = await mark_email_as_read(email_id, user_id=user_id)
        if success:
            return {"message": "Email marked as read", "email_id": email_id}
        else:
            raise HTTPException(
                status_code=404,
                detail="Email not found or you don't have permission to access it",
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
    """
    Mark an email as processed
    
    IMPORTANT: Emails are user-private. Users can only mark their own emails as processed.
    """
    if not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=403,
            detail="Authorization header missing or invalid",
        )
    
    try:
        token = authorization.replace("Bearer ", "")
        auth_data = await get_user_from_token(token)
        user_id = int(auth_data['user']['id'])
        
        # Verify user ownership before marking as processed
        success = await mark_email_as_processed(email_id, user_id=user_id)
        if success:
            return {"message": "Email marked as processed", "email_id": email_id}
        else:
            raise HTTPException(
                status_code=404,
                detail="Email not found or you don't have permission to access it",
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


async def verify_admin_access(token: str) -> bool:
    """Verify if user has admin access"""
    import httpx
    try:
        async with httpx.AsyncClient() as client:
            auth_response = await client.get(
                f"{settings.AUTH_SERVICE_URL}/api/auth/admin",
                headers={"Authorization": f"Bearer {token}"},
                timeout=10.0
            )
            return auth_response.status_code == 200
    except Exception as e:
        logger.error(f"Error verifying admin access: {str(e)}")
        return False


@router.get("/admin/all")
async def admin_list_all_emails(
    authorization: str = Header(default=""),
    limit: int = Query(default=1000, ge=1, le=10000),
    offset: int = Query(default=0, ge=0),
):
    """
    Admin endpoint: List ALL emails across ALL users (admin only)
    
    IMPORTANT: This endpoint bypasses user-level privacy for admin access.
    Only users with is_staff=True or is_superuser=True can access this.
    """
    if not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=403,
            detail="Authorization header missing or invalid",
        )
    
    token = authorization.replace("Bearer ", "")
    
    # Verify admin access
    if not await verify_admin_access(token):
        raise HTTPException(
            status_code=403,
            detail="Admin access required. Only staff or superuser accounts can access this endpoint."
        )
    
    try:
        # Get all emails from vector DB (no user_id filter)
        async with httpx.AsyncClient() as client:
            # Use a generic query to get all emails
            response = await client.post(
                f"{settings.VECTOR_DB_SERVICE_URL}/api/vector/collections/{EMAILS_COLLECTION}/query",
                json={
                    "query_texts": ["email"],
                    "n_results": limit + offset  # Get enough to paginate
                },
                timeout=60.0
            )
            
            if response.status_code != 200:
                raise HTTPException(
                    status_code=500,
                    detail="Failed to query vector DB"
                )
            
            data = response.json()
            results = data.get("results", {})
            ids = results.get("ids", [[]])[0]
            metadatas = results.get("metadatas", [[]])[0]
            documents = results.get("documents", [[]])[0]
            
            # Convert to Email objects
            all_emails = []
            for i, meta in enumerate(metadatas):
                email = _metadata_to_email(
                    ids[i],
                    meta,
                    documents[i] if documents else ""
                )
                all_emails.append(email)
            
            # Sort by date (newest first)
            all_emails.sort(key=lambda x: x.date or "", reverse=True)
            
            # Apply pagination
            paginated_emails = all_emails[offset:offset + limit]
            
            # Build response
            email_list = []
            for email in paginated_emails:
                email_data = {
                    "id": email.id,
                    "user_id": email.user_id,
                    "gmail_message_id": email.gmail_message_id,
                    "subject": email.subject,
                    "from_email": email.from_email,
                    "to_email": email.to_email,
                    "snippet": email.snippet,
                    "body_plain": email.body_plain[:500] if email.body_plain else None,  # Truncate for list view
                    "body_html": email.body_html[:500] if email.body_html else None,  # Truncate for list view
                    "date": email.date,
                    "has_attachments": email.has_attachments,
                    "attachment_count": email.attachment_count,
                    "is_read": email.is_read,
                    "is_processed": email.is_processed,
                    "is_rate_sheet": email.is_rate_sheet,
                    "created_at": email.created_at,
                    "drafted_response": email.drafted_response,
                }
                email_list.append(email_data)
            
            return {
                "emails": email_list,
                "total": len(all_emails),
                "limit": limit,
                "offset": offset,
                "returned": len(email_list)
            }
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to list all emails (admin): {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to list all emails: {str(e)}",
        )


@router.get("/admin/stats")
async def admin_email_stats(
    authorization: str = Header(default="")
):
    """
    Admin endpoint: Get email statistics across all users (admin only)
    """
    if not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=403,
            detail="Authorization header missing or invalid",
        )
    
    token = authorization.replace("Bearer ", "")
    
    # Verify admin access
    if not await verify_admin_access(token):
        raise HTTPException(
            status_code=403,
            detail="Admin access required. Only staff or superuser accounts can access this endpoint."
        )
    
    try:
        # Get collection info to get total count
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{settings.VECTOR_DB_SERVICE_URL}/api/vector/collections/{EMAILS_COLLECTION}",
                timeout=10.0
            )
            
            total_emails = 0
            if response.status_code == 200:
                collection_info = response.json()
                total_emails = collection_info.get("count", 0)
            
            # Get sample of emails to calculate stats
            sample_response = await client.post(
                f"{settings.VECTOR_DB_SERVICE_URL}/api/vector/collections/{EMAILS_COLLECTION}/query",
                json={
                    "query_texts": ["email"],
                    "n_results": min(1000, total_emails)  # Sample up to 1000
                },
                timeout=30.0
            )
            
            unread_count = 0
            processed_count = 0
            with_drafts_count = 0
            rate_sheet_count = 0
            unique_users = set()
            
            if sample_response.status_code == 200:
                sample_data = sample_response.json()
                results = sample_data.get("results", {})
                metadatas = results.get("metadatas", [[]])[0]
                
                for meta in metadatas:
                    if not meta.get("is_read", False):
                        unread_count += 1
                    if meta.get("is_processed", False):
                        processed_count += 1
                    if meta.get("drafted_response"):
                        with_drafts_count += 1
                    if meta.get("is_rate_sheet", False):
                        rate_sheet_count += 1
                    user_id = meta.get("user_id")
                    if user_id:
                        unique_users.add(str(user_id))
            
            # Extrapolate stats if we sampled
            if total_emails > 1000:
                sample_size = len(metadatas) if sample_response.status_code == 200 else 0
                if sample_size > 0:
                    ratio = total_emails / sample_size
                    unread_count = int(unread_count * ratio)
                    processed_count = int(processed_count * ratio)
                    with_drafts_count = int(with_drafts_count * ratio)
                    rate_sheet_count = int(rate_sheet_count * ratio)
            
            return {
                "total_emails": total_emails,
                "unread_emails": unread_count,
                "processed_emails": processed_count,
                "emails_with_drafts": with_drafts_count,
                "rate_sheet_emails": rate_sheet_count,
                "unique_users": len(unique_users),
                "read_emails": total_emails - unread_count if total_emails > 0 else 0
            }
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get email stats (admin): {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get email stats: {str(e)}",
        )
