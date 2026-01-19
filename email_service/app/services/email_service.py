"""Email service - stores all data in Vector DB with BGE embeddings"""
import httpx
import uuid
from typing import List, Optional, Dict, Any
from datetime import datetime
from ..core.config import settings
from ..models import Email, EmailCreate, EmailUpdate
import logging

logger = logging.getLogger(__name__)

# Collection name for emails in vector DB
EMAILS_COLLECTION = "emails"


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
    return Email(
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
        created_at=metadata.get("created_at"),
        updated_at=metadata.get("updated_at"),
    )


def _email_to_metadata(email: EmailCreate, email_id: str) -> Dict[str, Any]:
    """Convert EmailCreate to vector DB metadata"""
    now = datetime.utcnow().isoformat()
    return {
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


async def store_email(email_data: EmailCreate) -> Optional[Email]:
    """Store an email in the vector DB"""
    try:
        await ensure_collection_exists()
        
        # Check if email already exists
        existing = await get_email_by_gmail_id(email_data.user_id, email_data.gmail_message_id)
        if existing:
            logger.info(f"Email {email_data.gmail_message_id} already exists")
            return existing
        
        # Generate unique ID
        email_id = str(uuid.uuid4())
        
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
        
        # Create metadata
        metadata = _email_to_metadata(email_data, email_id)
        
        async with httpx.AsyncClient() as client:
            # Store the full raw email content as the document
            # Vector DB will:
            # 1. Store the raw email text (for retrieval)
            # 2. Generate embeddings from it (for semantic search)
            # 3. Store metadata (for filtering and additional info)
            response = await client.post(
                f"{settings.VECTOR_DB_SERVICE_URL}/api/vector/collections/{EMAILS_COLLECTION}/documents",
                json={
                    "documents": [raw_email_content],  # Full raw email content
                    "metadatas": [metadata],  # Metadata with all email fields
                    "ids": [email_id]
                },
                timeout=60.0  # Longer timeout for embedding generation
            )
            
            if response.status_code == 200:
                logger.info(f"Stored email {email_data.gmail_message_id} with ID {email_id} (raw content + embeddings)")
                return _metadata_to_email(email_id, metadata, raw_email_content)
            else:
                logger.error(f"Failed to store email: {response.text}")
                return None
                
    except Exception as e:
        logger.error(f"Error storing email: {e}")
        return None


async def get_email_by_gmail_id(user_id: int, gmail_message_id: str) -> Optional[Email]:
    """Get an email by Gmail message ID"""
    try:
        # Search for the email using the gmail_message_id in query
        async with httpx.AsyncClient() as client:
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
            
    except Exception as e:
        logger.error(f"Error getting email by Gmail ID: {e}")
        return None


async def get_email_by_id(email_id: str) -> Optional[Email]:
    """Get an email by its ID"""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{settings.VECTOR_DB_SERVICE_URL}/api/vector/collections/{EMAILS_COLLECTION}/documents/{email_id}",
                timeout=10.0
            )
            
            if response.status_code == 200:
                data = response.json()
                return _metadata_to_email(data['id'], data['metadata'], data.get('document', ''))
            return None
            
    except Exception as e:
        logger.error(f"Error getting email by ID: {e}")
        return None


async def get_user_emails(user_id: int, limit: int = 100, is_read: Optional[bool] = None) -> List[Email]:
    """Get emails for a user"""
    try:
        async with httpx.AsyncClient() as client:
            # Query with a generic term to get all documents
            response = await client.post(
                f"{settings.VECTOR_DB_SERVICE_URL}/api/vector/collections/{EMAILS_COLLECTION}/query",
                json={
                    "query_texts": ["email message inbox"],
                    "n_results": limit * 3  # Get more to filter
                },
                timeout=30.0
            )
            
            if response.status_code == 200:
                data = response.json()
                results = data.get("results", {})
                ids = results.get("ids", [[]])[0]
                metadatas = results.get("metadatas", [[]])[0]
                documents = results.get("documents", [[]])[0]
                
                emails = []
                for i, meta in enumerate(metadatas):
                    if str(meta.get("user_id")) == str(user_id):
                        if is_read is None or meta.get("is_read") == is_read:
                            emails.append(_metadata_to_email(
                                ids[i], 
                                meta, 
                                documents[i] if documents else ""
                            ))
                            if len(emails) >= limit:
                                break
                
                # Sort by date (newest first)
                emails.sort(key=lambda x: x.date or "", reverse=True)
                return emails
                
            return []
            
    except Exception as e:
        logger.error(f"Error getting user emails: {e}")
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


async def mark_email_as_read(email_id: str) -> bool:
    """Mark an email as read"""
    return await update_email_metadata(email_id, {"is_read": True})


async def mark_email_as_processed(email_id: str) -> bool:
    """Mark an email as processed"""
    return await update_email_metadata(email_id, {"is_processed": True})


async def mark_email_as_rate_sheet(email_id: str, is_rate_sheet: bool = True) -> bool:
    """Mark an email as a rate sheet"""
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
