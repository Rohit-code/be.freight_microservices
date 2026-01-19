from pydantic import BaseModel, EmailStr, Field
from typing import Optional, List
from datetime import datetime


class UserOut(BaseModel):
    id: str
    email: EmailStr
    name: Optional[str] = None
    picture: Optional[str] = None
    is_google_user: bool = False
    has_google_connected: bool = False


class AuthResponse(BaseModel):
    user: UserOut
    token: str


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=3)


class SignupRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    username: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None


class GoogleCredentialRequest(BaseModel):
    credential: str


class LogoutResponse(BaseModel):
    message: str


class AdminUserOut(BaseModel):
    id: str
    email: EmailStr
    username: str
    name: Optional[str] = None
    is_active: bool
    is_staff: bool
    is_superuser: bool
    is_google_user: bool
    has_google_connected: bool
    gmail_connected: bool
    drive_connected: bool
    last_login: Optional[datetime] = None
    created_at: datetime


class AdminDashboardResponse(BaseModel):
    total_users: int
    active_users: int
    google_connected_users: int
    gmail_connected_users: int
    drive_connected_users: int
    admin_users: List[AdminUserOut]
    recent_users: List[AdminUserOut]


class AdminUsersResponse(BaseModel):
    total: int
    users: List[AdminUserOut]


class AdminUserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=3)
    username: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    is_active: bool = True
    is_staff: bool = False
    is_superuser: bool = False


class AdminUserUpdate(BaseModel):
    email: Optional[EmailStr] = None
    password: Optional[str] = Field(default=None, min_length=3)
    username: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    is_active: Optional[bool] = None
    is_staff: Optional[bool] = None
    is_superuser: Optional[bool] = None
