from sqlalchemy import Column, Integer, String, DateTime, Text, ForeignKey, Boolean, Enum as SQLEnum
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.core.database import Base
import enum


class Department(str, enum.Enum):
    """Department enum"""
    OPS = "ops"  # Operations
    SALES = "sales"
    ADMIN = "admin"


class UserProfile(Base):
    """User profile model - links to auth service user"""
    __tablename__ = "user_profiles"
    
    id = Column(Integer, primary_key=True, index=True)
    auth_user_id = Column(Integer, nullable=False, unique=True, index=True)  # Reference to auth service user ID
    email = Column(String(255), nullable=False, index=True)  # Denormalized for quick access
    
    # Profile information
    first_name = Column(String(150), nullable=True)
    last_name = Column(String(150), nullable=True)
    phone = Column(String(50), nullable=True)
    avatar_url = Column(String(500), nullable=True)
    bio = Column(Text, nullable=True)
    
    # New fields
    department = Column(SQLEnum(Department), nullable=True, index=True)  # ops, sales, admin
    signature = Column(Text, nullable=True)  # Email footer signature
    
    # User status
    is_enabled = Column(Boolean, default=True, nullable=False, index=True)  # Enable/disable user
    deleted_at = Column(DateTime(timezone=True), nullable=True, index=True)  # Soft delete (audit-safe)
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    
    # Relationships
    user_organizations = relationship("UserOrganization", back_populates="user_profile", cascade="all, delete-orphan")
    
    @property
    def is_deleted(self) -> bool:
        """Check if user is soft deleted"""
        return self.deleted_at is not None
    
    def __repr__(self):
        return f"<UserProfile(id={self.id}, auth_user_id={self.auth_user_id}, email={self.email}, enabled={self.is_enabled})>"
