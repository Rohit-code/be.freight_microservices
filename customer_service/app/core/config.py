"""Configuration for Customer Service"""
from pydantic_settings import BaseSettings
from pathlib import Path
from dotenv import load_dotenv

MICROSERVICES_ROOT = Path(__file__).parent.parent.parent.parent
ENV_FILE = MICROSERVICES_ROOT / ".env"
if ENV_FILE.exists():
    load_dotenv(ENV_FILE)


class Settings(BaseSettings):
    SERVICE_NAME: str = "customer_service"
    PORT: int = 8016

    DB_HOST: str = "localhost"
    DB_PORT: int = 5432
    DB_USER: str = "postgres"
    DB_PASSWORD: str = "postgres"
    DB_NAME: str = "customer_service_db"

    @property
    def DATABASE_URL(self) -> str:
        return f"postgresql+asyncpg://{self.DB_USER}:{self.DB_PASSWORD}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"

    JWT_SECRET: str = "your-super-secret-jwt-key-change-in-production"
    JWT_ALGORITHM: str = "HS256"

    # Service-to-service auth for internal by-email lookup
    INTERNAL_API_KEY: str = ""

    # User service: resolve staff user's organization_id for org-scoped customer access
    USER_SERVICE_URL: str = "http://localhost:8006"

    class Config:
        env_file = [".env", "../.env", "../../.env"]
        case_sensitive = True
        extra = "ignore"


settings = Settings()
