from pydantic_settings import BaseSettings
from pydantic import ConfigDict
from typing import Optional


class Settings(BaseSettings):
    """Application settings"""
    
    # Service Configuration
    SERVICE_NAME: str = "rate_sheet_service"
    PORT: int = 8010
    DEBUG: bool = False
    
    # No PostgreSQL database - all data stored in ChromaDB via vector_db service
    
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
