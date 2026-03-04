"""
Configuration for Decision Engine
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
    """Decision Engine settings"""
    
    SERVICE_NAME: str = "decision_engine"
    PORT: int = 8014
    
    # Confidence thresholds
    HIGH_CONFIDENCE_THRESHOLD: float = 0.85
    MEDIUM_CONFIDENCE_THRESHOLD: float = 0.65
    LOW_CONFIDENCE_THRESHOLD: float = 0.40
    
    # Auto-send thresholds
    AUTO_SEND_CONFIDENCE: float = 0.90
    REQUIRES_REVIEW_CONFIDENCE: float = 0.70
    
    class Config:
        env_file = str(ENV_FILE) if ENV_FILE.exists() else None
        env_file_encoding = "utf-8"
        case_sensitive = True
        extra = "ignore"


settings = Settings()
