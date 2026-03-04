"""Dependencies: JWT auth for order service"""
from fastapi import Depends, HTTPException, status, Header
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt as jose_jwt
from jose import JWTError

from app.core.config import settings

security = HTTPBearer(auto_error=False)


def verify_internal_api_key(
    x_internal_api_key: str | None = Header(None, alias="X-Internal-Api-Key"),
) -> None:
    """Verify service-to-service internal API key. Used for create-for-user endpoint."""
    if not settings.INTERNAL_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Internal API key not configured",
        )
    if not x_internal_api_key or x_internal_api_key != settings.INTERNAL_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing internal API key",
        )


def get_current_user_id(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> int:
    if not credentials or credentials.credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = credentials.credentials
    try:
        payload = jose_jwt.decode(
            token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM]
        )
        user_id = payload.get("user_id")
        if user_id is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token payload",
            )
        return int(user_id)
    except jose_jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
        )
    except (jose_jwt.JWTError, ValueError) as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
        )


def get_current_user_id_or_customer_id(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> tuple[int | None, int | None]:
    """Return (user_id, None) for staff token or (None, customer_id) for customer portal token."""
    if not credentials or credentials.credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = credentials.credentials
    try:
        payload = jose_jwt.decode(
            token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM]
        )
        if payload.get("type") == "customer":
            customer_id = payload.get("customer_id")
            if customer_id is not None:
                return None, int(customer_id)
        user_id = payload.get("user_id")
        if user_id is not None:
            return int(user_id), None
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload",
        )
    except jose_jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
        )
    except (jose_jwt.JWTError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
        )


def get_current_user_id_and_staff(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> tuple[int, bool]:
    if not credentials or credentials.credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = credentials.credentials
    try:
        payload = jose_jwt.decode(
            token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM]
        )
        user_id = payload.get("user_id")
        if user_id is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token payload",
            )
        is_staff = bool(payload.get("is_staff", False))
        return int(user_id), is_staff
    except jose_jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
        )
    except (jose_jwt.JWTError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
        )
