"""JWT token for customer portal (same secret as Order Service so orders can be scoped by customer_id)."""
from datetime import datetime, timedelta
from jose import jwt as jose_jwt
from app.core.config import settings


def generate_customer_token(customer_id: int, email: str) -> str:
    """Generate JWT for customer portal. Payload includes type='customer' so Order Service can scope by customer_id."""
    payload = {
        "customer_id": customer_id,
        "type": "customer",
        "email": email,
        "exp": datetime.utcnow() + timedelta(days=7),
        "iat": datetime.utcnow(),
    }
    return jose_jwt.encode(
        payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM
    )
