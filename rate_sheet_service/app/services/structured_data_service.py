"""
Structured Data Service
Handles storage and querying of structured rate sheet data in PostgreSQL
"""
import logging
from typing import List, Dict, Any, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_
from datetime import datetime
from app.models.structured_data import RateSheetStructuredData
from app.core.database import get_db

logger = logging.getLogger(__name__)


class StructuredDataService:
    """Service for managing structured rate sheet data in PostgreSQL"""
    
    async def store_structured_data(
        self,
        session: AsyncSession,
        rate_sheet_id: str,
        organization_id: int,
        user_id: int,
        file_name: str,
        structured_data: Dict[str, Any]
    ) -> RateSheetStructuredData:
        """
        Store structured rate sheet data in PostgreSQL
        
        Args:
            session: Database session
            rate_sheet_id: UUID linking to ChromaDB document
            organization_id: Organization ID
            user_id: User ID who uploaded
            file_name: Original file name
            structured_data: AI-analyzed structured data (routes, pricing_tiers, etc.)
        
        Returns:
            Created RateSheetStructuredData object
        """
        try:
            # Parse validity dates
            validity = structured_data.get("validity", {})
            valid_from = self._parse_datetime(validity.get("valid_from"))
            valid_to = self._parse_datetime(validity.get("valid_to"))
            effective_date = self._parse_datetime(validity.get("effective_date"))
            
            # Parse relationships
            relationships = structured_data.get("relationships", {})
            is_related = str(relationships.get("is_related", False)).lower()
            relationship_type = relationships.get("relationship_type")
            related_ids = relationships.get("related_rate_sheet_ids", [])
            
            # Create structured data record
            structured_record = RateSheetStructuredData(
                rate_sheet_id=rate_sheet_id,
                organization_id=organization_id,
                user_id=user_id,
                file_name=file_name,
                carrier_name=structured_data.get("carrier_name"),
                rate_sheet_type=structured_data.get("rate_sheet_type"),
                title=structured_data.get("title"),
                routes=structured_data.get("routes", []),
                pricing_tiers=structured_data.get("pricing_tiers", []),
                surcharges=structured_data.get("surcharges", []),
                additional_charges=structured_data.get("additional_charges", []),
                valid_from=valid_from,
                valid_to=valid_to,
                effective_date=effective_date,
                is_related=is_related,
                relationship_type=relationship_type,
                related_rate_sheet_ids=related_ids if related_ids else None
            )
            
            session.add(structured_record)
            await session.commit()
            await session.refresh(structured_record)
            
            logger.info(f"✅ Stored structured data for rate sheet {rate_sheet_id}")
            return structured_record
            
        except Exception as e:
            await session.rollback()
            logger.error(f"❌ Error storing structured data for {rate_sheet_id}: {e}", exc_info=True)
            raise
    
    async def get_structured_data(
        self,
        session: AsyncSession,
        rate_sheet_id: str,
        organization_id: int
    ) -> Optional[RateSheetStructuredData]:
        """Get structured data for a specific rate sheet"""
        try:
            result = await session.execute(
                select(RateSheetStructuredData).where(
                    and_(
                        RateSheetStructuredData.rate_sheet_id == rate_sheet_id,
                        RateSheetStructuredData.organization_id == organization_id
                    )
                )
            )
            return result.scalar_one_or_none()
        except Exception as e:
            logger.error(f"Error getting structured data for {rate_sheet_id}: {e}")
            return None
    
    async def query_routes(
        self,
        session: AsyncSession,
        organization_id: int,
        origin_port: Optional[str] = None,
        destination_port: Optional[str] = None,
        container_type: Optional[str] = None,
        valid_date: Optional[datetime] = None
    ) -> List[Dict[str, Any]]:
        """
        Query routes matching specific criteria
        
        Args:
            session: Database session
            organization_id: Organization ID
            origin_port: Filter by origin port (case-insensitive partial match)
            destination_port: Filter by destination port (case-insensitive partial match)
            container_type: Filter by container type (20', 40', etc.)
            valid_date: Filter by validity date (must be within valid_from and valid_to)
        
        Returns:
            List of matching routes with rate sheet info
        """
        try:
            # Build query
            query = select(RateSheetStructuredData).where(
                RateSheetStructuredData.organization_id == organization_id
            )
            
            # Filter by validity date if provided
            if valid_date:
                query = query.where(
                    or_(
                        RateSheetStructuredData.valid_from.is_(None),
                        RateSheetStructuredData.valid_from <= valid_date
                    ),
                    or_(
                        RateSheetStructuredData.valid_to.is_(None),
                        RateSheetStructuredData.valid_to >= valid_date
                    )
                )
            
            result = await session.execute(query)
            rate_sheets = result.scalars().all()
            
            # Filter routes in Python (JSONB filtering)
            matching_routes = []
            for rs in rate_sheets:
                for route in rs.routes or []:
                    # Filter by origin port
                    if origin_port:
                        origin = route.get("origin_port", "").upper()
                        if origin_port.upper() not in origin:
                            continue
                    
                    # Filter by destination port
                    if destination_port:
                        dest = route.get("destination_port", "").upper()
                        if destination_port.upper() not in dest:
                            continue
                    
                    # Filter by container type in pricing tiers
                    if container_type:
                        pricing_tiers = route.get("pricing_tiers", [])
                        has_container = any(
                            tier.get("container_type", "").upper() == container_type.upper()
                            for tier in pricing_tiers
                        )
                        if not has_container:
                            continue
                    
                    # Add route with rate sheet context
                    matching_routes.append({
                        "rate_sheet_id": rs.rate_sheet_id,
                        "file_name": rs.file_name,
                        "carrier_name": rs.carrier_name,
                        "rate_sheet_type": rs.rate_sheet_type,
                        "valid_from": rs.valid_from.isoformat() if rs.valid_from else None,
                        "valid_to": rs.valid_to.isoformat() if rs.valid_to else None,
                        "route": route
                    })
            
            logger.info(f"Found {len(matching_routes)} matching routes for org {organization_id}")
            return matching_routes
            
        except Exception as e:
            logger.error(f"Error querying routes: {e}", exc_info=True)
            return []
    
    async def extract_precise_rates(
        self,
        session: AsyncSession,
        rate_sheet_ids: List[str],
        organization_id: int,
        origin_port: Optional[str] = None,
        destination_port: Optional[str] = None,
        container_type: Optional[str] = None,
        vgm_weight: Optional[float] = None
    ) -> List[Dict[str, Any]]:
        """
        Extract precise rates from structured data
        
        Args:
            session: Database session
            rate_sheet_ids: List of rate sheet IDs to query
            organization_id: Organization ID
            origin_port: Filter by origin port
            destination_port: Filter by destination port
            container_type: Filter by container type (20', 40', etc.)
            vgm_weight: Filter by VGM weight (MT)
        
        Returns:
            List of extracted rates with full context
        """
        try:
            if not rate_sheet_ids:
                return []
            
            # Query structured data for these rate sheets
            result = await session.execute(
                select(RateSheetStructuredData).where(
                    and_(
                        RateSheetStructuredData.rate_sheet_id.in_(rate_sheet_ids),
                        RateSheetStructuredData.organization_id == organization_id
                    )
                )
            )
            rate_sheets = result.scalars().all()
            
            extracted_rates = []
            for rs in rate_sheets:
                for route in rs.routes or []:
                    # Filter routes
                    if origin_port and origin_port.upper() not in route.get("origin_port", "").upper():
                        continue
                    if destination_port and destination_port.upper() not in route.get("destination_port", "").upper():
                        continue
                    
                    # Extract pricing tiers
                    pricing_tiers = route.get("pricing_tiers", [])
                    for tier in pricing_tiers:
                        # Filter by container type
                        if container_type:
                            tier_container = tier.get("container_type", "").upper()
                            if container_type.upper() not in tier_container:
                                continue
                        
                        # Filter by VGM weight if provided
                        if vgm_weight:
                            vgm_min = tier.get("vgm_min_weight_mt")
                            vgm_max = tier.get("vgm_max_weight_mt")
                            if vgm_min is not None and vgm_weight < vgm_min:
                                continue
                            if vgm_max is not None and vgm_weight > vgm_max:
                                continue
                        
                        # Extract rate information
                        rate_info = {
                            "rate_sheet_id": rs.rate_sheet_id,
                            "file_name": rs.file_name,
                            "carrier_name": rs.carrier_name,
                            "origin_port": route.get("origin_port"),
                            "origin_code": route.get("origin_code"),
                            "destination_port": route.get("destination_port"),
                            "destination_code": route.get("destination_code"),
                            "routing": route.get("routing"),
                            "transit_time_days": route.get("transit_time_days"),
                            "transit_time_text": route.get("transit_time_text"),
                            "free_detention_days": route.get("free_detention_days"),
                            "free_detention_text": route.get("free_detention_text"),
                            "container_type": tier.get("container_type"),
                            "container_size": tier.get("container_size"),
                            "base_rate": tier.get("base_rate"),
                            "currency": tier.get("currency", "USD"),
                            "vgm_min_weight_mt": tier.get("vgm_min_weight_mt"),
                            "vgm_max_weight_mt": tier.get("vgm_max_weight_mt"),
                            "remarks": tier.get("remarks") or route.get("remarks"),
                            "valid_from": rs.valid_from.isoformat() if rs.valid_from else None,
                            "valid_to": rs.valid_to.isoformat() if rs.valid_to else None,
                        }
                        
                        # Add surcharges if available
                        if rs.surcharges:
                            rate_info["surcharges"] = rs.surcharges
                        
                        extracted_rates.append(rate_info)
            
            logger.info(f"Extracted {len(extracted_rates)} precise rates from {len(rate_sheets)} rate sheets")
            return extracted_rates
            
        except Exception as e:
            logger.error(f"Error extracting precise rates: {e}", exc_info=True)
            return []
    
    def _parse_datetime(self, date_str: Optional[str]) -> Optional[datetime]:
        """Parse ISO datetime string to datetime object"""
        if not date_str:
            return None
        try:
            # Try ISO format first
            if 'T' in date_str:
                return datetime.fromisoformat(date_str.replace('Z', '+00:00'))
            # Try date only
            return datetime.strptime(date_str, '%Y-%m-%d')
        except Exception as e:
            logger.warning(f"Could not parse datetime '{date_str}': {e}")
            return None
