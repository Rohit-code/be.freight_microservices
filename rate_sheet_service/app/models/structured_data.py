"""
Structured Rate Sheet Data Models
Stores extracted structured data (routes, pricing, surcharges) for precise querying

Architecture:
- RateSheetStructuredData: Main rate sheet metadata and JSONB fields (for backward compat)
- Route: Normalized route/lane data for precise SQL queries
- PricingTier: Normalized pricing tier data
- Surcharge: Normalized surcharge data

The normalized tables enable:
- Precise SQL JOINs across routes and pricing
- Better query performance than JSONB filtering
- Easier maintenance and migrations
"""
from sqlalchemy import Column, String, Integer, DateTime, Index, Boolean, Text, ForeignKey, Numeric
from sqlalchemy.sql import func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from app.core.database import Base


class RateSheetStructuredData(Base):
    """
    Main rate sheet metadata.
    
    Storage architecture:
    - PostgreSQL: Structured data (this model + normalized tables) - exact rates, routes, validity
    - ChromaDB: Semantic content - notes, clauses, policies (via EmbeddingService)
    - ArangoDB: Graph relationships - lanes, carriers, routes (via GraphAwareIngestion)
    
    NOTE: JSONB columns (routes, pricing_tiers, surcharges) kept for backward compatibility.
    New code should use the normalized Route, PricingTier, Surcharge tables instead.
    """
    __tablename__ = "rate_sheet_structured_data"
    
    # Primary key - links to ChromaDB document ID
    rate_sheet_id = Column(String(36), primary_key=True, index=True)
    
    # Multi-tenant isolation
    organization_id = Column(Integer, nullable=False, index=True)
    user_id = Column(Integer, nullable=False)
    
    # Basic info
    file_name = Column(String(500), nullable=False)
    file_path = Column(String(1000), nullable=True)  # Path to stored file
    carrier_name = Column(String(255), nullable=True, index=True)
    rate_sheet_type = Column(String(50), nullable=True)  # ocean_freight, air_freight, etc.
    title = Column(String(500), nullable=True)
    
    # Idempotency - prevents duplicate uploads of same file
    file_hash = Column(String(64), nullable=True, index=True)  # SHA256 hash of file content
    idempotency_key = Column(String(100), nullable=True, index=True)  # org_id:file_hash
    
    # Processing status (for async ingestion)
    status = Column(String(20), nullable=False, default='pending', index=True)
    # Values: 'pending', 'processing', 'processed', 'failed'
    processing_error = Column(Text, nullable=True)  # Error message if status='failed'
    processing_started_at = Column(DateTime(timezone=True), nullable=True)
    processing_completed_at = Column(DateTime(timezone=True), nullable=True)
    
    # Version tracking
    version = Column(Integer, nullable=False, default=1)
    supersedes_rate_sheet_id = Column(String(36), nullable=True, index=True)
    is_active = Column(Boolean, nullable=False, default=True, index=True)
    deactivated_at = Column(DateTime(timezone=True), nullable=True)
    deactivated_by = Column(Integer, nullable=True)
    
    # JSONB columns - DEPRECATED, use normalized tables instead
    # Kept for backward compatibility with existing code
    routes_json = Column('routes', JSONB, nullable=False, default=list)
    pricing_tiers_json = Column('pricing_tiers', JSONB, nullable=True)
    surcharges_json = Column('surcharges', JSONB, nullable=True)
    additional_charges = Column(JSONB, nullable=True)
    
    # Validity period
    valid_from = Column(DateTime(timezone=True), nullable=True, index=True)
    valid_to = Column(DateTime(timezone=True), nullable=True, index=True)
    effective_date = Column(DateTime(timezone=True), nullable=True)
    
    # Relationships (if rate sheets are linked)
    is_related = Column(String(10), nullable=True)  # "true" or "false"
    relationship_type = Column(String(100), nullable=True)
    related_rate_sheet_ids = Column(JSONB, nullable=True)
    
    # Metadata
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    
    # Relationships to normalized tables
    routes = relationship("Route", back_populates="rate_sheet", cascade="all, delete-orphan")
    pricing_tiers = relationship("PricingTier", back_populates="rate_sheet", cascade="all, delete-orphan")
    surcharges = relationship("Surcharge", back_populates="rate_sheet", cascade="all, delete-orphan")
    
    # Indexes for common queries
    __table_args__ = (
        # Composite indexes for common query patterns
        Index('idx_org_validity', 'organization_id', 'valid_from', 'valid_to'),
        Index('idx_carrier_org', 'carrier_name', 'organization_id'),
        Index('idx_org_status', 'organization_id', 'status'),
        Index('idx_org_active', 'organization_id', 'is_active'),
        Index('idx_supersedes', 'supersedes_rate_sheet_id'),
        
        # Idempotency - unique constraint on org_id + file_hash
        Index('idx_idempotency', 'organization_id', 'file_hash', unique=True),
        
        # GIN indexes for JSONB columns (backward compat queries)
        Index('idx_routes_gin', 'routes', postgresql_using='gin'),
        Index('idx_pricing_tiers_gin', 'pricing_tiers', postgresql_using='gin'),
        Index('idx_surcharges_gin', 'surcharges', postgresql_using='gin'),
    )
    
    def __repr__(self):
        return f"<RateSheetStructuredData(rate_sheet_id={self.rate_sheet_id}, organization_id={self.organization_id}, carrier={self.carrier_name}, status={self.status}, v{self.version})>"


class Route(Base):
    """
    Normalized route/lane data.
    
    Enables precise SQL queries like:
    - SELECT * FROM routes WHERE origin_port = 'CNSHA' AND destination_port = 'USLAX'
    - JOIN with pricing_tiers for rate lookups
    """
    __tablename__ = "routes"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    rate_sheet_id = Column(String(36), ForeignKey('rate_sheet_structured_data.rate_sheet_id', ondelete='CASCADE'), nullable=False, index=True)
    organization_id = Column(Integer, nullable=False, index=True)
    
    # Route identification - using full port names for better matching
    origin_port = Column(String(100), nullable=False, index=True)  # Full port name e.g., LAEM CHABANG
    origin_port_name = Column(String(255), nullable=True)
    origin_country = Column(String(100), nullable=True)
    destination_port = Column(String(100), nullable=False, index=True)  # Full port name e.g., NHAVA SHEVA
    destination_port_name = Column(String(255), nullable=True)
    destination_country = Column(String(100), nullable=True)
    
    # Container type
    container_type = Column(String(20), nullable=False, index=True)  # 20GP, 40GP, 40HC, etc.
    
    # Pricing
    base_rate = Column(Numeric(12, 2), nullable=True)  # USD
    currency = Column(String(3), nullable=False, default='USD')
    
    # Transit
    transit_time_days = Column(Integer, nullable=True)
    transit_time_text = Column(String(100), nullable=True)  # e.g., "14-18 days"
    
    # Service details
    service_type = Column(String(50), nullable=True)  # e.g., "FCL", "LCL"
    carrier_name = Column(String(255), nullable=True, index=True)
    vessel_name = Column(String(255), nullable=True)
    
    # Validity (route-level, may differ from rate sheet validity)
    valid_from = Column(DateTime(timezone=True), nullable=True, index=True)
    valid_to = Column(DateTime(timezone=True), nullable=True, index=True)
    
    # Additional data as JSONB (for flexibility)
    extra_data = Column(JSONB, nullable=True)  # Any extra fields from extraction
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    
    # Relationship back to rate sheet
    rate_sheet = relationship("RateSheetStructuredData", back_populates="routes")
    
    __table_args__ = (
        # Common query patterns
        Index('idx_route_origin_dest', 'origin_port', 'destination_port'),
        Index('idx_route_org_origin_dest', 'organization_id', 'origin_port', 'destination_port'),
        Index('idx_route_container', 'organization_id', 'container_type'),
        Index('idx_route_carrier', 'organization_id', 'carrier_name'),
        Index('idx_route_validity', 'valid_from', 'valid_to'),
    )
    
    def __repr__(self):
        return f"<Route(id={self.id}, {self.origin_port}->{self.destination_port}, {self.container_type}, ${self.base_rate})>"


class PricingTier(Base):
    """
    Normalized pricing tier data.
    
    Enables volume-based pricing lookups:
    - Different rates for different quantity ranges
    - Contract vs spot pricing
    """
    __tablename__ = "pricing_tiers"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    rate_sheet_id = Column(String(36), ForeignKey('rate_sheet_structured_data.rate_sheet_id', ondelete='CASCADE'), nullable=False, index=True)
    organization_id = Column(Integer, nullable=False, index=True)
    
    # Tier identification
    tier_name = Column(String(100), nullable=True)  # e.g., "Standard", "Volume", "Contract"
    tier_type = Column(String(50), nullable=True)  # "volume", "contract", "spot"
    
    # Volume range (for volume-based pricing)
    min_quantity = Column(Integer, nullable=True)  # Min TEUs/containers
    max_quantity = Column(Integer, nullable=True)  # Max TEUs/containers (null = unlimited)
    
    # Route reference (optional - some tiers apply to all routes)
    origin_port = Column(String(100), nullable=True, index=True)
    destination_port = Column(String(100), nullable=True, index=True)
    container_type = Column(String(20), nullable=True, index=True)
    
    # Pricing
    rate = Column(Numeric(12, 2), nullable=False)
    currency = Column(String(3), nullable=False, default='USD')
    rate_basis = Column(String(50), nullable=True)  # "per_container", "per_teu", "per_kg"
    
    # Discount/markup
    discount_percentage = Column(Numeric(5, 2), nullable=True)
    markup_amount = Column(Numeric(12, 2), nullable=True)
    
    # Validity
    valid_from = Column(DateTime(timezone=True), nullable=True)
    valid_to = Column(DateTime(timezone=True), nullable=True)
    
    # Additional data
    extra_data = Column(JSONB, nullable=True)
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    
    # Relationship back to rate sheet
    rate_sheet = relationship("RateSheetStructuredData", back_populates="pricing_tiers")
    
    __table_args__ = (
        Index('idx_pricing_org_tier', 'organization_id', 'tier_type'),
        Index('idx_pricing_route', 'origin_port', 'destination_port', 'container_type'),
        Index('idx_pricing_validity', 'valid_from', 'valid_to'),
    )
    
    def __repr__(self):
        return f"<PricingTier(id={self.id}, {self.tier_name}, ${self.rate})>"


class Surcharge(Base):
    """
    Normalized surcharge data.
    
    Types of surcharges:
    - BAF (Bunker Adjustment Factor)
    - CAF (Currency Adjustment Factor)
    - THC (Terminal Handling Charge)
    - Documentation fees
    - Customs fees
    - etc.
    """
    __tablename__ = "surcharges"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    rate_sheet_id = Column(String(36), ForeignKey('rate_sheet_structured_data.rate_sheet_id', ondelete='CASCADE'), nullable=False, index=True)
    organization_id = Column(Integer, nullable=False, index=True)
    
    # Surcharge identification
    surcharge_code = Column(String(20), nullable=True, index=True)  # BAF, CAF, THC, etc.
    surcharge_name = Column(String(255), nullable=False)
    surcharge_type = Column(String(50), nullable=True)  # "fuel", "terminal", "documentation", "customs"
    description = Column(Text, nullable=True)
    
    # Applicability (which routes/containers this surcharge applies to)
    applies_to_all = Column(Boolean, default=True)  # If true, applies to all routes
    origin_port = Column(String(100), nullable=True)
    destination_port = Column(String(100), nullable=True)
    container_type = Column(String(20), nullable=True)
    
    # Pricing
    amount = Column(Numeric(12, 2), nullable=True)  # Fixed amount
    percentage = Column(Numeric(5, 2), nullable=True)  # Percentage of base rate
    currency = Column(String(3), nullable=False, default='USD')
    charge_basis = Column(String(50), nullable=True)  # "per_container", "per_bl", "per_shipment"
    
    # Whether this is included in the quoted rate or charged separately
    is_included = Column(Boolean, default=False)
    
    # Validity
    valid_from = Column(DateTime(timezone=True), nullable=True)
    valid_to = Column(DateTime(timezone=True), nullable=True)
    
    # Additional data
    extra_data = Column(JSONB, nullable=True)
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    
    # Relationship back to rate sheet
    rate_sheet = relationship("RateSheetStructuredData", back_populates="surcharges")
    
    __table_args__ = (
        Index('idx_surcharge_org_code', 'organization_id', 'surcharge_code'),
        Index('idx_surcharge_type', 'organization_id', 'surcharge_type'),
        Index('idx_surcharge_route', 'origin_port', 'destination_port'),
        Index('idx_surcharge_validity', 'valid_from', 'valid_to'),
    )
    
    def __repr__(self):
        return f"<Surcharge(id={self.id}, {self.surcharge_code}: {self.surcharge_name}, ${self.amount})>"
