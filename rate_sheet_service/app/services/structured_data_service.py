"""
Structured Data Service
Handles storage and querying of structured rate sheet data in PostgreSQL

Architecture:
- RateSheetStructuredData: Main rate sheet metadata + JSONB columns (backward compat)
- Route: Normalized route/lane table for precise SQL queries
- PricingTier: Normalized pricing tier table
- Surcharge: Normalized surcharge table

The service writes to BOTH JSONB columns (for backward compatibility) 
AND normalized tables (for optimized queries).
"""
import logging
from typing import List, Dict, Any, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_
from sqlalchemy.orm import selectinload
from datetime import datetime
from decimal import Decimal
from app.models.structured_data import RateSheetStructuredData, Route, PricingTier, Surcharge
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
        structured_data: Dict[str, Any],
        file_hash: str = None,
        idempotency_key: str = None
    ) -> RateSheetStructuredData:
        """
        Store structured rate sheet data in PostgreSQL
        
        Writes to BOTH:
        - JSONB columns (routes_json, pricing_tiers_json, surcharges_json) for backward compatibility
        - Normalized tables (routes, pricing_tiers, surcharges) for optimized queries
        
        Args:
            session: Database session
            rate_sheet_id: UUID linking to ChromaDB document
            organization_id: Organization ID
            user_id: User ID who uploaded
            file_name: Original file name
            structured_data: AI-analyzed structured data (routes, pricing_tiers, etc.)
            file_hash: SHA256 hash of file content for idempotency
            idempotency_key: org_id:file_hash for duplicate detection
        
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
            
            carrier_name = structured_data.get("carrier_name")
            
            # Merge data_understanding (Cursor-style: what kind of data this sheet has) into additional_charges for storage
            additional_charges = structured_data.get("additional_charges")
            if isinstance(additional_charges, list):
                additional_charges = {}
            additional_charges = dict(additional_charges or {})
            additional_charges["data_understanding"] = structured_data.get("data_understanding", {})
            
            # Create structured data record (with JSONB columns for backward compat)
            structured_record = RateSheetStructuredData(
                rate_sheet_id=rate_sheet_id,
                organization_id=organization_id,
                user_id=user_id,
                file_name=file_name,
                file_hash=file_hash,
                idempotency_key=idempotency_key,
                carrier_name=carrier_name,
                rate_sheet_type=structured_data.get("rate_sheet_type"),
                title=structured_data.get("title"),
                routes_json=structured_data.get("routes", []),  # JSONB column
                pricing_tiers_json=structured_data.get("pricing_tiers", []),  # JSONB column
                surcharges_json=structured_data.get("surcharges", []),  # JSONB column
                additional_charges=additional_charges,
                valid_from=valid_from,
                valid_to=valid_to,
                effective_date=effective_date,
                is_related=is_related,
                relationship_type=relationship_type,
                related_rate_sheet_ids=related_ids if related_ids else None
            )
            
            session.add(structured_record)
            
            # Create normalized Route records
            routes_data = structured_data.get("routes", [])
            route_records = self._create_route_records(
                rate_sheet_id=rate_sheet_id,
                organization_id=organization_id,
                carrier_name=carrier_name,
                routes_data=routes_data,
                valid_from=valid_from,
                valid_to=valid_to
            )
            for route_record in route_records:
                session.add(route_record)
            
            # Create normalized PricingTier records
            pricing_data = structured_data.get("pricing_tiers", [])
            pricing_records = self._create_pricing_tier_records(
                rate_sheet_id=rate_sheet_id,
                organization_id=organization_id,
                pricing_data=pricing_data,
                valid_from=valid_from,
                valid_to=valid_to
            )
            for pricing_record in pricing_records:
                session.add(pricing_record)
            
            # Create normalized Surcharge records
            surcharges_data = structured_data.get("surcharges", [])
            surcharge_records = self._create_surcharge_records(
                rate_sheet_id=rate_sheet_id,
                organization_id=organization_id,
                surcharges_data=surcharges_data,
                valid_from=valid_from,
                valid_to=valid_to
            )
            for surcharge_record in surcharge_records:
                session.add(surcharge_record)
            
            await session.commit()
            await session.refresh(structured_record)
            
            logger.info(f"✅ Stored structured data for rate sheet {rate_sheet_id} "
                       f"({len(route_records)} routes, {len(pricing_records)} pricing tiers, {len(surcharge_records)} surcharges)")
            return structured_record
            
        except Exception as e:
            await session.rollback()
            logger.error(f"❌ Error storing structured data for {rate_sheet_id}: {e}", exc_info=True)
            raise
    
    def _create_route_records(
        self,
        rate_sheet_id: str,
        organization_id: int,
        carrier_name: Optional[str],
        routes_data: List[Dict[str, Any]],
        valid_from: Optional[datetime],
        valid_to: Optional[datetime]
    ) -> List[Route]:
        """Create normalized Route records from JSONB route data"""
        records = []
        for route_data in routes_data:
            # Extract pricing tiers from route (nested structure)
            pricing_tiers = route_data.get("pricing_tiers", [])
            
            # Get full port names - prefer full names over codes for better matching
            origin_port_full = route_data.get("origin_port", "").upper().strip()
            origin_code = route_data.get("origin_code", "").upper().strip() if route_data.get("origin_code") else None
            dest_port_full = route_data.get("destination_port", "").upper().strip()
            dest_code = route_data.get("destination_code", "").upper().strip() if route_data.get("destination_code") else None
            
            # Create one Route record per container type in pricing tiers
            if pricing_tiers:
                for tier in pricing_tiers:
                    # Skip tiers without base rate
                    base_rate = self._safe_decimal(tier.get("base_rate"))
                    if base_rate is None or base_rate == 0:
                        continue
                    
                    record = Route(
                        rate_sheet_id=rate_sheet_id,
                        organization_id=organization_id,
                        # Store FULL port name in origin_port for better ILIKE matching
                        origin_port=origin_port_full,
                        origin_port_name=origin_port_full,
                        destination_port=dest_port_full,
                        destination_port_name=dest_port_full,
                        container_type=tier.get("container_type", "UNKNOWN"),
                        base_rate=base_rate,
                        currency=tier.get("currency", "USD"),
                        transit_time_days=self._safe_int(route_data.get("transit_time_days")),
                        transit_time_text=route_data.get("transit_time_text"),
                        carrier_name=carrier_name,
                        valid_from=valid_from,
                        valid_to=valid_to,
                        extra_data={
                            "routing": route_data.get("routing"),
                            "free_detention_days": route_data.get("free_detention_days"),
                            "free_detention_text": route_data.get("free_detention_text"),
                            "remarks": route_data.get("remarks") or tier.get("remarks"),
                            "vgm_min_weight_mt": tier.get("vgm_min_weight_mt"),
                            "vgm_max_weight_mt": tier.get("vgm_max_weight_mt"),
                            "origin_code": origin_code,
                            "destination_code": dest_code,
                        }
                    )
                    records.append(record)
            else:
                # No pricing tiers - create route without rate (for reference)
                record = Route(
                    rate_sheet_id=rate_sheet_id,
                    organization_id=organization_id,
                    origin_port=origin_port_full,
                    origin_port_name=origin_port_full,
                    destination_port=dest_port_full,
                    destination_port_name=dest_port_full,
                    container_type="UNKNOWN",
                    transit_time_days=self._safe_int(route_data.get("transit_time_days")),
                    transit_time_text=route_data.get("transit_time_text"),
                    carrier_name=carrier_name,
                    valid_from=valid_from,
                    valid_to=valid_to,
                    extra_data={
                        "routing": route_data.get("routing"),
                        "remarks": route_data.get("remarks"),
                        "origin_code": origin_code,
                        "destination_code": dest_code,
                    }
                )
                records.append(record)
        
        return records
    
    def _create_pricing_tier_records(
        self,
        rate_sheet_id: str,
        organization_id: int,
        pricing_data: List[Dict[str, Any]],
        valid_from: Optional[datetime],
        valid_to: Optional[datetime]
    ) -> List[PricingTier]:
        """Create normalized PricingTier records from standalone pricing tier data"""
        records = []
        for tier_data in pricing_data:
            record = PricingTier(
                rate_sheet_id=rate_sheet_id,
                organization_id=organization_id,
                tier_name=tier_data.get("tier_name") or tier_data.get("name"),
                tier_type=tier_data.get("tier_type") or tier_data.get("type"),
                min_quantity=self._safe_int(tier_data.get("min_quantity")),
                max_quantity=self._safe_int(tier_data.get("max_quantity")),
                origin_port=tier_data.get("origin_port"),
                destination_port=tier_data.get("destination_port"),
                container_type=tier_data.get("container_type"),
                rate=self._safe_decimal(tier_data.get("rate") or tier_data.get("base_rate")) or Decimal("0"),
                currency=tier_data.get("currency", "USD"),
                rate_basis=tier_data.get("rate_basis"),
                discount_percentage=self._safe_decimal(tier_data.get("discount_percentage")),
                markup_amount=self._safe_decimal(tier_data.get("markup_amount")),
                valid_from=valid_from,
                valid_to=valid_to,
                extra_data=tier_data.get("metadata") or tier_data.get("extra_data")
            )
            records.append(record)
        return records
    
    def _create_surcharge_records(
        self,
        rate_sheet_id: str,
        organization_id: int,
        surcharges_data: List[Dict[str, Any]],
        valid_from: Optional[datetime],
        valid_to: Optional[datetime]
    ) -> List[Surcharge]:
        """Create normalized Surcharge records from surcharge data"""
        records = []
        for surcharge_data in surcharges_data:
            record = Surcharge(
                rate_sheet_id=rate_sheet_id,
                organization_id=organization_id,
                surcharge_code=surcharge_data.get("code") or surcharge_data.get("surcharge_code"),
                surcharge_name=surcharge_data.get("name") or surcharge_data.get("surcharge_name") or "Unknown Surcharge",
                surcharge_type=surcharge_data.get("type") or surcharge_data.get("surcharge_type"),
                description=surcharge_data.get("description"),
                applies_to_all=surcharge_data.get("applies_to_all", True),
                origin_port=surcharge_data.get("origin_port"),
                destination_port=surcharge_data.get("destination_port"),
                container_type=surcharge_data.get("container_type"),
                amount=self._safe_decimal(surcharge_data.get("amount")),
                percentage=self._safe_decimal(surcharge_data.get("percentage")),
                currency=surcharge_data.get("currency", "USD"),
                charge_basis=surcharge_data.get("charge_basis") or surcharge_data.get("basis"),
                is_included=surcharge_data.get("is_included", False),
                valid_from=valid_from,
                valid_to=valid_to,
                extra_data=surcharge_data.get("metadata") or surcharge_data.get("extra_data")
            )
            records.append(record)
        return records
    
    def _safe_decimal(self, value) -> Optional[Decimal]:
        """Safely convert value to Decimal"""
        if value is None:
            return None
        try:
            return Decimal(str(value))
        except:
            return None
    
    def _safe_int(self, value) -> Optional[int]:
        """Safely convert value to int"""
        if value is None:
            return None
        try:
            return int(value)
        except:
            return None
    
    async def update_structured_data(
        self,
        session: AsyncSession,
        rate_sheet_id: str,
        structured_data: Dict[str, Any]
    ) -> RateSheetStructuredData:
        """
        Update an existing rate sheet record with processed data.
        Used by async processing to update pending records.
        
        Updates BOTH JSONB columns AND normalized tables.
        """
        try:
            # Get existing record
            result = await session.execute(
                select(RateSheetStructuredData).where(
                    RateSheetStructuredData.rate_sheet_id == rate_sheet_id
                )
            )
            record = result.scalar_one_or_none()
            
            if not record:
                raise ValueError(f"Rate sheet {rate_sheet_id} not found")
            
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
            
            # Check for version conflicts and handle supersession
            carrier_name = structured_data.get("carrier_name")
            if carrier_name and valid_from and valid_to:
                await self._handle_version_supersession(
                    session=session,
                    organization_id=record.organization_id,
                    carrier_name=carrier_name,
                    valid_from=valid_from,
                    valid_to=valid_to,
                    current_rate_sheet_id=rate_sheet_id,
                    record=record
                )
            
            # Update record fields (JSONB columns)
            record.carrier_name = carrier_name
            record.rate_sheet_type = structured_data.get("rate_sheet_type")
            record.title = structured_data.get("title")
            record.routes_json = structured_data.get("routes", [])  # JSONB
            record.pricing_tiers_json = structured_data.get("pricing_tiers", [])  # JSONB
            record.surcharges_json = structured_data.get("surcharges", [])  # JSONB
            record.additional_charges = structured_data.get("additional_charges", [])
            record.valid_from = valid_from
            record.valid_to = valid_to
            record.effective_date = effective_date
            record.is_related = is_related
            record.relationship_type = relationship_type
            record.related_rate_sheet_ids = related_ids if related_ids else None
            record.status = 'processed'
            record.processing_completed_at = datetime.utcnow()
            
            # Delete existing normalized records and recreate
            await session.execute(
                Route.__table__.delete().where(Route.rate_sheet_id == rate_sheet_id)
            )
            await session.execute(
                PricingTier.__table__.delete().where(PricingTier.rate_sheet_id == rate_sheet_id)
            )
            await session.execute(
                Surcharge.__table__.delete().where(Surcharge.rate_sheet_id == rate_sheet_id)
            )
            
            # Create normalized Route records
            route_records = self._create_route_records(
                rate_sheet_id=rate_sheet_id,
                organization_id=record.organization_id,
                carrier_name=carrier_name,
                routes_data=structured_data.get("routes", []),
                valid_from=valid_from,
                valid_to=valid_to
            )
            for route_record in route_records:
                session.add(route_record)
            
            # Create normalized PricingTier records
            pricing_records = self._create_pricing_tier_records(
                rate_sheet_id=rate_sheet_id,
                organization_id=record.organization_id,
                pricing_data=structured_data.get("pricing_tiers", []),
                valid_from=valid_from,
                valid_to=valid_to
            )
            for pricing_record in pricing_records:
                session.add(pricing_record)
            
            # Create normalized Surcharge records
            surcharge_records = self._create_surcharge_records(
                rate_sheet_id=rate_sheet_id,
                organization_id=record.organization_id,
                surcharges_data=structured_data.get("surcharges", []),
                valid_from=valid_from,
                valid_to=valid_to
            )
            for surcharge_record in surcharge_records:
                session.add(surcharge_record)
            
            await session.commit()
            await session.refresh(record)
            
            logger.info(f"✅ Updated structured data for rate sheet {rate_sheet_id} "
                       f"({len(route_records)} routes, {len(pricing_records)} pricing tiers, {len(surcharge_records)} surcharges)")
            return record
            
        except Exception as e:
            await session.rollback()
            logger.error(f"❌ Error updating structured data for {rate_sheet_id}: {e}", exc_info=True)
            raise
    
    async def _handle_version_supersession(
        self,
        session: AsyncSession,
        organization_id: int,
        carrier_name: str,
        valid_from: datetime,
        valid_to: datetime,
        current_rate_sheet_id: str,
        record: RateSheetStructuredData
    ):
        """
        Handle version supersession when a new rate sheet overlaps with existing ones.
        - Find existing active rate sheets with same carrier and overlapping validity
        - Set is_active=False on old ones
        - Set supersedes_rate_sheet_id on new one
        - Increment version number
        """
        try:
            # Find existing active rate sheets with overlapping validity
            result = await session.execute(
                select(RateSheetStructuredData).where(
                    and_(
                        RateSheetStructuredData.organization_id == organization_id,
                        RateSheetStructuredData.carrier_name == carrier_name,
                        RateSheetStructuredData.is_active == True,
                        RateSheetStructuredData.rate_sheet_id != current_rate_sheet_id,
                        # Overlapping validity check
                        or_(
                            # New sheet starts during old sheet's validity
                            and_(
                                RateSheetStructuredData.valid_from <= valid_from,
                                RateSheetStructuredData.valid_to >= valid_from
                            ),
                            # New sheet ends during old sheet's validity
                            and_(
                                RateSheetStructuredData.valid_from <= valid_to,
                                RateSheetStructuredData.valid_to >= valid_to
                            ),
                            # New sheet completely contains old sheet
                            and_(
                                RateSheetStructuredData.valid_from >= valid_from,
                                RateSheetStructuredData.valid_to <= valid_to
                            )
                        )
                    )
                ).order_by(RateSheetStructuredData.version.desc())
            )
            overlapping_sheets = result.scalars().all()
            
            if overlapping_sheets:
                # Get the highest version and supersede
                highest_version = max(s.version for s in overlapping_sheets)
                record.version = highest_version + 1
                record.supersedes_rate_sheet_id = overlapping_sheets[0].rate_sheet_id
                
                # Deactivate overlapping sheets
                for sheet in overlapping_sheets:
                    sheet.is_active = False
                    sheet.deactivated_at = datetime.utcnow()
                    sheet.deactivated_by = record.user_id
                    logger.info(f"🔄 Deactivated rate sheet {sheet.rate_sheet_id} (superseded by {current_rate_sheet_id})")
                
                logger.info(f"📋 New rate sheet {current_rate_sheet_id} is version {record.version}, supersedes {record.supersedes_rate_sheet_id}")
            
        except Exception as e:
            logger.warning(f"⚠️  Error handling version supersession: {e}")
            # Don't fail the upload - versioning is enhancement
    
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
    
    async def delete_structured_data(
        self,
        session: AsyncSession,
        rate_sheet_id: str,
        organization_id: int
    ) -> bool:
        """Delete rate sheet and all related data from PostgreSQL (routes, pricing_tiers, surcharges, rate_sheet_structured_data)."""
        try:
            # Verify record exists and belongs to org
            record = await self.get_structured_data(session, rate_sheet_id, organization_id)
            if not record:
                return False
            # Delete normalized child tables first (FK to rate_sheet_structured_data)
            await session.execute(Route.__table__.delete().where(Route.rate_sheet_id == rate_sheet_id))
            await session.execute(PricingTier.__table__.delete().where(PricingTier.rate_sheet_id == rate_sheet_id))
            await session.execute(Surcharge.__table__.delete().where(Surcharge.rate_sheet_id == rate_sheet_id))
            await session.delete(record)
            await session.commit()
            logger.info(f"✅ Deleted structured data for rate sheet {rate_sheet_id} (org {organization_id})")
            return True
        except Exception as e:
            await session.rollback()
            logger.error(f"Error deleting structured data for {rate_sheet_id}: {e}", exc_info=True)
            return False
    
    def _normalize_port_name(self, port_name: str) -> str:
        """Normalize port name by removing country names, parentheses, and extra text"""
        if not port_name:
            return ""
        
        # Port alias mapping (common variations)
        port_aliases = {
            "MUMBAI": "NHAVA SHEVA",
            "BOMBAY": "NHAVA SHEVA",
            "INNSA": "NHAVA SHEVA",
            "BANGKOK": "LAEM CHABANG",
            "THLCH": "LAEM CHABANG",
            "SGP": "SINGAPORE",
            "SIN": "SINGAPORE",
        }
        
        # Remove common country names
        port_name = port_name.upper()
        countries = ["INDIA", "THAILAND", "SINGAPORE", "MALAYSIA", "CHINA", "USA", "UNITED STATES"]
        for country in countries:
            port_name = port_name.replace(f", {country}", "").replace(f" {country}", "")
        
        # Remove parentheses and content inside them
        import re
        port_name = re.sub(r'\([^)]*\)', '', port_name)
        
        # Remove extra commas and whitespace
        port_name = port_name.strip().strip(',').strip()
        
        # Check for aliases
        for alias, canonical in port_aliases.items():
            if alias in port_name or port_name == alias:
                return canonical
        
        return port_name
    
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
        Query routes matching specific criteria using NORMALIZED Route table.
        
        This is much faster than JSONB filtering because it uses proper SQL indexes.
        
        Args:
            session: Database session
            organization_id: Organization ID
            origin_port: Filter by origin port (case-insensitive partial match)
            destination_port: Filter by destination port (case-insensitive partial match)
            container_type: Filter by container type (20GP, 40GP, 40HC, etc.)
            valid_date: Filter by validity date (must be within valid_from and valid_to)
        
        Returns:
            List of matching routes with rate sheet info
        """
        try:
            # Normalize port names to remove country names and extra text
            normalized_origin = self._normalize_port_name(origin_port) if origin_port else None
            normalized_dest = self._normalize_port_name(destination_port) if destination_port else None
            
            logger.info(f"[DEBUG] query_routes called: org={organization_id}, origin='{origin_port}' (normalized: '{normalized_origin}'), dest='{destination_port}' (normalized: '{normalized_dest}'), container='{container_type}'")
            
            # Build query using normalized Route table with JOIN to rate sheet
            query = (
                select(Route, RateSheetStructuredData)
                .join(RateSheetStructuredData, Route.rate_sheet_id == RateSheetStructuredData.rate_sheet_id)
                .where(
                    and_(
                        Route.organization_id == organization_id,
                        RateSheetStructuredData.is_active == True  # Only active rate sheets
                    )
                )
            )
            
            # Filter by origin port (case-insensitive, uses index)
            # Try both normalized and original port name
            if normalized_origin:
                query = query.where(
                    or_(
                        Route.origin_port.ilike(f"%{normalized_origin}%"),
                        Route.origin_port_name.ilike(f"%{normalized_origin}%"),
                        Route.origin_port.ilike(f"%{origin_port}%") if origin_port else False,
                        Route.origin_port_name.ilike(f"%{origin_port}%") if origin_port else False
                    )
                )
            
            # Filter by destination port (case-insensitive, uses index)
            # Try both normalized and original port name
            if normalized_dest:
                query = query.where(
                    or_(
                        Route.destination_port.ilike(f"%{normalized_dest}%"),
                        Route.destination_port_name.ilike(f"%{normalized_dest}%"),
                        Route.destination_port.ilike(f"%{destination_port}%") if destination_port else False,
                        Route.destination_port_name.ilike(f"%{destination_port}%") if destination_port else False
                    )
                )
            
            # Filter by container type (exact match, uses index)
            if container_type:
                query = query.where(
                    Route.container_type.ilike(f"%{container_type}%")
                )
            
            # Filter by validity date if provided
            if valid_date:
                query = query.where(
                    or_(
                        Route.valid_from.is_(None),
                        Route.valid_from <= valid_date
                    ),
                    or_(
                        Route.valid_to.is_(None),
                        Route.valid_to >= valid_date
                    )
                )
            
            result = await session.execute(query)
            rows = result.all()
            
            logger.info(f"[DEBUG] SQL query returned {len(rows)} rows")
            
            # Build response
            matching_routes = []
            for route, rate_sheet in rows:
                matching_routes.append({
                    "rate_sheet_id": rate_sheet.rate_sheet_id,
                    "file_name": rate_sheet.file_name,
                    "carrier_name": rate_sheet.carrier_name,
                    "rate_sheet_type": rate_sheet.rate_sheet_type,
                    "valid_from": rate_sheet.valid_from.isoformat() if rate_sheet.valid_from else None,
                    "valid_to": rate_sheet.valid_to.isoformat() if rate_sheet.valid_to else None,
                    "route": {
                        "origin_port": route.origin_port_name or route.origin_port,
                        "origin_code": route.origin_port,
                        "destination_port": route.destination_port_name or route.destination_port,
                        "destination_code": route.destination_port,
                        "container_type": route.container_type,
                        "base_rate": float(route.base_rate) if route.base_rate else None,
                        "currency": route.currency,
                        "transit_time_days": route.transit_time_days,
                        "transit_time_text": route.transit_time_text,
                        "carrier_name": route.carrier_name,
                        "extra_data": route.extra_data
                    }
                })
            
            logger.info(f"Found {len(matching_routes)} matching routes for org {organization_id} (using normalized table)")
            return matching_routes
            
        except Exception as e:
            logger.error(f"[ERROR] Error querying routes from normalized table: {e}", exc_info=True)
            logger.info(f"[DEBUG] Falling back to JSONB query")
            # Fallback to JSONB query if normalized table doesn't exist yet
            return await self._query_routes_jsonb(session, organization_id, origin_port, destination_port, container_type, valid_date)
    
    async def _query_routes_jsonb(
        self,
        session: AsyncSession,
        organization_id: int,
        origin_port: Optional[str] = None,
        destination_port: Optional[str] = None,
        container_type: Optional[str] = None,
        valid_date: Optional[datetime] = None
    ) -> List[Dict[str, Any]]:
        """
        FALLBACK: Query routes using JSONB columns (backward compatibility).
        Used when normalized tables don't exist yet.
        """
        try:
            # Build query - only active rate sheets
            query = select(RateSheetStructuredData).where(
                and_(
                    RateSheetStructuredData.organization_id == organization_id,
                    RateSheetStructuredData.is_active == True
                )
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
                for route in rs.routes_json or []:
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
            
            logger.info(f"Found {len(matching_routes)} matching routes for org {organization_id} (using JSONB fallback)")
            return matching_routes
            
        except Exception as e:
            logger.error(f"Error querying routes (JSONB fallback): {e}", exc_info=True)
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
