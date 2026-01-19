from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, Enum as SQLEnum
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.core.database import Base
import enum


class OrganizationStatus(str, enum.Enum):
    """Organization status enum"""
    ACTIVE = "active"
    SUSPENDED = "suspended"


class IndustryType(str, enum.Enum):
    """Industry type enum"""
    FREIGHT_FORWARDER = "freight_forwarder"
    CHA = "cha"  # Custom House Agent
    EXPORTER = "exporter"


class Organization(Base):
    """Organization/Company model"""
    __tablename__ = "organizations"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False, index=True)
    slug = Column(String(255), unique=True, nullable=False, index=True)  # URL-friendly identifier
    description = Column(Text, nullable=True)
    
    # Organization details
    domain = Column(String(255), nullable=False, index=True)  # Company domain (e.g., acme.com) - REQUIRED
    admin_email = Column(String(255), nullable=False, index=True)  # Organization admin email
    logo_url = Column(String(500), nullable=True)
    website = Column(String(500), nullable=True)
    
    # New fields
    industry_type = Column(SQLEnum(IndustryType), nullable=True, index=True)  # freight_forwarder, CHA, exporter
    timezone = Column(String(100), nullable=True, default="UTC")  # e.g., "Asia/Kolkata"
    default_currency = Column(String(10), nullable=True, default="USD")  # e.g., "INR", "USD"
    
    # Status (replacing is_active with enum)
    status = Column(SQLEnum(OrganizationStatus), default=OrganizationStatus.ACTIVE, nullable=False, index=True)
    is_active = Column(Boolean, default=True, nullable=False)  # Keep for backward compatibility
    
    # Organization-level limits
    emails_per_day_limit = Column(Integer, nullable=True)  # Daily email limit (None = unlimited)
    ai_usage_limit = Column(Integer, nullable=True)  # AI API calls per day (None = unlimited)
    
    # Email settings
    auto_send_threshold = Column(Integer, nullable=True, default=95)  # Confidence threshold for auto-send (80-100)
    manual_review_threshold = Column(Integer, nullable=True, default=70)  # Confidence threshold for manual review (50-95)
    vip_auto_review = Column(Boolean, nullable=True, default=True)  # VIP customer auto-review rule
    proactive_delay_notifications = Column(Boolean, nullable=True, default=True)  # Proactive delay notifications rule
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    
    # Relationships
    user_organizations = relationship("UserOrganization", back_populates="organization", cascade="all, delete-orphan")
    invitations = relationship("Invitation", back_populates="organization", cascade="all, delete-orphan")
    
    def __repr__(self):
        return f"<Organization(id={self.id}, name={self.name}, slug={self.slug}, status={self.status})>"
