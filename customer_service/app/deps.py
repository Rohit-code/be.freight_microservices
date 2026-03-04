"""Dependencies: JWT auth for customer service"""
from fastapi import Depends, HTTPException, status, Header
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt as jose_jwt
from jose import JWTError
import httpx

from app.core.config import settings

security = HTTPBearer(auto_error=False)


async def get_organization_id_for_user(user_id: int) -> int | None:
    """Resolve staff user's organization_id from user service (one org per user)."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(
                f"{settings.USER_SERVICE_URL}/api/user/internal/user/{user_id}/organization-id"
            )
            if r.status_code != 200:
                return None
            data = r.json()
            return data.get("organization_id")
    except Exception:
        return None


def verify_internal_api_key(
    x_internal_api_key: str | None = Header(None, alias="X-Internal-Api-Key"),
) -> None:
    """Verify service-to-service internal API key."""
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
    except (jose_jwt.JWTError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
        )


async def get_current_user_id_and_organization_id(
    user_id: int = Depends(get_current_user_id),
) -> tuple[int, int | None]:
    """Return (user_id, organization_id) for staff. organization_id is None if user has no org."""
    org_id = await get_organization_id_for_user(user_id)
    return user_id, org_id


def get_current_customer_id(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> int:
    """Require Bearer token with type=customer (for customer portal /me and portal-only APIs)."""
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
        if payload.get("type") != "customer":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token type",
            )
        customer_id = payload.get("customer_id")
        if customer_id is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token payload",
            )
        return int(customer_id)
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
