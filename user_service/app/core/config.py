from pydantic_settings import BaseSettings
from pathlib import Path
from dotenv import load_dotenv

# Get microservices root directory (2 levels up from this file: user_service/app/core/config.py)
MICROSERVICES_ROOT = Path(__file__).parent.parent.parent.parent
ENV_FILE = MICROSERVICES_ROOT / ".env"

# Load .env file from microservices root
if ENV_FILE.exists():
    load_dotenv(ENV_FILE)


class Settings(BaseSettings):
    """Application settings"""
    
    # Service info
    service_name: str = "user"
    environment: str = "development"
    debug: bool = True
    
    # Database settings - HOST, PORT, USER, PASSWORD from env, NAME is service-specific
    DB_HOST: str = "localhost"
    DB_PORT: int = 5432
    DB_USER: str = "postgres"
    DB_PASSWORD: str = "postgres"
    
    @property
    def DB_NAME(self) -> str:
        """Service-specific database name - not from env"""
        return "user_service_db"
    
    @property
    def DATABASE_URL(self) -> str:
        """Construct async PostgreSQL database URL"""
        return f"postgresql+asyncpg://{self.DB_USER}:{self.DB_PASSWORD}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
    
    @property
    def DATABASE_URL_SYNC(self) -> str:
        """Construct sync PostgreSQL database URL (for Alembic)"""
        return f"postgresql://{self.DB_USER}:{self.DB_PASSWORD}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
    
    # Auth service URL (to verify JWT tokens and get user info)
    AUTH_SERVICE_URL: str = "http://localhost:8001"
    
    # Email service URL (for sending invitations)
    EMAIL_SERVICE_URL: str = "http://localhost:8005"
    
    # Frontend URL (for invitation links)
    FRONTEND_URL: str = "http://localhost:3000"
    
    class Config:
        env_file = str(ENV_FILE) if ENV_FILE.exists() else None
        env_file_encoding = "utf-8"
        case_sensitive = False
        extra = "ignore"


settings = Settings()
