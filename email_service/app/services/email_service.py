"""Email service - stores all data in Vector DB with BGE embeddings"""
import httpx
import uuid
import asyncio
import json
from typing import List, Optional, Dict, Any
from datetime import datetime
from ..core.config import settings
from ..models import Email, EmailCreate, EmailUpdate
import logging

logger = logging.getLogger(__name__)

# Collection name for emails in vector DB
EMAILS_COLLECTION = "emails"

# Lock dictionary to prevent concurrent storage of the same email
# Key: email_id, Value: asyncio.Lock
# Note: Locks are cleaned up after use to prevent memory leaks
_email_storage_locks: Dict[str, asyncio.Lock] = {}
_locks_lock = asyncio.Lock()  # Lock to protect the locks dictionary
_MAX_LOCKS = 1000  # Maximum number of locks to keep in memory


async def ensure_collection_exists():
    """Ensure the emails collection exists in vector DB"""
    try:
        async with httpx.AsyncClient() as client:
            # Try to create collection (will return existing if already exists)
            response = await client.post(
                f"{settings.VECTOR_DB_SERVICE_URL}/api/vector/collections",
                json={"name": EMAILS_COLLECTION},
                timeout=30.0
            )
            return response.status_code in [200, 201]
    except Exception as e:
        logger.error(f"Error ensuring collection exists: {e}")
        return False


def _metadata_to_email(doc_id: str, metadata: Dict[str, Any], content: str = "") -> Email:
    """Convert vector DB metadata to Email model"""
    # Extract drafted_response from metadata if present
    drafted_response = None
    if metadata.get("drafted_response"):
        import json
        try:
            drafted_response = json.loads(metadata.get("drafted_response"))
        except (json.JSONDecodeError, TypeError, ValueError) as e:
            # Log but don't fail - invalid JSON in metadata is non-critical
            logger.debug(f"Could not parse drafted_response JSON for email {doc_id}: {e}")
            drafted_response = None
    
    email = Email(
        id=doc_id,
        user_id=int(metadata.get("user_id", 0)),
        gmail_message_id=metadata.get("gmail_message_id", ""),
        gmail_thread_id=metadata.get("gmail_thread_id"),
        subject=metadata.get("subject"),
        from_email=metadata.get("from_email"),
        to_email=metadata.get("to_email"),
        cc_email=metadata.get("cc_email"),
        bcc_email=metadata.get("bcc_email"),
        snippet=metadata.get("snippet"),
        body_html=metadata.get("body_html"),
        body_plain=metadata.get("body_plain") or content,
        date=metadata.get("date"),
        has_attachments=metadata.get("has_attachments", False),
        attachment_count=int(metadata.get("attachment_count", 0)),
        is_sent=metadata.get("is_sent", False),
        is_read=metadata.get("is_read", False),
        is_processed=metadata.get("is_processed", False),
        is_rate_sheet=metadata.get("is_rate_sheet", False),
        drafted_response=drafted_response,  # Include drafted_response in model
        created_at=metadata.get("created_at"),
        updated_at=metadata.get("updated_at"),
    )
    
    return email


def _email_to_metadata(
    email: EmailCreate, 
    email_id: str, 
    drafted_response: Optional[Dict[str, Any]] = None,
    ai_analysis: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Convert EmailCreate to vector DB metadata"""
    now = datetime.utcnow().isoformat()
    metadata = {
        "id": email_id,
        "user_id": str(email.user_id),
        "gmail_message_id": email.gmail_message_id,
        "gmail_thread_id": email.gmail_thread_id or "",
        "subject": email.subject or "",
        "from_email": email.from_email or "",
        "to_email": email.to_email or "",
        "cc_email": email.cc_email or "",
        "bcc_email": email.bcc_email or "",
        "snippet": email.snippet or "",
        "body_html": email.body_html or "",
        "body_plain": email.body_plain or "",
        "date": email.date or "",
        "has_attachments": email.has_attachments,
        "attachment_count": str(email.attachment_count),
        "is_sent": email.is_sent,
        "is_read": False,
        "is_processed": False,
        "is_rate_sheet": False,
        "created_at": now,
        "updated_at": now,
    }
    
    # Store AI analysis if available (like rate sheets do)
    if ai_analysis:
        import json
        metadata["ai_analysis"] = json.dumps(ai_analysis)
        metadata["ai_summary"] = ai_analysis.get("summary", "")[:500]  # Truncate for metadata
        metadata["ai_sentiment"] = ai_analysis.get("sentiment", "neutral")
        metadata["ai_priority"] = ai_analysis.get("priority", "medium")
    
    # Store drafted response if available
    if drafted_response:
        import json
        metadata["drafted_response"] = json.dumps(drafted_response)
        metadata["has_draft"] = "true"
    
    return metadata


async def get_user_organization_id(user_id: int) -> Optional[int]:
    """
    Get user's organization_id from user service (internal endpoint).
    This is a service-to-service call, no auth token required.
    Returns None if organization cannot be determined.
    """
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            org_url = f"{settings.USER_SERVICE_URL}/api/user/internal/user/{user_id}/organization-id"
            logger.debug(f"Getting organization_id from user service: {org_url}")
            response = await client.get(org_url)
            
            if response.status_code == 200:
                org_data = response.json()
                organization_id = org_data.get('organization_id')
                if organization_id:
                    logger.info(f"✅ Got organization_id: {organization_id} for user {user_id}")
                    return organization_id
                else:
                    logger.debug(f"User {user_id} has no organization: {org_data.get('message', 'Unknown')}")
                    return None
            else:
                logger.warning(f"Failed to get organization_id: HTTP {response.status_code}")
                return None
    except Exception as e:
        logger.warning(f"Could not get organization_id for user {user_id}: {e}")
        return None


async def get_user_drafting_status(user_id: int) -> Dict[str, Any]:
    """
    Get user's email drafting status from auth service (internal endpoint).
    Returns drafting enabled status and timestamp.
    """
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            # Use internal endpoint to get drafting status
            drafting_url = f"{settings.AUTH_SERVICE_URL}/api/auth/internal/user/{user_id}/drafting-status"
            logger.debug(f"Getting drafting status from auth service: {drafting_url}")
            response = await client.get(drafting_url)
            
            if response.status_code == 200:
                drafting_data = response.json()
                return {
                    "email_drafting_enabled": drafting_data.get("email_drafting_enabled", False),
                    "email_drafting_enabled_at": drafting_data.get("email_drafting_enabled_at")
                }
            else:
                logger.warning(f"Failed to get drafting status: HTTP {response.status_code}")
                return {"email_drafting_enabled": False, "email_drafting_enabled_at": None}
    except Exception as e:
        logger.warning(f"Could not get drafting status for user {user_id}: {e}")
        return {"email_drafting_enabled": False, "email_drafting_enabled_at": None}


def should_draft_email(email_date: Optional[str], drafting_enabled_at: Optional[str]) -> bool:
    """
    Check if an email should be drafted based on:
    1. Drafting must be enabled
    2. Email must have arrived AFTER drafting was enabled
    """
    if not drafting_enabled_at:
        return False  # Drafting never enabled
    
    if not email_date:
        return False  # Can't determine email date
    
    try:
        from datetime import datetime
        from email.utils import parsedate_to_datetime
        
        # Parse email date - handle both RFC 2822 (email format) and ISO format
        email_dt = None
        
        # Try RFC 2822 format first (e.g., "Tue, 27 Jan 2026 21:59:36 +0530")
        try:
            email_dt = parsedate_to_datetime(email_date)
        except (TypeError, ValueError):
            pass
        
        # Fallback to ISO format
        if email_dt is None:
            try:
                email_dt = datetime.fromisoformat(email_date.replace('Z', '+00:00'))
            except (TypeError, ValueError):
                pass
        
        if email_dt is None:
            logger.warning(f"Could not parse email date: {email_date}")
            return True  # If we can't parse email date, assume it's new and draft it
        
        # Parse enabled timestamp (always ISO format from database)
        enabled_dt = datetime.fromisoformat(drafting_enabled_at.replace('Z', '+00:00'))
        
        # Make both timezone-aware for comparison
        if email_dt.tzinfo is None:
            from datetime import timezone
            email_dt = email_dt.replace(tzinfo=timezone.utc)
        if enabled_dt.tzinfo is None:
            from datetime import timezone
            enabled_dt = enabled_dt.replace(tzinfo=timezone.utc)
        
        # Only draft if email arrived AFTER drafting was enabled
        should_draft = email_dt >= enabled_dt
        logger.debug(f"Date comparison: email_dt={email_dt.isoformat()}, enabled_dt={enabled_dt.isoformat()}, should_draft={should_draft}")
        return should_draft
    except Exception as e:
        logger.warning(f"Error comparing dates: {e}, email_date={email_date}, enabled_at={drafting_enabled_at}")
        return True  # If we can't parse dates, assume new email and draft it


async def draft_email_response_auto(email_data: EmailCreate, organization_id: int) -> Optional[Dict[str, Any]]:
    """Automatically draft an email response based on rate sheet data"""
    try:
        # Extract email query from email content
        email_query = email_data.body_plain or email_data.snippet or email_data.subject or ""
        
        if not email_query:
            logger.debug(f"No email query content for auto-draft (email: {email_data.gmail_message_id})")
            return None
        
        # Quick pre-check: Skip obvious non-freight emails
        email_text_lower = email_query.lower()
        skip_keywords = [
            'linkedin', 'notification', 'newsletter', 'unsubscribe',
            'shared a post', 'commented on', 'liked your', 'followed you',
            'facebook', 'twitter', 'instagram', 'social media',
            'do not reply', 'noreply', 'automated',
        ]
        
        if any(keyword in email_text_lower for keyword in skip_keywords):
            logger.info(f"Skipping auto-draft for email {email_data.gmail_message_id} - appears to be notification/newsletter")
            return None
        
        logger.info(f"Auto-drafting response for email {email_data.gmail_message_id}, org_id: {organization_id}")
        
        # Use longer timeout for draft generation (search + re-rank + AI response can take time)
        async with httpx.AsyncClient(timeout=120.0) as client:
            draft_response = await client.post(
                f"{settings.RATE_SHEET_SERVICE_URL}/api/rate-sheets/draft-email-response?organization_id={organization_id}",
                json={
                    "email_query": email_query,
                    "original_email_subject": email_data.subject,
                    "original_email_from": email_data.from_email,
                    "limit": 5
                },
                headers={"Content-Type": "application/json"},
                timeout=120.0  # 2 minutes for complex queries with AI processing
            )
            
            if draft_response.status_code == 200:
                draft_data = draft_response.json()
                
                # Check if draft was skipped (not a freight inquiry or low confidence)
                if draft_data.get("skipped"):
                    logger.info(f"Auto-draft skipped for email {email_data.gmail_message_id}: {draft_data.get('skip_reason', 'Unknown reason')}")
                    return None  # Don't store skipped drafts
                
                # Map response fields to frontend-expected format
                # Rate Sheet Service returns: {draft: {...}, confidence_score: ...}
                # Frontend expects: {drafted_email: {...}, confidence_score: ...}
                if "draft" in draft_data and "drafted_email" not in draft_data:
                    draft_data["drafted_email"] = draft_data.pop("draft")
                    logger.debug(f"Mapped 'draft' to 'drafted_email' for email {email_data.gmail_message_id}")
                
                # Always return draft - mark for review if confidence is low
                # User can decide whether to use the draft even if confidence is low
                confidence = draft_data.get("confidence_score", 0.0)
                MIN_AUTO_DRAFT_CONFIDENCE = 0.30  # 30% minimum - below this, mark for review
                
                if confidence < MIN_AUTO_DRAFT_CONFIDENCE:
                    logger.info(f"⚠️  Low confidence draft for email {email_data.gmail_message_id} ({confidence:.2%} < {MIN_AUTO_DRAFT_CONFIDENCE:.2%})")
                    # Mark as low confidence for manual review
                    draft_data["low_confidence"] = True
                    draft_data["requires_review"] = True
                    draft_data["confidence_warning"] = f"Low confidence ({confidence:.2%}) - please review before sending"
                    logger.info(f"✅ Draft generated but marked for review (confidence: {confidence:.2%})")
                else:
                    logger.info(f"✅ Successfully auto-drafted response for email {email_data.gmail_message_id} (confidence: {confidence:.2%})")
                
                # Log the draft content for debugging
                drafted_email = draft_data.get("drafted_email", {})
                logger.info(f"📝 Draft content for email {email_data.gmail_message_id}: subject='{drafted_email.get('subject', 'N/A')}', body_length={len(drafted_email.get('body', ''))}")
                
                # Always return draft (even if low confidence) - let user decide
                return draft_data
            else:
                error_text = draft_response.text[:500] if hasattr(draft_response, 'text') else "No error text"
                logger.warning(f"Auto-draft failed for email {email_data.gmail_message_id}: HTTP {draft_response.status_code} - {error_text}")
                return None
                
    except httpx.ReadTimeout:
        # Log timeout with context (no silent failure per BACKEND_REVIEW.md)
        logger.warning(
            f"Auto-draft timeout for email {email_data.gmail_message_id} - draft generation took too long. Email will be stored without draft.",
            extra={
                "gmail_message_id": email_data.gmail_message_id,
                "organization_id": organization_id,
                "exception_type": "ReadTimeout"
            }
        )
        return None
    except httpx.TimeoutException:
        # Log timeout with context (no silent failure)
        logger.warning(
            f"Auto-draft timeout for email {email_data.gmail_message_id} - request timed out. Email will be stored without draft.",
            extra={
                "gmail_message_id": email_data.gmail_message_id,
                "organization_id": organization_id,
                "exception_type": "TimeoutException"
            }
        )
        return None
    except Exception as e:
        # Log error with full context (no silent failure per BACKEND_REVIEW.md)
        logger.error(
            f"Error auto-drafting response for email {email_data.gmail_message_id}: {type(e).__name__}: {str(e)}",
            exc_info=True,
            extra={
                "gmail_message_id": email_data.gmail_message_id,
                "organization_id": organization_id,
                "exception_type": type(e).__name__
            }
        )
        return None


async def _draft_and_update_email_async(email_id: str, email_data: EmailCreate, organization_id: int):
    """
    Async helper function to draft email response and update stored email
    This runs in the background so email storage is not blocked
    
    Per BACKEND_REVIEW.md: Background tasks should not fail silently
    """
    try:
        logger.info(f"🔄 Background: Starting async draft for email {email_id}")
        drafted_response = await draft_email_response_auto(email_data, organization_id)
        
        if drafted_response:
            logger.info(f"✅ Background: Draft completed for email {email_id}, updating metadata...")
            # Update email metadata with drafted response
            success = await update_email_metadata(email_id, {
                "drafted_response": json.dumps(drafted_response),
                "has_draft": "true"
            })
            if success:
                logger.info(f"✅ Background: Successfully updated email {email_id} with draft response")
            else:
                # Log failure with context (no silent failure)
                logger.warning(
                    f"⚠️  Background: Failed to update email {email_id} metadata with draft",
                    extra={
                        "email_id": email_id,
                        "gmail_message_id": email_data.gmail_message_id,
                        "organization_id": organization_id
                    }
                )
        else:
            # Log when draft returns None (no silent failure)
            logger.warning(
                f"⚠️  Background: Draft returned None for email {email_id}",
                extra={
                    "email_id": email_id,
                    "gmail_message_id": email_data.gmail_message_id,
                    "organization_id": organization_id
                }
            )
    except Exception as e:
        # Log background task errors with full context (no silent failures per BACKEND_REVIEW.md)
        logger.error(
            f"❌ Background: Error in async draft/update for email {email_id}: {type(e).__name__}: {str(e)}",
            exc_info=True,
            extra={
                "email_id": email_id,
                "gmail_message_id": email_data.gmail_message_id,
                "organization_id": organization_id,
                "exception_type": type(e).__name__
            }
        )
        # Don't re-raise - background task failures shouldn't crash the service
        # But error is logged for monitoring/debugging


async def _process_inbound_reply_async(email_data: EmailCreate, organization_id: int):
    """
    Background: call Rate Sheet Service process-inbound-reply to detect quote acceptance and create order.
    """
    try:
        email_content = email_data.body_plain or email_data.snippet or email_data.subject or ""
        if not email_content:
            return
        async with httpx.AsyncClient(timeout=25.0) as client:
            r = await client.post(
                f"{settings.RATE_SHEET_SERVICE_URL}/api/rate-sheets/process-inbound-reply",
                json={
                    "user_id": email_data.user_id,
                    "organization_id": organization_id,
                    "email_content": email_content,
                    "subject": email_data.subject,
                    "from_email": email_data.from_email,
                    "thread_id": email_data.gmail_thread_id,
                },
                timeout=25.0,
            )
            if r.status_code == 200:
                data = r.json()
                if data.get("processed") and data.get("order_id"):
                    logger.info(f"✅ Quote acceptance: created order {data.get('order_id')} for user {email_data.user_id}")
            else:
                logger.warning(f"process-inbound-reply returned {r.status_code}: {r.text[:200]}")
    except Exception as e:
        logger.warning(f"process-inbound-reply background task failed: {e}", exc_info=False)


async def store_email(email_data: EmailCreate, organization_id: Optional[int] = None, auto_draft: bool = True) -> Optional[Email]:
    """
    Store an email in the vector DB and optionally auto-draft a response
    
    IMPORTANT: Email Privacy Model
    - Emails are USER-SPECIFIC and PRIVATE to each individual user
    - Emails are NOT shared within organizations (unlike rate sheets)
    - Each user can ONLY see their own emails
    - organization_id is ONLY used for auto-drafting responses (to search organization's rate sheets)
    - organization_id is NOT stored in email metadata - emails are identified by user_id only
    
    Args:
        email_data: Email data to store (must include user_id)
        organization_id: Optional organization_id (ONLY used for auto-drafting responses, not stored with email)
        auto_draft: If True, automatically draft a response after storing (requires organization_id to search rate sheets)
    """
    logger.info(f"📧 store_email called: gmail_id={email_data.gmail_message_id}, user_id={email_data.user_id}, org_id={organization_id}, auto_draft={auto_draft}")
    
    # Generate deterministic ID FIRST (before any checks)
    # This ensures we use the same ID for duplicate detection
    email_id = _generate_email_id(email_data.user_id, email_data.gmail_message_id)
    
    # Get or create a lock for this specific email_id to prevent race conditions
    async with _locks_lock:
        if email_id not in _email_storage_locks:
            # Clean up old locks if we're approaching the limit
            if len(_email_storage_locks) >= _MAX_LOCKS:
                # Remove oldest 10% of locks (simple cleanup strategy)
                keys_to_remove = list(_email_storage_locks.keys())[:max(1, _MAX_LOCKS // 10)]
                for key in keys_to_remove:
                    _email_storage_locks.pop(key, None)
                logger.debug(f"Cleaned up {len(keys_to_remove)} old locks from memory")
            _email_storage_locks[email_id] = asyncio.Lock()
        lock = _email_storage_locks[email_id]
    
    # Acquire lock for this email_id (prevents concurrent storage of same email)
    async with lock:
        try:
            logger.info("🔍 Ensuring collection exists...")
            await ensure_collection_exists()
            
            # Check if email already exists using deterministic ID (atomic check)
            logger.info(f"🔍 Checking if email {email_data.gmail_message_id} (ID: {email_id}) already exists...")
            async with httpx.AsyncClient() as client:
                existing_doc_response = await client.get(
                    f"{settings.VECTOR_DB_SERVICE_URL}/api/vector/collections/{EMAILS_COLLECTION}/documents/{email_id}",
                    timeout=30.0
                )
                if existing_doc_response.status_code == 200:
                    # Email already exists - return existing
                    logger.info(f"⚠️  Email {email_data.gmail_message_id} already exists with ID {email_id}, returning existing")
                    existing_data = existing_doc_response.json()
                    existing_metadata = existing_data.get("metadata", {})
                    existing_document = existing_data.get("document", "")
                    return _metadata_to_email(email_id, existing_metadata, existing_document)
            
            logger.info(f"✅ Email {email_data.gmail_message_id} is new, proceeding with storage")
            
            # Get organization_id if not provided and auto_draft is enabled
            org_id = organization_id
            logger.info(f"🔍 Organization ID: provided={organization_id}, auto_draft={auto_draft}")
            
            if auto_draft and not org_id:
                logger.info(f"🔍 Attempting to get organization_id for user {email_data.user_id}...")
                org_id = await get_user_organization_id(email_data.user_id)
                if not org_id:
                    logger.warning(f"⚠️  Could not get organization_id for user {email_data.user_id}, skipping auto-draft")
                    auto_draft = False
                else:
                    logger.info(f"✅ Got organization_id: {org_id}")
            
            # AI Analysis: Extract structured data from email (like rate sheets do)
            # Always analyze emails - use subject if body is empty
            ai_analysis = None
            try:
                # Get email content - use subject if body is empty (some emails are subject-only)
                email_content = email_data.body_plain or email_data.snippet or email_data.subject or ""
                
                if not email_content:
                    logger.debug(f"⚠️  No content available for AI analysis for {email_data.gmail_message_id}, skipping")
                else:
                    logger.info(f"🤖 Analyzing email {email_data.gmail_message_id} with AI (content length: {len(email_content)})...")
                    async with httpx.AsyncClient(timeout=30.0) as client:
                        try:
                            analysis_response = await client.post(
                                f"{settings.AI_SERVICE_URL}/api/ai/analyze-email",
                                json={
                                    "content": email_content,
                                    "subject": email_data.subject or "",
                                    "from": email_data.from_email or ""
                                },
                                timeout=30.0
                            )
                            analysis_response.raise_for_status()  # Raise exception for non-200 status codes
                            ai_analysis = analysis_response.json()
                            logger.info(f"✅ AI analysis completed for email {email_data.gmail_message_id}: sentiment={ai_analysis.get('sentiment', 'unknown')}, priority={ai_analysis.get('priority', 'unknown')}")
                        except httpx.HTTPStatusError as e:
                            error_text = ""
                            try:
                                error_text = e.response.text[:200] if e.response else "No response"
                            except:
                                pass
                            logger.warning(f"⚠️  AI analysis HTTP error (non-critical): {e.response.status_code if e.response else 'Unknown'} - {error_text}, continuing without analysis")
                        except httpx.TimeoutException:
                            logger.warning(f"⚠️  AI analysis timeout (non-critical): Request took longer than 30s, continuing without analysis")
            except httpx.ConnectError as e:
                logger.warning(f"⚠️  AI service connection error (non-critical): Cannot connect to {settings.AI_SERVICE_URL} - {str(e) or 'Connection refused'}, continuing without analysis")
            except Exception as e:
                error_msg = str(e) if str(e) else f"{type(e).__name__} (no message)"
                logger.warning(f"⚠️  AI analysis error (non-critical): {error_msg}, continuing without analysis", exc_info=True)
            
            # Check if user has enabled email drafting and if email should be drafted
            # Only draft emails that arrived AFTER drafting was enabled
            should_draft = False
            if auto_draft and org_id:
                # Get user's drafting status
                drafting_status = await get_user_drafting_status(email_data.user_id)
                drafting_enabled = drafting_status.get("email_drafting_enabled", False)
                drafting_enabled_at = drafting_status.get("email_drafting_enabled_at")
                
                if drafting_enabled:
                    # Check if email arrived after drafting was enabled
                    should_draft = should_draft_email(email_data.date, drafting_enabled_at)
                    if should_draft:
                        logger.info(f"✅ Drafting enabled - will draft email {email_data.gmail_message_id} (arrived after {drafting_enabled_at})")
                    else:
                        logger.info(f"⏭️  Skipping draft for email {email_data.gmail_message_id} - arrived before drafting was enabled ({email_data.date} < {drafting_enabled_at})")
                else:
                    logger.info(f"⏭️  Skipping draft for email {email_data.gmail_message_id} - drafting not enabled by user")
            
            # Store email first, then draft response asynchronously (non-blocking)
            # This ensures emails are always stored even if drafting takes a long time
            drafted_response = None
            if should_draft and org_id:
                logger.info(f"🤖 Will auto-draft response for email {email_data.gmail_message_id} with org_id {org_id} (async)")
                # Start async draft task (fire and forget) - runs in background
                # Email will be stored immediately, draft will be added when ready
                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        loop.create_task(_draft_and_update_email_async(email_id, email_data, org_id))
                    else:
                        asyncio.ensure_future(_draft_and_update_email_async(email_id, email_data, org_id))
                except RuntimeError:
                    # If no event loop, create a new one
                    asyncio.ensure_future(_draft_and_update_email_async(email_id, email_data, org_id))
            else:
                logger.info(f"ℹ️  Skipping auto-draft (should_draft={should_draft}, org_id={org_id})")
            
            # Create full raw email content as a structured string
            # Store complete email content for both retrieval and semantic search
            # Format: All email fields including full body (both HTML and plain)
            raw_email_content_parts = []
            if email_data.subject:
                raw_email_content_parts.append(f"Subject: {email_data.subject}")
            if email_data.from_email:
                raw_email_content_parts.append(f"From: {email_data.from_email}")
            if email_data.to_email:
                raw_email_content_parts.append(f"To: {email_data.to_email}")
            if email_data.cc_email:
                raw_email_content_parts.append(f"CC: {email_data.cc_email}")
            if email_data.bcc_email:
                raw_email_content_parts.append(f"BCC: {email_data.bcc_email}")
            if email_data.date:
                raw_email_content_parts.append(f"Date: {email_data.date}")
            raw_email_content_parts.append("")  # Separator
            if email_data.body_plain:
                raw_email_content_parts.append(f"Body (Plain):\n{email_data.body_plain}")
            if email_data.body_html:
                raw_email_content_parts.append(f"Body (HTML):\n{email_data.body_html}")
            if email_data.snippet:
                raw_email_content_parts.append(f"Snippet: {email_data.snippet}")
            
            # Full raw email content as document (for retrieval + embeddings)
            raw_email_content = "\n".join(raw_email_content_parts)
            
            # Create metadata (including drafted response and AI analysis if available)
            metadata = _email_to_metadata(email_data, email_id, drafted_response, ai_analysis)
            
            # Store the email (vector DB's add method handles upsert, so duplicates are safe)
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{settings.VECTOR_DB_SERVICE_URL}/api/vector/collections/{EMAILS_COLLECTION}/documents",
                    json={
                        "documents": [raw_email_content],  # Full raw email content
                        "metadatas": [metadata],  # Metadata with all email fields + draft
                        "ids": [email_id]  # Deterministic ID ensures upsert behavior
                    },
                    timeout=60.0  # Longer timeout for embedding generation
                )
                
                logger.info(f"📤 Storing email in ChromaDB (ID: {email_id})...")
                if response.status_code == 200:
                    success_msg = f"✅ Stored email {email_data.gmail_message_id} with ID {email_id}"
                    if drafted_response:
                        success_msg += " with auto-drafted response"
                    logger.info(success_msg)
                    stored_email = _metadata_to_email(email_id, metadata, raw_email_content)
                    # Process inbound reply in background (quote acceptance -> create order)
                    if org_id:
                        try:
                            loop = asyncio.get_event_loop()
                            if loop.is_running():
                                loop.create_task(_process_inbound_reply_async(email_data, org_id))
                            else:
                                asyncio.ensure_future(_process_inbound_reply_async(email_data, org_id))
                        except RuntimeError:
                            asyncio.ensure_future(_process_inbound_reply_async(email_data, org_id))
                    # drafted_response is already included in the Email model via _metadata_to_email
                    return stored_email
                else:
                    error_text = response.text[:500] if hasattr(response, 'text') else "No error text"
                    logger.error(f"❌ Failed to store email in ChromaDB: HTTP {response.status_code} - {error_text}")
                    return None
                    
        except Exception as e:
            # Log error with full context (no silent failures per BACKEND_REVIEW.md)
            logger.error(
                f"❌ Error storing email {email_data.gmail_message_id}: {type(e).__name__}: {str(e)}",
                exc_info=True,
                extra={
                    "gmail_message_id": email_data.gmail_message_id,
                    "user_id": email_data.user_id,
                    "organization_id": organization_id,
                    "exception_type": type(e).__name__
                }
            )
            # Return None to indicate failure (caller should handle)
            return None
        finally:
            # Note: Lock cleanup happens automatically when we reach MAX_LOCKS
            # This prevents memory leaks while maintaining thread safety
            pass


def _generate_email_id(user_id: int, gmail_message_id: str) -> str:
    """
    Generate a deterministic email ID based on user_id and gmail_message_id.
    This ensures the same email always gets the same ID, preventing duplicates.
    """
    import hashlib
    # Create a unique composite key
    composite_key = f"{user_id}:{gmail_message_id}"
    # Generate deterministic hash-based ID
    hash_obj = hashlib.sha256(composite_key.encode('utf-8'))
    # Use first 32 chars of hex digest (UUID length)
    return hash_obj.hexdigest()[:32]


async def get_email_by_gmail_id(user_id: int, gmail_message_id: str) -> Optional[Email]:
    """Get an email by Gmail message ID using deterministic ID lookup"""
    try:
        # Generate the deterministic ID for this email
        email_id = _generate_email_id(user_id, gmail_message_id)
        
        # Try to get the document directly by ID (fast and atomic)
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{settings.VECTOR_DB_SERVICE_URL}/api/vector/collections/{EMAILS_COLLECTION}/documents/{email_id}",
                timeout=30.0
            )
            
            if response.status_code == 200:
                data = response.json()
                metadata = data.get("metadata", {})
                document = data.get("document", "")
                
                # Verify it matches (safety check)
                if (metadata.get("gmail_message_id") == gmail_message_id and 
                    str(metadata.get("user_id")) == str(user_id)):
                    return _metadata_to_email(email_id, metadata, document)
            
            # Fallback: if direct lookup fails, try semantic search (for old emails with random IDs)
            logger.debug(f"Direct lookup failed for {email_id}, trying semantic search fallback...")
            response = await client.post(
                f"{settings.VECTOR_DB_SERVICE_URL}/api/vector/collections/{EMAILS_COLLECTION}/query",
                json={
                    "query_texts": [gmail_message_id],
                    "n_results": 100  # Get more results to filter by user_id and exact match
                },
                timeout=30.0
            )
            
            if response.status_code == 200:
                data = response.json()
                results = data.get("results", {})
                ids = results.get("ids", [[]])[0]
                metadatas = results.get("metadatas", [[]])[0]
                documents = results.get("documents", [[]])[0]
                
                for i, meta in enumerate(metadatas):
                    if (meta.get("gmail_message_id") == gmail_message_id and 
                        str(meta.get("user_id")) == str(user_id)):
                        return _metadata_to_email(ids[i], meta, documents[i] if documents else "")
                        
            return None
            
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            # Document not found by ID - this is fine, email doesn't exist
            return None
        logger.error(f"HTTP error getting email by Gmail ID: {e}")
        return None
    except Exception as e:
        logger.error(f"Error getting email by Gmail ID: {e}")
        return None


async def get_email_by_id(email_id: str, user_id: Optional[int] = None) -> Optional[Email]:
    """
    Get an email by its ID
    
    IMPORTANT: If user_id is provided, verifies the email belongs to that user (user-level privacy).
    Returns None if the email doesn't belong to the specified user.
    """
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{settings.VECTOR_DB_SERVICE_URL}/api/vector/collections/{EMAILS_COLLECTION}/documents/{email_id}",
                timeout=10.0
            )
            
            if response.status_code == 200:
                data = response.json()
                email = _metadata_to_email(data['id'], data['metadata'], data.get('document', ''))
                
                # SECURITY: Verify user ownership if user_id provided
                if user_id is not None:
                    if email.user_id != user_id:
                        logger.warning(f"Access denied: Email {email_id} belongs to user {email.user_id}, but request was for user {user_id}")
                        return None
                
                return email
            return None
            
    except Exception as e:
        logger.error(f"Error getting email by ID: {e}")
        return None


async def get_user_emails(user_id: int, limit: int = 100, is_read: Optional[bool] = None) -> List[Email]:
    """Get emails for a user"""
    try:
        async with httpx.AsyncClient() as client:
            # OPTIMIZED: Use a single generic query instead of multiple queries
            # This reduces overhead from 5 queries to 1 query
            # Request enough results to cover all user's emails (most users won't have more than limit*3 emails)
            all_emails_dict = {}  # Use dict to avoid duplicates by email ID
            
            try:
                # Single query with a generic term that matches all emails
                response = await client.post(
                    f"{settings.VECTOR_DB_SERVICE_URL}/api/vector/collections/{EMAILS_COLLECTION}/query",
                    json={
                        "query_texts": ["email"],  # Single generic query
                        "n_results": limit * 3  # Get enough to cover all user's emails
                    },
                    timeout=30.0
                )
                
                if response.status_code == 200:
                    data = response.json()
                    results = data.get("results", {})
                    ids = results.get("ids", [[]])[0]
                    metadatas = results.get("metadatas", [[]])[0]
                    documents = results.get("documents", [[]])[0]
                    
                    # Add emails that match user_id to our dict
                    for i, meta in enumerate(metadatas):
                        if str(meta.get("user_id")) == str(user_id):
                            email_id = ids[i]
                            if email_id not in all_emails_dict:
                                if is_read is None or meta.get("is_read") == is_read:
                                    all_emails_dict[email_id] = _metadata_to_email(
                                        ids[i], 
                                        meta, 
                                        documents[i] if documents else ""
                                    )
            except Exception as e:
                logger.debug(f"Error querying emails: {e}")
                # Continue even if query fails - return what we have
            
            # Convert dict to list and sort by date (newest first)
            emails = list(all_emails_dict.values())
            emails.sort(key=lambda x: x.date or "", reverse=True)
            
            # Limit results
            return emails[:limit]
                
    except Exception as e:
        logger.error(f"Error getting user emails: {e}", exc_info=True)
        return []


async def get_new_emails(user_id: int, limit: int = 50) -> List[Email]:
    """Get unread emails for a user"""
    return await get_user_emails(user_id, limit=limit, is_read=False)


async def update_email_metadata(email_id: str, updates: Dict[str, Any]) -> bool:
    """Update email metadata in vector DB"""
    try:
        updates['updated_at'] = datetime.utcnow().isoformat()
        
        async with httpx.AsyncClient() as client:
            response = await client.patch(
                f"{settings.VECTOR_DB_SERVICE_URL}/api/vector/collections/{EMAILS_COLLECTION}/documents/{email_id}",
                json={"metadata": updates},
                timeout=10.0
            )
            return response.status_code == 200
            
    except Exception as e:
        logger.error(f"Error updating email metadata: {e}")
        return False


async def mark_email_as_read(email_id: str, user_id: Optional[int] = None) -> bool:
    """
    Mark an email as read
    
    IMPORTANT: If user_id is provided, verifies the email belongs to that user (user-level privacy).
    """
    # Verify user ownership if user_id provided
    if user_id is not None:
        email = await get_email_by_id(email_id, user_id)
        if not email:
            logger.warning(f"Access denied: Cannot mark email {email_id} as read - doesn't belong to user {user_id}")
            return False
    
    return await update_email_metadata(email_id, {"is_read": True})


async def mark_email_as_processed(email_id: str, user_id: Optional[int] = None) -> bool:
    """
    Mark an email as processed
    
    IMPORTANT: If user_id is provided, verifies the email belongs to that user (user-level privacy).
    """
    # Verify user ownership if user_id provided
    if user_id is not None:
        email = await get_email_by_id(email_id, user_id)
        if not email:
            logger.warning(f"Access denied: Cannot mark email {email_id} as processed - doesn't belong to user {user_id}")
            return False
    
    return await update_email_metadata(email_id, {"is_processed": True})


async def mark_email_as_rate_sheet(email_id: str, is_rate_sheet: bool = True, user_id: Optional[int] = None) -> bool:
    """
    Mark an email as a rate sheet
    
    IMPORTANT: If user_id is provided, verifies the email belongs to that user (user-level privacy).
    """
    # Verify user ownership if user_id provided
    if user_id is not None:
        email = await get_email_by_id(email_id, user_id)
        if not email:
            logger.warning(f"Access denied: Cannot mark email {email_id} as rate sheet - doesn't belong to user {user_id}")
            return False
    
    return await update_email_metadata(email_id, {"is_rate_sheet": is_rate_sheet})


async def search_emails_semantic(user_id: int, query: str, limit: int = 20) -> List[Email]:
    """Search emails using semantic similarity with BGE embeddings"""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{settings.VECTOR_DB_SERVICE_URL}/api/vector/collections/{EMAILS_COLLECTION}/query",
                json={
                    "query_texts": [query],
                    "n_results": limit * 3  # Get more to filter by user
                },
                timeout=30.0
            )
            
            if response.status_code == 200:
                data = response.json()
                results = data.get("results", {})
                ids = results.get("ids", [[]])[0]
                metadatas = results.get("metadatas", [[]])[0]
                documents = results.get("documents", [[]])[0]
                distances = results.get("distances", [[]])[0]
                
                emails = []
                for i, meta in enumerate(metadatas):
                    if str(meta.get("user_id")) == str(user_id):
                        email = _metadata_to_email(
                            ids[i],
                            meta,
                            documents[i] if documents else ""
                        )
                        emails.append(email)
                        if len(emails) >= limit:
                            break
                
                return emails
                
            return []
            
    except Exception as e:
        logger.error(f"Error searching emails: {e}")
        return []


async def get_user_drafts(user_id: int, limit: int = 100, offset: int = 0) -> tuple:
    """
    Get all emails with drafted responses for a user (with pagination)
    
    IMPORTANT: User-Level Privacy
    - Returns ONLY drafts for the specified user_id
    - Filters by user_id to ensure user privacy
    - Users can only see their own drafts
    
    Args:
        user_id: User ID (REQUIRED for user-level filtering)
        limit: Number of results per page
        offset: Offset for pagination
        
    Returns:
        Tuple of (list of emails with drafts, total count)
    """
    try:
        async with httpx.AsyncClient() as client:
            # Query for emails - use multiple queries to get all emails
            query_terms = [
                "email message",
                "mail inbox",
                "message",
                "email",
                "inbox"
            ]
            
            all_emails_dict = {}  # Use dict to avoid duplicates
            
            for query_term in query_terms:
                try:
                    response = await client.post(
                        f"{settings.VECTOR_DB_SERVICE_URL}/api/vector/collections/{EMAILS_COLLECTION}/query",
                        json={
                            "query_texts": [query_term],
                            "n_results": limit * 10  # Get more to filter drafts
                        },
                        timeout=30.0
                    )
                    
                    if response.status_code == 200:
                        data = response.json()
                        results = data.get("results", {})
                        ids = results.get("ids", [[]])[0]
                        metadatas = results.get("metadatas", [[]])[0]
                        documents = results.get("documents", [[]])[0]
                        
                        # SECURITY: Filter emails that belong to user AND have drafts
                        # This ensures user-level privacy - users can only see their own drafts
                        for i, meta in enumerate(metadatas):
                            meta_user_id = str(meta.get("user_id"))
                            # CRITICAL: Only include emails that belong to this specific user
                            if meta_user_id == str(user_id):
                                # Check if email has a draft (has_draft field or drafted_response field)
                                has_draft = meta.get("has_draft") == "true" or meta.get("has_draft") == True
                                has_drafted_response = bool(meta.get("drafted_response"))
                                
                                if has_draft or has_drafted_response:
                                    email_id = ids[i]
                                    if email_id not in all_emails_dict:
                                        email = _metadata_to_email(
                                            ids[i],
                                            meta,
                                            documents[i] if documents else ""
                                        )
                                        # Double-check it has a draft and belongs to user
                                        if email.drafted_response and email.user_id == user_id:
                                            all_emails_dict[email_id] = email
                                        else:
                                            logger.debug(f"Skipping email {email_id} - no draft or user mismatch (email.user_id={email.user_id}, requested={user_id})")
                            else:
                                # Skip emails from other users (user-level privacy)
                                logger.debug(f"Skipping email - belongs to user {meta_user_id}, requested {user_id}")
                                            
                except Exception as e:
                    logger.debug(f"Error querying drafts with term '{query_term}': {e}")
                    continue
            
            # Convert to list and sort by date (newest first)
            emails_with_drafts = list(all_emails_dict.values())
            emails_with_drafts.sort(key=lambda x: x.date or x.created_at or "", reverse=True)
            
            total_count = len(emails_with_drafts)
            
            # Apply pagination
            paginated_emails = emails_with_drafts[offset:offset + limit]
            
            logger.info(f"Found {total_count} emails with drafts for user {user_id}, returning {len(paginated_emails)} (offset: {offset}, limit: {limit})")
            
            return paginated_emails, total_count
                
    except Exception as e:
        logger.error(f"Error getting user drafts: {e}", exc_info=True)
        return [], 0


async def delete_email(email_id: str) -> bool:
    """Delete an email"""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.delete(
                f"{settings.VECTOR_DB_SERVICE_URL}/api/vector/collections/{EMAILS_COLLECTION}/documents/{email_id}",
                timeout=10.0
            )
            return response.status_code == 200
            
    except Exception as e:
        logger.error(f"Error deleting email: {e}")
        return False


async def delete_user_emails(user_id: int) -> int:
    """Delete all emails for a user"""
    try:
        # Get all user emails first
        emails = await get_user_emails(user_id, limit=1000)
        deleted = 0
        
        for email in emails:
            if await delete_email(email.id):
                deleted += 1
        
        logger.info(f"Deleted {deleted} emails for user {user_id}")
        return deleted
        
    except Exception as e:
        logger.error(f"Error deleting user emails: {e}")
        return 0
