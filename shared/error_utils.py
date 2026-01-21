"""
Error handling utilities for consistent error handling patterns
"""
import logging
import sys
from typing import Optional, TypeVar, Callable, Any
from functools import wraps
from pathlib import Path

# Try to import shared exceptions
SHARED_PATH = Path(__file__).parent
if str(SHARED_PATH) not in sys.path:
    sys.path.insert(0, str(SHARED_PATH))

try:
    from exceptions import (
        BaseAPIException,
        NotFoundError,
        ValidationError,
        AuthenticationError,
        AuthorizationError,
        ServiceUnavailableError,
        InternalServerError
    )
    SHARED_EXCEPTIONS_AVAILABLE = True
except ImportError:
    SHARED_EXCEPTIONS_AVAILABLE = False
    # Fallback to HTTPException if shared exceptions not available
    from fastapi import HTTPException
    BaseAPIException = HTTPException

logger = logging.getLogger(__name__)
T = TypeVar('T')


def handle_service_error(
    operation_name: str,
    service_name: str,
    error: Exception,
    error_id: Optional[str] = None,
    raise_error: bool = True
) -> None:
    """
    Standardized error handling for service-to-service calls
    
    Args:
        operation_name: Name of the operation that failed
        service_name: Name of the service that failed
        error: The exception that occurred
        error_id: Optional error correlation ID
        raise_error: Whether to raise ServiceUnavailableError (default: True)
    
    Raises:
        ServiceUnavailableError: If raise_error is True
    """
    error_msg = f"{service_name} error during {operation_name}: {type(error).__name__}: {str(error)}"
    
    if error_id:
        logger.error(f"[{error_id}] {error_msg}", exc_info=True)
    else:
        logger.error(error_msg, exc_info=True)
    
    if raise_error and SHARED_EXCEPTIONS_AVAILABLE:
        raise ServiceUnavailableError(service_name, error_id=error_id)
    elif raise_error:
        from fastapi import HTTPException, status
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"{service_name} service unavailable"
        )


def safe_async_call(
    func: Callable,
    operation_name: str,
    default_return: Any = None,
    log_error: bool = True,
    reraise: bool = False
):
    """
    Decorator for safe async function calls that handles errors gracefully
    
    Args:
        func: Async function to wrap
        operation_name: Name of operation for logging
        default_return: Value to return on error (if reraise=False)
        log_error: Whether to log errors
        reraise: Whether to re-raise exceptions (default: False)
    
    Usage:
        @safe_async_call(operation_name="email_fetch", default_return=[])
        async def fetch_emails():
            ...
    """
    @wraps(func)
    async def wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        except Exception as e:
            if log_error:
                logger.error(
                    f"Error in {operation_name}: {type(e).__name__}: {str(e)}",
                    exc_info=True
                )
            if reraise:
                raise
            return default_return
    return wrapper


def safe_call(
    func: Callable,
    operation_name: str,
    default_return: Any = None,
    log_error: bool = True,
    reraise: bool = False
):
    """
    Decorator for safe synchronous function calls that handles errors gracefully
    
    Args:
        func: Function to wrap
        operation_name: Name of operation for logging
        default_return: Value to return on error (if reraise=False)
        log_error: Whether to log errors
        reraise: Whether to re-raise exceptions (default: False)
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            if log_error:
                logger.error(
                    f"Error in {operation_name}: {type(e).__name__}: {str(e)}",
                    exc_info=True
                )
            if reraise:
                raise
            return default_return
    return wrapper


def ensure_error_context(func: Callable) -> Callable:
    """
    Decorator to ensure error context ID is available in function
    
    This ensures all errors in a function have proper correlation IDs
    """
    @wraps(func)
    async def async_wrapper(*args, **kwargs):
        try:
            from .error_context import get_error_context_id
            error_id = get_error_context_id()
            # Error ID is now available in context
            return await func(*args, **kwargs)
        except Exception as e:
            # Ensure error ID is logged (fallback if context not available)
            try:
                from .error_context import get_error_context_id
                error_id = get_error_context_id()
                logger.error(f"[{error_id}] Error in {func.__name__}: {e}", exc_info=True)
            except (ImportError, AttributeError):
                # Fallback if error context not available - still log the error
                logger.error(f"Error in {func.__name__}: {e}", exc_info=True)
            raise
    
    @wraps(func)
    def sync_wrapper(*args, **kwargs):
        try:
            from .error_context import get_error_context_id
            error_id = get_error_context_id()
            return func(*args, **kwargs)
        except Exception as e:
            try:
                from .error_context import get_error_context_id
                error_id = get_error_context_id()
                logger.error(f"[{error_id}] Error in {func.__name__}: {e}", exc_info=True)
            except (ImportError, AttributeError):
                # Fallback if error context not available - still log the error
                logger.error(f"Error in {func.__name__}: {e}", exc_info=True)
            raise
    
    import asyncio
    if asyncio.iscoroutinefunction(func):
        return async_wrapper
    return sync_wrapper
