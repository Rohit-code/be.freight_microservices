"""JWT token utilities"""
from datetime import datetime, timedelta
from jose import jwt as jose_jwt
from ..core.config import settings
import logging

logger = logging.getLogger(__name__)


def generate_jwt_token(user_id: int, email: str) -> str:
    """Generate JWT token for authenticated user"""
    payload = {
        'user_id': user_id,
        'email': email,
        'exp': datetime.utcnow() + timedelta(days=7),
        'iat': datetime.utcnow(),
    }
    token = jose_jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    return token


def verify_jwt_token(token: str) -> dict:
    """Verify and decode JWT token"""
    try:
        payload = jose_jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        return payload
    except jose_jwt.ExpiredSignatureError:
        logger.warning("JWT verification failed: token expired")
        raise ValueError('Token has expired')
    except jose_jwt.JWTError as e:
        logger.warning("JWT verification failed: %s", str(e))
        raise ValueError(f'Invalid token: {str(e)}')
