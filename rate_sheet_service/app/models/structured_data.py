"""
Structured Rate Sheet Data Model
Stores extracted structured data (routes, pricing, surcharges) for precise querying
"""
from sqlalchemy import Column, String, Integer, DateTime, JSON, Index
from sqlalchemy.sql import func
from app.core.database import Base
import uuid


class RateSheetStructuredData(Base):
    """Structured rate sheet data for precise querying and extraction"""
    __tablename__ = "rate_sheet_structured_data"
    
    # Primary key - links to ChromaDB document ID
    rate_sheet_id = Column(String(36), primary_key=True, index=True)
    
    # Multi-tenant isolation
    organization_id = Column(Integer, nullable=False, index=True)
    user_id = Column(Integer, nullable=False)
    
    # Basic info
    file_name = Column(String(500), nullable=False)
    carrier_name = Column(String(255), nullable=True, index=True)
    rate_sheet_type = Column(String(50), nullable=True)  # ocean_freight, air_freight, etc.
    title = Column(String(500), nullable=True)
    
    # Structured data stored as JSONB for flexible querying
    routes = Column(JSON, nullable=False, default=list)  # Array of route objects
    pricing_tiers = Column(JSON, nullable=True)  # Array of pricing tier objects
    surcharges = Column(JSON, nullable=True)  # Array of surcharge objects
    additional_charges = Column(JSON, nullable=True)  # Array of additional charge objects
    
    # Validity period
    valid_from = Column(DateTime(timezone=True), nullable=True, index=True)
    valid_to = Column(DateTime(timezone=True), nullable=True, index=True)
    effective_date = Column(DateTime(timezone=True), nullable=True)
    
    # Relationships (if rate sheets are linked)
    is_related = Column(String(10), nullable=True)  # "true" or "false"
    relationship_type = Column(String(100), nullable=True)
    related_rate_sheet_ids = Column(JSON, nullable=True)  # Array of related rate sheet IDs
    
    # Metadata
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    
    # Indexes for common queries
    __table_args__ = (
        Index('idx_org_validity', 'organization_id', 'valid_from', 'valid_to'),
        Index('idx_carrier_org', 'carrier_name', 'organization_id'),
    )
    
    def __repr__(self):
        return f"<RateSheetStructuredData(rate_sheet_id={self.rate_sheet_id}, organization_id={self.organization_id}, carrier={self.carrier_name})>"
