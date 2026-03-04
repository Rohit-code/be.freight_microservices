from sqlalchemy import Column, Integer, String, Text, DateTime, JSON
from sqlalchemy.sql import func
from app.core.database import Base


class Customer(Base):
    """Customer (shipper/BCO) profile. user_id and organization_id are foreign IDs (no FK across DBs)."""
    __tablename__ = "customers"

    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, nullable=True, index=True)
    user_id = Column(Integer, nullable=False, index=True)
    company_name = Column(String(255), nullable=False)
    contact_email = Column(String(255), nullable=False, index=True)
    default_origin_port = Column(String(128), nullable=True)
    default_destination_port = Column(String(128), nullable=True)
    preferences = Column(JSON, nullable=True)
    password_hash = Column(String(255), nullable=True)  # For customer portal login (nullable for existing/imported customers)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
