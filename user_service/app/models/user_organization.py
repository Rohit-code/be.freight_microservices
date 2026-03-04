from sqlalchemy import Column, Integer, ForeignKey, DateTime, Boolean, UniqueConstraint
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.core.database import Base


class UserOrganization(Base):
    """Many-to-many relationship between UserProfile and Organization with Role"""
    __tablename__ = "user_organizations"
    
    id = Column(Integer, primary_key=True, index=True)
    user_profile_id = Column(Integer, ForeignKey("user_profiles.id"), nullable=False, index=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)
    role_id = Column(Integer, ForeignKey("roles.id"), nullable=False, index=True)
    
    # Status
    is_active = Column(Boolean, default=True, nullable=False)
    
    # Timestamps
    joined_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    
    # Relationships
    user_profile = relationship("UserProfile", back_populates="user_organizations")
    organization = relationship("Organization", back_populates="user_organizations")
    role = relationship("Role", back_populates="user_organizations")
    
    # Unique constraint - one user can only have one role per organization
    __table_args__ = (
        UniqueConstraint('user_profile_id', 'organization_id', name='uq_user_organization'),
    )
    
    def __repr__(self):
        return f"<UserOrganization(user_profile_id={self.user_profile_id}, organization_id={self.organization_id}, role_id={self.role_id})>"
