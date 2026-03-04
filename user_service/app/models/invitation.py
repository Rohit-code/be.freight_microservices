from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Text
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.core.database import Base
import secrets


class Invitation(Base):
    """Invitation model for inviting users to organizations"""
    __tablename__ = "invitations"
    
    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)
    invited_by_user_id = Column(Integer, nullable=False, index=True)  # UserProfile ID who sent invitation
    
    # Invitation details
    email = Column(String(255), nullable=False, index=True)
    token = Column(String(255), unique=True, nullable=False, index=True)  # Unique token for invitation link
    role_id = Column(Integer, ForeignKey("roles.id"), nullable=False)  # Role to assign when accepted
    
    # Status
    is_accepted = Column(Boolean, default=False, nullable=False, index=True)
    accepted_at = Column(DateTime(timezone=True), nullable=True)
    accepted_by_user_id = Column(Integer, nullable=True, index=True)  # UserProfile ID who accepted
    
    # Expiry
    expires_at = Column(DateTime(timezone=True), nullable=False, index=True)
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    
    # Relationships
    organization = relationship("Organization", back_populates="invitations")
    role = relationship("Role")
    
    @staticmethod
    def generate_token() -> str:
        """Generate a secure invitation token"""
        return secrets.token_urlsafe(32)
    
    def __repr__(self):
        return f"<Invitation(id={self.id}, email={self.email}, organization_id={self.organization_id}, is_accepted={self.is_accepted})>"
