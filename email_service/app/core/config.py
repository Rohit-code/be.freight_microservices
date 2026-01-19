from pydantic_settings import BaseSettings
from pathlib import Path
from dotenv import load_dotenv

# Get microservices root directory (2 levels up from this file: email_service/app/core/config.py)
MICROSERVICES_ROOT = Path(__file__).parent.parent.parent.parent
ENV_FILE = MICROSERVICES_ROOT / ".env"

# Load .env file from microservices root
if ENV_FILE.exists():
    load_dotenv(ENV_FILE)


class Settings(BaseSettings):
    """Application settings - Email service uses Vector DB only (no PostgreSQL)"""
    
    # Service info
    service_name: str = "email"
    environment: str = "development"
    debug: bool = True
    
    # Vector DB settings (all email data stored here)
    VECTOR_DB_SERVICE_URL: str = "http://localhost:8004"
    
    # Auth service URL (to get user info and Gmail tokens)
    AUTH_SERVICE_URL: str = "http://localhost:8001"
    
    # Frontend URL
    FRONTEND_URL: str = "http://localhost:3000"
    
    class Config:
        env_file = str(ENV_FILE) if ENV_FILE.exists() else None
        env_file_encoding = "utf-8"
        case_sensitive = False
        extra = "ignore"


settings = Settings()
