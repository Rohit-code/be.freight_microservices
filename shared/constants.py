"""
Shared constants across microservices
"""
from typing import Final

# Timeout configurations (in seconds)
TIMEOUT_SHORT: Final[int] = 10
TIMEOUT_MEDIUM: Final[int] = 30
TIMEOUT_LONG: Final[int] = 60
TIMEOUT_VERY_LONG: Final[int] = 120
TIMEOUT_WEBHOOK: Final[int] = 180  # For webhook endpoints that trigger long operations

# Request limits
DEFAULT_PAGE_SIZE: Final[int] = 20
MAX_PAGE_SIZE: Final[int] = 100
DEFAULT_EMAIL_LIMIT: Final[int] = 50
MAX_EMAIL_LIMIT: Final[int] = 200
DEFAULT_RATE_SHEET_LIMIT: Final[int] = 10
MAX_RATE_SHEET_LIMIT: Final[int] = 50

# File upload limits
MAX_FILE_SIZE_MB: Final[int] = 50
MAX_FILE_SIZE_BYTES: Final[int] = MAX_FILE_SIZE_MB * 1024 * 1024

# Pagination defaults
DEFAULT_OFFSET: Final[int] = 0
DEFAULT_LIMIT: Final[int] = DEFAULT_PAGE_SIZE

# HTTP Status Codes (for consistency)
HTTP_OK: Final[int] = 200
HTTP_CREATED: Final[int] = 201
HTTP_BAD_REQUEST: Final[int] = 400
HTTP_UNAUTHORIZED: Final[int] = 401
HTTP_FORBIDDEN: Final[int] = 403
HTTP_NOT_FOUND: Final[int] = 404
HTTP_CONFLICT: Final[int] = 409
HTTP_INTERNAL_ERROR: Final[int] = 500
HTTP_SERVICE_UNAVAILABLE: Final[int] = 503

# Error Messages
ERROR_SERVICE_UNAVAILABLE: Final[str] = "Service temporarily unavailable"
ERROR_INVALID_INPUT: Final[str] = "Invalid input provided"
ERROR_UNAUTHORIZED: Final[str] = "Unauthorized access"
ERROR_NOT_FOUND: Final[str] = "Resource not found"
ERROR_INTERNAL_ERROR: Final[str] = "Internal server error"
