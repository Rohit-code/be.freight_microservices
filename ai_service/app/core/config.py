from pydantic_settings import BaseSettings
from pathlib import Path
from dotenv import load_dotenv

# Get microservices root directory (2 levels up from this file: ai_service/app/core/config.py)
MICROSERVICES_ROOT = Path(__file__).parent.parent.parent.parent
ENV_FILE = MICROSERVICES_ROOT / ".env"

# Load .env file from microservices root
if ENV_FILE.exists():
    load_dotenv(ENV_FILE)


class Settings(BaseSettings):
    """Application settings"""
    
    # Service info
    service_name: str = "ai"
    environment: str = "development"
    debug: bool = True
    
    # OpenAI settings
    openai_api_key: str = ""
    
    class Config:
        env_file = str(ENV_FILE) if ENV_FILE.exists() else None
        env_file_encoding = "utf-8"
        case_sensitive = False
        extra = "ignore"


settings = Settings()
