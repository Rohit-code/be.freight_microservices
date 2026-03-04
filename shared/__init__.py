"""
Shared utilities and constants for microservices
"""
from .constants import *
from .exceptions import *
from .validators import *

# Import error utilities (optional, may not be available)
try:
    from .error_context import get_error_context_id, set_error_context_id, log_with_context
    from .error_utils import handle_service_error, safe_async_call, safe_call, ensure_error_context
    ERROR_UTILS_AVAILABLE = True
except ImportError:
    ERROR_UTILS_AVAILABLE = False

__all__ = [
    # Constants
    "TIMEOUT_SHORT",
    "TIMEOUT_MEDIUM",
    "TIMEOUT_LONG",
    "TIMEOUT_VERY_LONG",
    "TIMEOUT_WEBHOOK",
    "DEFAULT_PAGE_SIZE",
    "MAX_PAGE_SIZE",
    "DEFAULT_EMAIL_LIMIT",
    "MAX_EMAIL_LIMIT",
    # Exceptions
    "BaseAPIException",
    "ValidationError",
    "AuthenticationError",
    "AuthorizationError",
    "NotFoundError",
    "ConflictError",
    "ServiceUnavailableError",
    "InternalServerError",
    # Validators
    "PaginationParams",
    "EmailListParams",
    "RateSheetSearchParams",
    "validate_pagination",
    "validate_email_limit",
    "validate_rate_sheet_limit",
    # Error utilities (if available)
    "get_error_context_id",
    "set_error_context_id",
    "log_with_context",
    "handle_service_error",
    "safe_async_call",
    "safe_call",
    "ensure_error_context",
]
