"""
Shared validation utilities
"""
from typing import Optional, List
from pydantic import BaseModel, Field, validator
from .constants import MAX_PAGE_SIZE, MAX_EMAIL_LIMIT, MAX_RATE_SHEET_LIMIT


class PaginationParams(BaseModel):
    """Standard pagination parameters"""
    limit: int = Field(default=20, ge=1, le=MAX_PAGE_SIZE, description="Number of items per page")
    offset: int = Field(default=0, ge=0, description="Number of items to skip")
    
    @validator('limit')
    def validate_limit(cls, v):
        if v > MAX_PAGE_SIZE:
            return MAX_PAGE_SIZE
        return v


class EmailListParams(BaseModel):
    """Parameters for listing emails"""
    limit: int = Field(default=50, ge=1, le=MAX_EMAIL_LIMIT, description="Maximum number of emails to return")
    is_read: Optional[bool] = Field(default=None, description="Filter by read status")
    organization_id: Optional[int] = Field(default=None, description="Filter by organization")


class RateSheetSearchParams(BaseModel):
    """Parameters for rate sheet search"""
    limit: int = Field(default=10, ge=1, le=MAX_RATE_SHEET_LIMIT, description="Maximum number of results")
    organization_id: Optional[int] = Field(default=None, description="Filter by organization")


def validate_pagination(limit: Optional[int] = None, offset: Optional[int] = None) -> tuple[int, int]:
    """Validate and normalize pagination parameters"""
    limit = limit or 20
    offset = offset or 0
    
    if limit < 1:
        limit = 20
    if limit > MAX_PAGE_SIZE:
        limit = MAX_PAGE_SIZE
    if offset < 0:
        offset = 0
    
    return limit, offset


def validate_email_limit(limit: Optional[int] = None) -> int:
    """Validate email list limit"""
    if limit is None:
        return 50
    if limit < 1:
        return 50
    if limit > MAX_EMAIL_LIMIT:
        return MAX_EMAIL_LIMIT
    return limit


def validate_rate_sheet_limit(limit: Optional[int] = None) -> int:
    """Validate rate sheet search limit"""
    if limit is None:
        return 10
    if limit < 1:
        return 10
    if limit > MAX_RATE_SHEET_LIMIT:
        return MAX_RATE_SHEET_LIMIT
    return limit
