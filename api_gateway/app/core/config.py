from pydantic_settings import BaseSettings
from typing import Optional
from pathlib import Path
from dotenv import load_dotenv

# Get microservices root directory (2 levels up from this file: api_gateway/app/core/config.py)
MICROSERVICES_ROOT = Path(__file__).parent.parent.parent.parent
ENV_FILE = MICROSERVICES_ROOT / ".env"

# Load .env file from microservices root
if ENV_FILE.exists():
    load_dotenv(ENV_FILE)


class Settings(BaseSettings):
    """Application settings"""
    
    # API Gateway settings
    API_GATEWAY_HOST: str = "0.0.0.0"
    API_GATEWAY_PORT: int = 8000
    
    # Microservice URLs
    AUTHENTICATION_SERVICE_URL: str = "http://localhost:8001"
    CONSTANTS_SERVICE_URL: str = "http://localhost:8002"
    AI_SERVICE_URL: str = "http://localhost:8003"
    VECTOR_DB_SERVICE_URL: str = "http://localhost:8004"
    EMAIL_SERVICE_URL: str = "http://localhost:8005"
    USER_SERVICE_URL: str = "http://localhost:8006"
    
    class Config:
        env_file = str(ENV_FILE) if ENV_FILE.exists() else None
        env_file_encoding = "utf-8"
        case_sensitive = True
        extra = "ignore"  # Ignore extra fields from .env file


settings = Settings()
