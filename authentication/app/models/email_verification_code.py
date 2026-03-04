"""One-time email verification codes (OTP) for signup and optional flows."""
from sqlalchemy import Column, Integer, String, DateTime, func
from app.core.database import Base


class EmailVerificationCode(Base):
    __tablename__ = "email_verification_codes"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), nullable=False, index=True)
    code = Column(String(10), nullable=False)  # 6-digit OTP
    expires_at = Column(DateTime(timezone=True), nullable=False)
    organization_id = Column(Integer, nullable=True, index=True)  # Optional; for customer portal
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
