from pydantic import BaseModel, EmailStr
from typing import Optional, List
from datetime import datetime
from enum import Enum


# Enums
class OrganizationStatus(str, Enum):
    ACTIVE = "active"
    SUSPENDED = "suspended"


class IndustryType(str, Enum):
    FREIGHT_FORWARDER = "freight_forwarder"
    CHA = "cha"
    EXPORTER = "exporter"


class Department(str, Enum):
    OPS = "ops"
    SALES = "sales"
    ADMIN = "admin"


# Organization Schemas
class OrganizationCreate(BaseModel):
    name: str
    domain: str  # Required - company domain (e.g., acme.com)
    admin_email: EmailStr  # Required - organization admin email
    slug: Optional[str] = None
    description: Optional[str] = None
    website: Optional[str] = None
    industry_type: Optional[IndustryType] = None
    timezone: Optional[str] = "UTC"
    default_currency: Optional[str] = "USD"
    emails_per_day_limit: Optional[int] = None  # None = unlimited
    ai_usage_limit: Optional[int] = None  # None = unlimited


class OrganizationUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    website: Optional[str] = None
    logo_url: Optional[str] = None
    industry_type: Optional[IndustryType] = None
    timezone: Optional[str] = None
    default_currency: Optional[str] = None
    status: Optional[OrganizationStatus] = None
    emails_per_day_limit: Optional[int] = None
    ai_usage_limit: Optional[int] = None
    auto_send_threshold: Optional[int] = None
    manual_review_threshold: Optional[int] = None
    vip_auto_review: Optional[bool] = None
    proactive_delay_notifications: Optional[bool] = None


class EmailSettingsUpdate(BaseModel):
    """Email settings update schema"""
    auto_send_threshold: Optional[int] = None
    manual_review_threshold: Optional[int] = None
    vip_auto_review: Optional[bool] = None
    proactive_delay_notifications: Optional[bool] = None
    email_signature: Optional[str] = None  # User's email signature


class OrganizationOut(BaseModel):
    id: int
    name: str
    slug: str
    description: Optional[str] = None
    domain: str
    admin_email: str
    logo_url: Optional[str] = None
    website: Optional[str] = None
    industry_type: Optional[IndustryType] = None
    timezone: Optional[str] = None
    default_currency: Optional[str] = None
    status: OrganizationStatus
    is_active: bool  # Backward compatibility
    emails_per_day_limit: Optional[int] = None
    ai_usage_limit: Optional[int] = None
    auto_send_threshold: Optional[int] = None
    manual_review_threshold: Optional[int] = None
    vip_auto_review: Optional[bool] = None
    proactive_delay_notifications: Optional[bool] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# User Profile Schemas
class UserProfileCreate(BaseModel):
    auth_user_id: int
    email: EmailStr
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    phone: Optional[str] = None
    department: Optional[Department] = None
    signature: Optional[str] = None


class UserProfileUpdate(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    phone: Optional[str] = None
    avatar_url: Optional[str] = None
    bio: Optional[str] = None
    department: Optional[Department] = None
    signature: Optional[str] = None
    is_enabled: Optional[bool] = None


class UserProfileOut(BaseModel):
    id: int
    auth_user_id: int
    email: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    phone: Optional[str] = None
    avatar_url: Optional[str] = None
    bio: Optional[str] = None
    department: Optional[Department] = None
    signature: Optional[str] = None
    is_enabled: bool
    deleted_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# Role Schemas
class RoleOut(BaseModel):
    id: int
    name: str
    display_name: str
    description: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# Invitation Schemas
class InvitationCreate(BaseModel):
    email: EmailStr
    role_id: int


class InvitationOut(BaseModel):
    id: int
    organization_id: int
    invited_by_user_id: int
    email: str
    token: str
    role_id: int
    is_accepted: bool
    accepted_at: Optional[datetime] = None
    accepted_by_user_id: Optional[int] = None
    expires_at: datetime
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# User Organization Schemas
class UserOrganizationOut(BaseModel):
    id: int
    user_profile_id: int
    organization_id: int
    role_id: int
    is_active: bool
    joined_at: datetime
    created_at: datetime
    updated_at: datetime
    user_profile: Optional[UserProfileOut] = None
    organization: Optional[OrganizationOut] = None
    role: Optional[RoleOut] = None

    class Config:
        from_attributes = True


# Response Schemas
class OrganizationWithUsers(OrganizationOut):
    users: List[UserOrganizationOut] = []


class InvitationResponse(BaseModel):
    invitation: InvitationOut
    invitation_link: str
    message: str
