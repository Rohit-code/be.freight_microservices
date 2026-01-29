"""
Configuration for Intent Classifier Service
"""
from pydantic_settings import BaseSettings
from typing import Optional
from pathlib import Path
from dotenv import load_dotenv

# Get microservices root directory
MICROSERVICES_ROOT = Path(__file__).parent.parent.parent.parent
ENV_FILE = MICROSERVICES_ROOT / ".env"

if ENV_FILE.exists():
    load_dotenv(ENV_FILE)


class Settings(BaseSettings):
    """Intent Classifier Service settings"""
    
    SERVICE_NAME: str = "intent_classifier_service"
    PORT: int = 8012
    
    # AI Service Configuration
    AI_SERVICE_URL: str = "http://localhost:8003"
    OPENAI_API_KEY: Optional[str] = None
    
    class Config:
        env_file = str(ENV_FILE) if ENV_FILE.exists() else None
        env_file_encoding = "utf-8"
        case_sensitive = True
        extra = "ignore"


settings = Settings()
