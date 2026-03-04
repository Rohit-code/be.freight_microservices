from pydantic import BaseModel
from datetime import datetime
from typing import Optional, Any


class CustomerLoginRequest(BaseModel):
    email: str
    password: str
    organization_id: int | None = None  # Required for portal login: same email can be customer of multiple orgs


class CustomerPortalOut(BaseModel):
    id: int
    company_name: str
    contact_email: str

    class Config:
        from_attributes = True


class CustomerLoginResponse(BaseModel):
    token: str
    customer: CustomerPortalOut


class CustomerCreate(BaseModel):
    company_name: str
    contact_email: str
    default_origin_port: Optional[str] = None
    default_destination_port: Optional[str] = None
    preferences: Optional[dict[str, Any]] = None
    organization_id: Optional[int] = None


class CustomerUpdate(BaseModel):
    company_name: Optional[str] = None
    contact_email: Optional[str] = None
    default_origin_port: Optional[str] = None
    default_destination_port: Optional[str] = None
    preferences: Optional[dict[str, Any]] = None
    organization_id: Optional[int] = None
    password: Optional[str] = None  # Set for customer portal login (min 8 chars recommended)


class CustomerResponse(BaseModel):
    id: int
    organization_id: Optional[int] = None
    user_id: int
    company_name: str
    contact_email: str
    default_origin_port: Optional[str] = None
    default_destination_port: Optional[str] = None
    preferences: Optional[dict[str, Any]] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class CustomerListResponse(BaseModel):
    id: int
    organization_id: Optional[int] = None
    user_id: int
    company_name: str
    contact_email: str
    default_origin_port: Optional[str] = None
    default_destination_port: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
