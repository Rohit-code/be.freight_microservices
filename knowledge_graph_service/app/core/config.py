"""
Configuration for Knowledge Graph Service
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
    """Knowledge Graph Service settings"""
    
    SERVICE_NAME: str = "knowledge_graph_service"
    PORT: int = 8011
    
    # ArangoDB Configuration
    ARANGO_HOST: str = "http://localhost:8529"
    ARANGO_USER: str = "root"
    ARANGO_PASSWORD: str = "password"
    ARANGO_DATABASE: str = "freight_graph"
    
    # Graph Configuration
    MAX_DEPTH: int = 5  # Max traversal depth for graph queries
    
    class Config:
        env_file = str(ENV_FILE) if ENV_FILE.exists() else None
        env_file_encoding = "utf-8"
        case_sensitive = True
        extra = "ignore"


settings = Settings()
