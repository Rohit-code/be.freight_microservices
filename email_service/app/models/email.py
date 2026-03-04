"""Email model - stored in Vector DB with metadata"""
from pydantic import BaseModel, ConfigDict
from typing import Optional, Dict, Any
from datetime import datetime


class Email(BaseModel):
    """Email model for storing Gmail messages in Vector DB"""
    
    # Unique identifiers
    id: str  # Vector DB document ID
    user_id: int  # Reference to user in auth service
    gmail_message_id: str
    gmail_thread_id: Optional[str] = None
    
    # Email headers
    subject: Optional[str] = None
    from_email: Optional[str] = None
    to_email: Optional[str] = None
    cc_email: Optional[str] = None
    bcc_email: Optional[str] = None
    
    # Email content
    snippet: Optional[str] = None
    body_html: Optional[str] = None
    body_plain: Optional[str] = None
    
    # Metadata
    date: Optional[str] = None  # ISO format string
    has_attachments: bool = False
    attachment_count: int = 0
    is_sent: bool = False
    is_read: bool = False
    is_processed: bool = False  # For AI processing
    is_rate_sheet: bool = False  # Detected as rate sheet
    
    # Auto-drafted response (from rate sheet service)
    drafted_response: Optional[Dict[str, Any]] = None
    
    # Timestamps
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    
    model_config = ConfigDict(from_attributes=True)


class EmailCreate(BaseModel):
    """Schema for creating/storing an email"""
    user_id: int
    gmail_message_id: str
    gmail_thread_id: Optional[str] = None
    subject: Optional[str] = None
    from_email: Optional[str] = None
    to_email: Optional[str] = None
    cc_email: Optional[str] = None
    bcc_email: Optional[str] = None
    snippet: Optional[str] = None
    body_html: Optional[str] = None
    body_plain: Optional[str] = None
    date: Optional[str] = None
    has_attachments: bool = False
    attachment_count: int = 0
    is_sent: bool = False


class EmailUpdate(BaseModel):
    """Schema for updating an email"""
    is_read: Optional[bool] = None
    is_processed: Optional[bool] = None
    is_rate_sheet: Optional[bool] = None
    body_html: Optional[str] = None
    body_plain: Optional[str] = None
