"""Email service modules - using Vector DB for storage"""
from .email_service import (
    store_email,
    get_new_emails,
    get_user_emails,
    search_emails_semantic,
    mark_email_as_read,
    mark_email_as_processed,
)
from .email_monitor_service import (
    fetch_and_store_emails,
    start_email_monitoring,
    stop_email_monitoring,
)

__all__ = [
    "store_email",
    "get_new_emails",
    "get_user_emails",
    "search_emails_semantic",
    "mark_email_as_read",
    "mark_email_as_processed",
    "fetch_and_store_emails",
    "start_email_monitoring",
    "stop_email_monitoring",
]
