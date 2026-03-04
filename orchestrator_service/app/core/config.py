"""
Configuration for Orchestrator Service
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
    """Orchestrator Service settings"""
    
    SERVICE_NAME: str = "orchestrator_service"
    PORT: int = 8013
    
    # Service URLs
    RATE_SHEET_SERVICE_URL: str = "http://localhost:8010"
    KNOWLEDGE_GRAPH_SERVICE_URL: str = "http://localhost:8011"
    VECTOR_DB_SERVICE_URL: str = "http://localhost:8004"
    INTENT_CLASSIFIER_SERVICE_URL: str = "http://localhost:8012"
    
    class Config:
        env_file = str(ENV_FILE) if ENV_FILE.exists() else None
        env_file_encoding = "utf-8"
        case_sensitive = True
        extra = "ignore"


settings = Settings()
