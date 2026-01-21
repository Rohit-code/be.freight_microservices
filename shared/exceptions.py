"""
Centralized exception classes for consistent error handling
"""
from fastapi import HTTPException, status
from typing import Optional, Dict, Any
import uuid


class BaseAPIException(HTTPException):
    """Base exception class for API errors"""
    
    def __init__(
        self,
        status_code: int,
        detail: str,
        error_code: Optional[str] = None,
        error_id: Optional[str] = None,
        headers: Optional[Dict[str, Any]] = None
    ):
        super().__init__(status_code=status_code, detail=detail, headers=headers)
        self.error_code = error_code or f"ERR_{status_code}"
        self.error_id = error_id or str(uuid.uuid4())
        self.detail = detail


class ValidationError(BaseAPIException):
    """Raised when input validation fails"""
    
    def __init__(self, detail: str, error_id: Optional[str] = None):
        super().__init__(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=detail,
            error_code="VALIDATION_ERROR",
            error_id=error_id
        )


class AuthenticationError(BaseAPIException):
    """Raised when authentication fails"""
    
    def __init__(self, detail: str = "Authentication required", error_id: Optional[str] = None):
        super().__init__(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=detail,
            error_code="AUTH_ERROR",
            error_id=error_id
        )


class AuthorizationError(BaseAPIException):
    """Raised when authorization fails"""
    
    def __init__(self, detail: str = "Insufficient permissions", error_id: Optional[str] = None):
        super().__init__(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=detail,
            error_code="AUTHORIZATION_ERROR",
            error_id=error_id
        )


class NotFoundError(BaseAPIException):
    """Raised when a resource is not found"""
    
    def __init__(self, resource: str = "Resource", error_id: Optional[str] = None):
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{resource} not found",
            error_code="NOT_FOUND",
            error_id=error_id
        )


class ConflictError(BaseAPIException):
    """Raised when a resource conflict occurs"""
    
    def __init__(self, detail: str, error_id: Optional[str] = None):
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            detail=detail,
            error_code="CONFLICT",
            error_id=error_id
        )


class ServiceUnavailableError(BaseAPIException):
    """Raised when a service is unavailable"""
    
    def __init__(self, service_name: str, error_id: Optional[str] = None):
        super().__init__(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"{service_name} service unavailable",
            error_code="SERVICE_UNAVAILABLE",
            error_id=error_id
        )


class InternalServerError(BaseAPIException):
    """Raised for internal server errors"""
    
    def __init__(self, detail: str = "Internal server error", error_id: Optional[str] = None):
        super().__init__(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=detail,
            error_code="INTERNAL_ERROR",
            error_id=error_id
        )
