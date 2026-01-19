from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text
from sqlalchemy.sql import func
from app.core.database import Base


class User(Base):
    """User model for authentication service"""
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, index=True, nullable=False)
    username = Column(String(150), unique=True, index=True, nullable=False)
    password_hash = Column(String(255), nullable=True)  # Nullable for Google OAuth users
    first_name = Column(String(150), nullable=True)
    last_name = Column(String(150), nullable=True)
    
    # Google OAuth fields
    google_id = Column(String(255), unique=True, index=True, nullable=True)
    is_google_user = Column(Boolean, default=False, nullable=False)
    picture = Column(String(500), nullable=True)
    
    # Google OAuth tokens
    google_access_token = Column(Text, nullable=True)
    google_refresh_token = Column(Text, nullable=True)
    google_token_expiry = Column(DateTime(timezone=True), nullable=True)
    
    # Google service connection flags
    gmail_connected = Column(Boolean, default=False, nullable=False)
    drive_connected = Column(Boolean, default=False, nullable=False)
    sheets_connected = Column(Boolean, default=False, nullable=False)
    docs_connected = Column(Boolean, default=False, nullable=False)
    
    # Account status
    is_active = Column(Boolean, default=True, nullable=False)
    is_staff = Column(Boolean, default=False, nullable=False)
    is_superuser = Column(Boolean, default=False, nullable=False)
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    last_login = Column(DateTime(timezone=True), nullable=True)
    
    def __repr__(self):
        return f"<User(id={self.id}, email={self.email})>"
