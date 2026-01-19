from pydantic_settings import BaseSettings
from pydantic import Field, AliasChoices
from typing import Optional
from pathlib import Path
from dotenv import load_dotenv

# Get microservices root directory (2 levels up from this file: authentication/app/core/config.py)
MICROSERVICES_ROOT = Path(__file__).parent.parent.parent.parent
ENV_FILE = MICROSERVICES_ROOT / ".env"

# Load .env file from microservices root
if ENV_FILE.exists():
    load_dotenv(ENV_FILE)


class Settings(BaseSettings):
    """Application settings"""
    
    # Service info
    service_name: str = "authentication"
    environment: str = "development"
    debug: bool = True
    
    # Database settings
    DB_HOST: str = "localhost"
    DB_PORT: int = 5432
    DB_USER: str = "postgres"
    DB_PASSWORD: str = "postgres"
    DB_NAME: str = "auth_service_db"
    
    @property
    def DATABASE_URL(self) -> str:
        """Construct async PostgreSQL database URL"""
        return f"postgresql+asyncpg://{self.DB_USER}:{self.DB_PASSWORD}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
    
    @property
    def DATABASE_URL_SYNC(self) -> str:
        """Construct sync PostgreSQL database URL (for Alembic)"""
        return f"postgresql://{self.DB_USER}:{self.DB_PASSWORD}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
    
    # JWT settings
    jwt_secret: str = Field(
        default="",
        validation_alias=AliasChoices("JWT_SECRET", "jwt_secret")
    )
    jwt_algorithm: str = "HS256"
    jwt_expiry_minutes: int = Field(
        default=1440,
        validation_alias=AliasChoices("JWT_EXPIRY_MINUTES", "jwt_expiry_minutes")
    )
    
    # Google OAuth settings
    google_client_id: str = Field(
        default="",
        validation_alias=AliasChoices("GOOGLE_CLIENT_ID", "google_client_id")
    )
    google_client_secret: str = Field(
        default="",
        validation_alias=AliasChoices("GOOGLE_CLIENT_SECRET", "google_client_secret")
    )
    google_redirect_uri: str = Field(
        default="http://localhost:8000/api/auth/google/callback",
        validation_alias=AliasChoices("GOOGLE_REDIRECT_URI", "GOOGLE_BACKEND_CALLBACK_URL", "google_redirect_uri"),
    )

    @property
    def effective_google_redirect_uri(self) -> str:
        """Effective Google OAuth redirect URI (mirrors Django backend behavior)."""
        return self.google_redirect_uri
    
    # Gmail Push Notifications (Pub/Sub)
    google_cloud_project: str = Field(
        default="",
        validation_alias=AliasChoices("GOOGLE_CLOUD_PROJECT", "google_cloud_project")
    )
    gmail_pubsub_topic: str = Field(
        default="",
        validation_alias=AliasChoices("GMAIL_PUBSUB_TOPIC", "gmail_pubsub_topic")
    )
    gmail_webhook_url: str = Field(
        default="",
        validation_alias=AliasChoices("GMAIL_WEBHOOK_URL", "gmail_webhook_url")
    )
    
    # User service URL (to get user profile signature)
    USER_SERVICE_URL: str = Field(
        default="http://localhost:8006",
        validation_alias=AliasChoices("USER_SERVICE_URL", "user_service_url")
    )
    
    class Config:
        env_file = str(ENV_FILE) if ENV_FILE.exists() else None
        env_file_encoding = "utf-8"
        case_sensitive = False
        # Allow reading from environment even if not in .env file
        extra = "ignore"


# Ensure environment variables are loaded
import os
if ENV_FILE.exists():
    load_dotenv(ENV_FILE, override=True)

# Create settings instance
settings = Settings()

# Fallback: explicitly set from environment if not loaded via Pydantic
if not settings.google_client_id:
    settings.google_client_id = os.getenv("GOOGLE_CLIENT_ID", "")
if not settings.google_client_secret:
    settings.google_client_secret = os.getenv("GOOGLE_CLIENT_SECRET", "")
if settings.google_redirect_uri == "http://localhost:8000/api/auth/google/callback":
    redirect_from_env = os.getenv("GOOGLE_BACKEND_CALLBACK_URL") or os.getenv("GOOGLE_REDIRECT_URI")
    if redirect_from_env:
        settings.google_redirect_uri = redirect_from_env
if not settings.jwt_secret:
    jwt_secret_from_env = os.getenv("JWT_SECRET")
    if jwt_secret_from_env:
        settings.jwt_secret = jwt_secret_from_env

