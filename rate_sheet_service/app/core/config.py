from pydantic_settings import BaseSettings
from pydantic import ConfigDict, Field, AliasChoices
from typing import Optional
from pathlib import Path
from dotenv import load_dotenv

# Get microservices root directory (2 levels up from this file)
MICROSERVICES_ROOT = Path(__file__).parent.parent.parent.parent
ENV_FILE = MICROSERVICES_ROOT / ".env"

# Load .env file from microservices root
if ENV_FILE.exists():
    load_dotenv(ENV_FILE)


class Settings(BaseSettings):
    """Application settings"""
    
    # Service Configuration
    SERVICE_NAME: str = "rate_sheet_service"
    PORT: int = 8010
    DEBUG: bool = Field(default=False, validation_alias=AliasChoices("DEBUG", "debug"))
    
    # PostgreSQL Database Configuration (for structured rate sheet data)
    DB_HOST: str = "localhost"
    DB_PORT: int = 5432
    DB_USER: str = "postgres"
    DB_PASSWORD: str = "postgres"
    
    @property
    def DB_NAME(self) -> str:
        """Service-specific database name"""
        return "rate_sheet_service_db"
    
    @property
    def DATABASE_URL(self) -> str:
        """Construct async PostgreSQL database URL"""
        return f"postgresql+asyncpg://{self.DB_USER}:{self.DB_PASSWORD}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
    
    @property
    def DATABASE_URL_SYNC(self) -> str:
        """Construct sync PostgreSQL database URL (for Alembic)"""
        return f"postgresql://{self.DB_USER}:{self.DB_PASSWORD}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
    
    # AI Service Configuration
    AI_SERVICE_URL: str = "http://localhost:8003"
    ANTHROPIC_API_KEY: Optional[str] = None
    OPENAI_API_KEY: Optional[str] = None
    
    # Vector DB Service Configuration
    VECTOR_DB_SERVICE_URL: str = "http://localhost:8004"
    
    # Authentication Service Configuration (for sending emails)
    AUTH_SERVICE_URL: str = "http://localhost:8001"
    
    # File Storage Configuration
    MAX_FILE_SIZE_MB: int = 50
    ALLOWED_EXTENSIONS: list = [".xlsx", ".xls", ".csv"]
    UPLOAD_DIR: str = "./uploads/rate_sheets"
    
    # Embedding Configuration
    EMBEDDING_MODEL: str = "BAAI/bge-small-en-v1.5"
    EMBEDDING_DIMENSION: int = 384
    
    # Rate Sheet Processing
    BATCH_SIZE: int = 100
    MAX_CONCURRENT_UPLOADS: int = 5
    
    model_config = ConfigDict(
        env_file=[".env", "../.env", "../../.env"],  # Check current dir, parent dir, and microservices root
        case_sensitive=True,
        extra="ignore"  # Ignore extra fields from .env file (other services' config)
    )


settings = Settings()
