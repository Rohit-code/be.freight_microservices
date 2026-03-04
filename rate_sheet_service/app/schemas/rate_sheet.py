from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime
from enum import Enum


class RateSheetStatus(str, Enum):
    """Rate sheet processing status"""
    UPLOADED = "uploaded"
    PROCESSING = "processing"
    PROCESSED = "processed"
    FAILED = "failed"
    ARCHIVED = "archived"


class RateSheetType(str, Enum):
    """Rate sheet type"""
    OCEAN_FREIGHT = "ocean_freight"
    AIR_FREIGHT = "air_freight"
    LAND_FREIGHT = "land_freight"
    MULTIMODAL = "multimodal"
    UNKNOWN = "unknown"


class RelationshipType(str, Enum):
    """Type of relationship between rate sheets"""
    HAND_IN_HAND = "hand_in_hand"
    INDEPENDENT = "independent"
    VERSION = "version"
    SUPPLEMENT = "supplement"


class RateSheetBase(BaseModel):
    """Base rate sheet schema"""
    file_name: str
    carrier_name: Optional[str] = None
    title: Optional[str] = None


class RateSheetCreate(RateSheetBase):
    """Schema for creating a rate sheet"""
    organization_id: int
    user_id: int


class RateSheetResponse(BaseModel):
    """Rate sheet response schema (from ChromaDB)"""
    id: str  # UUID string from ChromaDB
    organization_id: int
    user_id: int
    file_name: str
    file_path: Optional[str] = None
    file_size_bytes: Optional[int] = None
    file_type: Optional[str] = None
    carrier_name: Optional[str] = None
    title: Optional[str] = None
    rate_sheet_type: Optional[str] = None
    status: Optional[str] = None
    valid_from: Optional[str] = None
    valid_to: Optional[str] = None
    effective_date: Optional[str] = None
    confidence_score: Optional[int] = None
    is_related: Optional[bool] = None
    relationship_type: Optional[str] = None
    has_embeddings: Optional[bool] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    processed_at: Optional[str] = None
    document: Optional[str] = None  # Full raw content from ChromaDB
    metadata: Optional[Dict[str, Any]] = None  # All metadata fields


class RateSheetSearch(BaseModel):
    """Schema for rate sheet search"""
    query: Optional[str] = None
    carrier_name: Optional[str] = None
    origin_code: Optional[str] = None
    destination_code: Optional[str] = None
    container_type: Optional[str] = None
    limit: int = Field(default=50, ge=1, le=100)


class RateSheetListResponse(BaseModel):
    """Response for listing rate sheets"""
    rate_sheets: List[Dict[str, Any]]  # Flexible dict since data comes from ChromaDB
    total: int
    page: int
    page_size: int
