from sqlalchemy import Column, Integer, String, Text, DateTime
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.core.database import Base


class Permission(Base):
    """Permission model - structure only, no definitions yet"""
    __tablename__ = "permissions"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), unique=True, nullable=False, index=True)  # e.g., "invite_users", "manage_organization"
    display_name = Column(String(150), nullable=False)
    description = Column(Text, nullable=True)
    
    # Resource and action (for future use)
    resource = Column(String(100), nullable=True)  # e.g., "user", "organization"
    action = Column(String(100), nullable=True)  # e.g., "create", "read", "update", "delete"
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    
    # Relationships
    role_permissions = relationship("RolePermission", back_populates="permission", cascade="all, delete-orphan")
    
    def __repr__(self):
        return f"<Permission(id={self.id}, name={self.name})>"
