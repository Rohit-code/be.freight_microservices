"""
Rate Sheet Service

FLOW:
1. Pandas Normalization (NO AI) - Convert Excel to clean grid
2. AI Semantic Extraction - Map to structured schema
3. Validation + Guardrails - Deterministic checks
4. Storage - SQL + Graph + ChromaDB
"""
from typing import List, Dict, Any, Optional
from datetime import datetime
import os
from sqlalchemy.ext.asyncio import AsyncSession
import uuid
import logging
import re
import numpy as np
import hashlib
import httpx

from app.services.excel_parser import ExcelParser
from app.services.rate_sheet_extractor import RateSheetExtractor
from app.services.rate_sheet_pipeline import RateSheetPipeline
from app.services.embedding_service import EmbeddingService
from app.services.rerank_service import RerankService
from app.core.config import settings

logger = logging.getLogger(__name__)


def convert_numpy_types(obj: Any) -> Any:
    """
    Recursively convert numpy types to native Python types for JSON serialization
    Handles numpy types, pandas types, nan, inf, and other non-serializable types
    """
    # Handle None first
    if obj is None:
        return None
    
    # Handle numpy integer types
    if isinstance(obj, (np.integer, np.int64, np.int32, np.int16, np.int8)):
        return int(obj)
    # Handle numpy float types (including nan and inf)
    elif isinstance(obj, (np.floating, np.float64, np.float32, np.float16)):
        # Check for nan and inf values
        if np.isnan(obj):
            return None
        elif np.isinf(obj):
            return None  # or could return "inf" or "-inf" as string, but None is safer
        return float(obj)
    # Handle numpy boolean
    elif isinstance(obj, np.bool_):
        return bool(obj)
    # Handle numpy arrays
    elif isinstance(obj, np.ndarray):
        return [convert_numpy_types(item) for item in obj]
    # Handle pandas Index objects
    elif hasattr(obj, '__class__') and 'pandas' in str(type(obj)) and hasattr(obj, 'tolist'):
        return [convert_numpy_types(item) for item in obj.tolist()]
    # Handle pandas NA/NaN values
    elif hasattr(obj, '__class__') and 'pandas' in str(type(obj)):
        if hasattr(obj, 'isna') and obj.isna().any() if hasattr(obj, 'any') else False:
            return None
    # Handle dictionaries
    elif isinstance(obj, dict):
        return {str(key): convert_numpy_types(value) for key, value in obj.items()}
    # Handle lists and tuples
    elif isinstance(obj, (list, tuple)):
        return [convert_numpy_types(item) for item in obj]
    # Handle native Python float (check for nan/inf)
    elif isinstance(obj, float):
        if np.isnan(obj):
            return None
        elif np.isinf(obj):
            return None
        return obj
    # Handle native Python types (pass through)
    elif isinstance(obj, (str, int, bool)):
        return obj
    # Handle datetime objects
    elif hasattr(obj, 'isoformat'):
        return obj.isoformat()
    else:
        # Try to convert numpy scalar types using item() method
        try:
            if hasattr(obj, 'item') and not isinstance(obj, (str, bytes)):
                item_value = obj.item()
                # Check if the item value is nan or inf
                if isinstance(item_value, float):
                    if np.isnan(item_value):
                        return None
                    elif np.isinf(item_value):
                        return None
                return convert_numpy_types(item_value)
        except (ValueError, AttributeError, TypeError):
            pass
        # Check if it's a pandas NA value
        try:
            if str(type(obj)) in ["<class 'pandas._libs.missing.NAType'>", "<class 'pandas._libs.tslibs.nattype.NaTType'>"]:
                return None
        except Exception:
            pass
        # Try to convert to string as last resort
        try:
            return str(obj)
        except Exception:
            return None  # Return None instead of obj if all else fails


class RateSheetService:
    """
    Main service for rate sheet operations
    
    FLOW:
    1. Pandas Normalization (NO AI) - Convert Excel to clean grid
    2. AI Semantic Extraction - Map to structured schema  
    3. Validation + Guardrails - Deterministic checks
    4. Storage - SQL + Graph + ChromaDB
    """
    
    def __init__(self):
        self.excel_parser = ExcelParser()
        self.extractor = RateSheetExtractor()  # Legacy extractor (backup)
        self.pipeline = RateSheetPipeline(settings.AI_SERVICE_URL)  # NEW: Full pipeline
        self.embedding_service = EmbeddingService()
        self.rerank_service = RerankService()
        self.upload_dir = settings.UPLOAD_DIR
        os.makedirs(self.upload_dir, exist_ok=True)
        
        # Import here to avoid circular imports
        from app.services.structured_data_service import StructuredDataService
        from app.services.graph_aware_ingestion import GraphAwareIngestion
        self.structured_data_service = StructuredDataService()
        self.graph_aware_ingestion = GraphAwareIngestion()
    
    async def upload_rate_sheet(
        self,
        file_content: bytes,
        file_name: str,
        organization_id: int,
        user_id: int,
        async_mode: bool = False
    ) -> Dict[str, Any]:
        """
        Upload and process a rate sheet file - stores in ChromaDB with BGE embeddings
        
        Args:
            file_content: File content bytes
            file_name: Original file name
            organization_id: Organization ID
            user_id: User ID who uploaded
            async_mode: If True, returns immediately and processes in background
        
        Returns:
            Dictionary with rate sheet data (stored in ChromaDB)
        """
        # Calculate file hash for idempotency check
        file_hash = hashlib.sha256(file_content).hexdigest()
        idempotency_key = f"{organization_id}:{file_hash}"
        
        # Check for existing upload with same file content (idempotency)
        existing = await self._check_duplicate(organization_id, file_hash)
        if existing:
            if existing.status == 'processed':
                # File already processed - check if ChromaDB is in sync
                logger.info(f"🔄 Duplicate detected: {existing.rate_sheet_id} (status={existing.status})")
                
                # Check if document exists in ChromaDB - if not, sync it
                chromadb_doc = await self.embedding_service.get_rate_sheet_by_id(existing.rate_sheet_id)
                if not chromadb_doc:
                    logger.warning(f"⚠️ Rate sheet {existing.rate_sheet_id} missing from ChromaDB - syncing now")
                    # Sync to ChromaDB using existing JSONB columns from PostgreSQL
                    try:
                        # Build structured_data from JSONB columns
                        structured_data = {
                            "routes": existing.routes_json or [],
                            "pricing_tiers": existing.pricing_tiers_json or [],
                            "surcharges": existing.surcharges_json or [],
                            "additional_charges": existing.additional_charges or [],
                            "carrier_name": existing.carrier_name or "",
                            "rate_sheet_type": existing.rate_sheet_type or "ocean_freight",
                            "title": existing.title or "",
                            "validity": {
                                "valid_from": existing.valid_from.isoformat() if existing.valid_from else None,
                                "valid_to": existing.valid_to.isoformat() if existing.valid_to else None,
                                "effective_date": existing.effective_date.isoformat() if existing.effective_date else None
                            },
                            "relationships": {
                                "is_related": existing.is_related == "true",
                                "relationship_type": existing.relationship_type or "",
                                "related_to_rate_sheets": existing.related_rate_sheet_ids or []
                            }
                        }
                        now = datetime.utcnow()
                        metadata = {
                            "organization_id": organization_id,
                            "user_id": existing.user_id,
                            "file_name": existing.file_name,
                            "file_path": existing.file_path or "",
                            "file_size_bytes": len(file_content),
                            "file_type": os.path.splitext(existing.file_name)[1].lower() if existing.file_name else "",
                            "status": "processed",
                            "created_at": existing.created_at.isoformat() if existing.created_at else now.isoformat(),
                            "updated_at": now.isoformat(),
                            "processed_at": now.isoformat(),
                        }
                        await self.embedding_service.store_rate_sheet(
                            rate_sheet_id=existing.rate_sheet_id,
                            rate_sheet_data=structured_data,
                            parsed_data={},  # Don't have parsed_data, but that's okay
                            metadata=metadata
                        )
                        logger.info(f"✅ Synced rate sheet {existing.rate_sheet_id} to ChromaDB")
                    except Exception as sync_error:
                        logger.error(f"❌ Failed to sync to ChromaDB: {sync_error}")
                
                return {
                    "id": existing.rate_sheet_id,
                    "status": existing.status,
                    "reused": True,
                    "message": "Identical file already uploaded and processed",
                    "existing_version": existing.version,
                    "file_name": existing.file_name,
                    "carrier_name": existing.carrier_name,
                    "created_at": existing.created_at.isoformat() if existing.created_at else None
                }
            else:
                # File still pending/processing - reuse existing job
                logger.info(f"♻️  Reusing existing job: {existing.rate_sheet_id} (status={existing.status})")
                return {
                    "id": existing.rate_sheet_id,
                    "status": existing.status,
                    "reused": True,
                    "message": f"Identical file already uploaded (status: {existing.status})",
                    "file_name": existing.file_name,
                    "created_at": existing.created_at.isoformat() if existing.created_at else None
                }
        
        # Save file
        file_path = await self._save_file(file_content, file_name, organization_id)
        file_size = len(file_content)
        file_ext = os.path.splitext(file_name)[1].lower()
        
        # Generate unique ID
        rate_sheet_id = str(uuid.uuid4())
        now = datetime.utcnow()
        
        if async_mode:
            # ASYNC MODE: Create pending record and return immediately
            return await self._create_pending_record(
                rate_sheet_id=rate_sheet_id,
                organization_id=organization_id,
                user_id=user_id,
                file_name=file_name,
                file_path=file_path,
                file_size=file_size,
                file_ext=file_ext,
                file_hash=file_hash,
                idempotency_key=idempotency_key
            )
        
        # SYNC MODE: Process immediately (legacy behavior)
        return await self._process_rate_sheet_sync(
            rate_sheet_id=rate_sheet_id,
            organization_id=organization_id,
            user_id=user_id,
            file_name=file_name,
            file_path=file_path,
            file_size=file_size,
            file_ext=file_ext,
            now=now,
            file_hash=file_hash,
            idempotency_key=idempotency_key
        )
    
    async def _check_duplicate(self, organization_id: int, file_hash: str):
        """
        Check if a file with the same hash already exists for this organization.
        Returns the existing record if found, None otherwise.
        """
        from app.core.database import AsyncSessionLocal
        from app.models.structured_data import RateSheetStructuredData
        from sqlalchemy import select, and_
        
        try:
            async with AsyncSessionLocal() as db_session:
                result = await db_session.execute(
                    select(RateSheetStructuredData).where(
                        and_(
                            RateSheetStructuredData.organization_id == organization_id,
                            RateSheetStructuredData.file_hash == file_hash
                        )
                    ).order_by(RateSheetStructuredData.created_at.desc())
                )
                return result.scalar_one_or_none()
        except Exception as e:
            logger.warning(f"Error checking for duplicate: {e}")
            return None
    
    async def _create_pending_record(
        self,
        rate_sheet_id: str,
        organization_id: int,
        user_id: int,
        file_name: str,
        file_path: str,
        file_size: int,
        file_ext: str,
        file_hash: str = None,
        idempotency_key: str = None
    ) -> Dict[str, Any]:
        """
        Phase 1 (Fast): Create a pending record in PostgreSQL and return immediately.
        Background task will process the file later.
        """
        from app.core.database import AsyncSessionLocal
        from app.models.structured_data import RateSheetStructuredData
        
        now = datetime.utcnow()
        
        try:
            async with AsyncSessionLocal() as db_session:
                # Check for existing rate sheet with same carrier/validity to determine version
                version = 1
                supersedes_id = None
                
                # Create pending record
                pending_record = RateSheetStructuredData(
                    rate_sheet_id=rate_sheet_id,
                    organization_id=organization_id,
                    user_id=user_id,
                    file_name=file_name,
                    file_path=file_path,
                    file_hash=file_hash,
                    idempotency_key=idempotency_key,
                    status='pending',
                    version=version,
                    supersedes_rate_sheet_id=supersedes_id,
                    is_active=True,
                    routes=[],  # Will be populated during processing
                    created_at=now,
                    updated_at=now
                )
                
                db_session.add(pending_record)
                await db_session.commit()
                
                logger.info(f"📋 Created pending rate sheet record: {rate_sheet_id}")
                
                return {
                    "id": rate_sheet_id,
                    "status": "pending",
                    "message": "Rate sheet uploaded. Processing in background.",
                    "organization_id": organization_id,
                    "file_name": file_name,
                    "file_size_bytes": file_size,
                    "file_type": file_ext,
                    "created_at": now.isoformat(),
                    "version": version
                }
                
        except Exception as e:
            logger.error(f"Error creating pending record: {e}")
            raise
    
    async def process_rate_sheet_background(self, rate_sheet_id: str) -> Dict[str, Any]:
        """
        Phase 2 (Background): Process a pending rate sheet.
        Called by background task after upload returns.
        """
        from app.core.database import AsyncSessionLocal
        from app.models.structured_data import RateSheetStructuredData
        from sqlalchemy import select
        
        async with AsyncSessionLocal() as db_session:
            # Get the pending record
            result = await db_session.execute(
                select(RateSheetStructuredData).where(
                    RateSheetStructuredData.rate_sheet_id == rate_sheet_id
                )
            )
            record = result.scalar_one_or_none()
            
            if not record:
                raise ValueError(f"Rate sheet {rate_sheet_id} not found")
            
            if record.status != 'pending':
                logger.warning(f"Rate sheet {rate_sheet_id} is not pending (status={record.status})")
                return {"id": rate_sheet_id, "status": record.status}
            
            # Update status to processing
            record.status = 'processing'
            record.processing_started_at = datetime.utcnow()
            await db_session.commit()
            
            logger.info(f"🔄 Processing rate sheet: {rate_sheet_id}")
            
            try:
                # Process the rate sheet
                result = await self._process_rate_sheet_sync(
                    rate_sheet_id=rate_sheet_id,
                    organization_id=record.organization_id,
                    user_id=record.user_id,
                    file_name=record.file_name,
                    file_path=record.file_path,
                    file_size=0,  # Not needed for processing
                    file_ext=os.path.splitext(record.file_name)[1].lower(),
                    now=datetime.utcnow(),
                    update_existing=True  # Update existing record instead of creating new
                )
                
                # Update status to processed
                record.status = 'processed'
                record.processing_completed_at = datetime.utcnow()
                record.processing_error = None
                await db_session.commit()
                
                logger.info(f"✅ Rate sheet processed: {rate_sheet_id}")
                return result
                
            except Exception as e:
                # Update status to failed
                record.status = 'failed'
                record.processing_error = str(e)
                record.processing_completed_at = datetime.utcnow()
                await db_session.commit()
                
                logger.error(f"❌ Rate sheet processing failed: {rate_sheet_id} - {e}")
                raise
    
    async def get_rate_sheet_status(self, rate_sheet_id: str, organization_id: int) -> Dict[str, Any]:
        """Get the processing status of a rate sheet"""
        from app.core.database import AsyncSessionLocal
        from app.models.structured_data import RateSheetStructuredData
        from sqlalchemy import select, and_
        
        async with AsyncSessionLocal() as db_session:
            result = await db_session.execute(
                select(RateSheetStructuredData).where(
                    and_(
                        RateSheetStructuredData.rate_sheet_id == rate_sheet_id,
                        RateSheetStructuredData.organization_id == organization_id
                    )
                )
            )
            record = result.scalar_one_or_none()
            
            if not record:
                return None
            
            return {
                "id": record.rate_sheet_id,
                "status": record.status,
                "file_name": record.file_name,
                "carrier_name": record.carrier_name,
                "version": record.version,
                "is_active": record.is_active,
                "processing_error": record.processing_error,
                "processing_started_at": record.processing_started_at.isoformat() if record.processing_started_at else None,
                "processing_completed_at": record.processing_completed_at.isoformat() if record.processing_completed_at else None,
                "created_at": record.created_at.isoformat() if record.created_at else None
            }
    
    async def _process_rate_sheet_sync(
        self,
        rate_sheet_id: str,
        organization_id: int,
        user_id: int,
        file_name: str,
        file_path: str,
        file_size: int,
        file_ext: str,
        now: datetime,
        update_existing: bool = False,
        file_hash: str = None,
        idempotency_key: str = None
    ) -> Dict[str, Any]:
        """
        Process rate sheet through the full pipeline:
        
        1. PANDAS NORMALIZATION (NO AI) - Convert Excel to clean grid
        2. AI SEMANTIC EXTRACTION - Map to structured schema
        3. VALIDATION + GUARDRAILS - Deterministic checks
        4. STORAGE - SQL + Graph + ChromaDB
        """
        try:
            logger.info(f"🚀 [PIPELINE] Starting processing for: {file_name}")
            
            # =================================================================
            # STAGE 1-3: PANDAS → AI → VALIDATION (via Pipeline)
            # =================================================================
            extracted_data, full_text, is_valid, issues = await self.pipeline.process(file_path)
            
            # Log validation results
            if not is_valid:
                logger.warning(f"⚠️ [PIPELINE] Validation issues: {issues}")
            else:
                logger.info(f"✅ [PIPELINE] Validation passed")
            
            # Get full text for ChromaDB (if not in extracted_data)
            chromadb_text = extracted_data.pop("_full_text_for_chromadb", full_text)
            
            # =================================================================
            # STAGE 4: STORAGE
            # =================================================================
            
            # Prepare metadata
            metadata = {
                "organization_id": organization_id,
                "user_id": user_id,
                "file_name": file_name,
                "file_path": file_path,
                "file_size_bytes": file_size,
                "file_type": file_ext,
                "status": "processed" if is_valid else "processed_with_warnings",
                "validation_passed": is_valid,
                "validation_issues": issues if issues else [],
                "created_at": now.isoformat(),
                "updated_at": now.isoformat(),
                "processed_at": now.isoformat(),
            }
            
            # 4A: Store in ChromaDB (full text for semantic search)
            try:
                # Add full text to extracted data for ChromaDB storage
                extracted_data_for_chromadb = extracted_data.copy()
                extracted_data_for_chromadb["_full_sheet_text"] = chromadb_text
                
                # Parse legacy format for backward compatibility
                parsed_data = self.excel_parser.parse_file(file_path)
                
                await self.embedding_service.store_rate_sheet(
                    rate_sheet_id=rate_sheet_id,
                    rate_sheet_data=extracted_data_for_chromadb,
                    parsed_data=parsed_data,
                    metadata=metadata
                )
                logger.info(f"✅ [STAGE 4A] Stored in ChromaDB for rate sheet {rate_sheet_id}")
            except Exception as chromadb_error:
                logger.error(f"❌ [STAGE 4A] ChromaDB storage failed: {chromadb_error}")
                raise
            
            # 4B: Store structured data in PostgreSQL
            try:
                from app.core.database import AsyncSessionLocal
                async with AsyncSessionLocal() as db_session:
                    if update_existing:
                        await self.structured_data_service.update_structured_data(
                            session=db_session,
                            rate_sheet_id=rate_sheet_id,
                            structured_data=extracted_data
                        )
                    else:
                        await self.structured_data_service.store_structured_data(
                            session=db_session,
                            rate_sheet_id=rate_sheet_id,
                            organization_id=organization_id,
                            user_id=user_id,
                            file_name=file_name,
                            structured_data=extracted_data,
                            file_hash=file_hash,
                            idempotency_key=idempotency_key
                        )
                    logger.info(f"✅ [STAGE 4B] Stored in PostgreSQL for rate sheet {rate_sheet_id}")
            except Exception as sql_error:
                logger.error(f"⚠️ [STAGE 4B] PostgreSQL storage failed (non-critical): {sql_error}")
            
            # 4C: Store graph relationships in ArangoDB
            try:
                await self.graph_aware_ingestion.ingest_rate_sheet(
                    rate_sheet_id=rate_sheet_id,
                    organization_id=organization_id,
                    structured_data=extracted_data,
                    raw_content=chromadb_text
                )
                logger.info(f"✅ [STAGE 4C] Stored in ArangoDB for rate sheet {rate_sheet_id}")
            except Exception as graph_error:
                logger.warning(f"⚠️ [STAGE 4C] ArangoDB storage failed (non-critical): {graph_error}")
            
            # Convert numpy types for JSON serialization
            converted_extracted_data = convert_numpy_types(extracted_data)
            
            response_data = {
                "id": rate_sheet_id,
                **metadata,
                **converted_extracted_data,
                "routes_count": len(extracted_data.get("routes", [])),
                "validation_passed": is_valid
            }
            
            logger.info(f"🏁 [PIPELINE] Processing complete for {file_name}: {len(extracted_data.get('routes', []))} routes")
            
            return convert_numpy_types(response_data)
        
        except Exception as e:
            import traceback
            error_details = str(e) if str(e) else repr(e)
            logger.error(f"Error processing rate sheet {rate_sheet_id}: {error_details}", exc_info=True)
            # Store failed status in ChromaDB
            try:
                failed_metadata = {
                    "organization_id": organization_id,
                    "user_id": user_id,
                    "file_name": file_name,
                    "file_path": file_path,
                    "file_size_bytes": file_size,
                    "file_type": file_ext,
                    "status": "failed",
                    "processing_error": error_details,
                    "created_at": now.isoformat(),
                    "updated_at": now.isoformat(),
                }
                await self.embedding_service.store_rate_sheet(
                    rate_sheet_id=rate_sheet_id,
                    rate_sheet_data={"error": error_details},
                    parsed_data={},
                    metadata=failed_metadata
                )
            except Exception as store_error:
                store_error_details = str(store_error) if str(store_error) else repr(store_error)
                logger.error(f"Error storing failed rate sheet: {store_error_details}", exc_info=True)
            
            raise Exception(f"Failed to process rate sheet {rate_sheet_id}: {error_details}") from e
    
    async def _save_file(self, file_content: bytes, file_name: str, organization_id: int) -> str:
        """Save uploaded file to disk"""
        org_dir = os.path.join(self.upload_dir, f"org_{organization_id}")
        os.makedirs(org_dir, exist_ok=True)
        
        # Generate unique file name
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        safe_file_name = "".join(c for c in file_name if c.isalnum() or c in "._- ")
        unique_file_name = f"{timestamp}_{safe_file_name}"
        file_path = os.path.join(org_dir, unique_file_name)
        
        with open(file_path, "wb") as f:
            f.write(file_content)
        
        return file_path
    
    async def _get_recent_rate_sheets(
        self,
        organization_id: int,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """Get recent rate sheets for relationship detection from ChromaDB"""
        try:
            # Search for recent rate sheets by organization
            results = await self.embedding_service.search_rate_sheets(
                query="rate sheet",
                organization_id=organization_id,
                limit=limit
            )
            
            return [
                {
                    "id": result["id"],
                    "file_name": result["metadata"].get("file_name", ""),
                    "carrier_name": result["metadata"].get("carrier_name", ""),
                    "rate_sheet_type": result["metadata"].get("rate_sheet_type", ""),
                    "title": result["metadata"].get("title", "")
                }
                for result in results
            ]
        except Exception as e:
            logger.error(f"Error getting recent rate sheets: {e}")
            return []
    
    async def get_rate_sheet(
        self,
        rate_sheet_id: str,
        organization_id: int
    ) -> Optional[Dict[str, Any]]:
        """
        Get rate sheet by ID from ChromaDB
        
        IMPORTANT: Enforces organization-level data isolation.
        Returns None if the rate sheet doesn't belong to the specified organization.
        """
        try:
            result = await self.embedding_service.get_rate_sheet_by_id(rate_sheet_id)
            
            if not result:
                logger.debug(f"Rate sheet {rate_sheet_id} not found")
                return None
            
            # SECURITY: Verify organization access - CRITICAL for multi-tenant isolation
            meta_org_id = result.get("metadata", {}).get("organization_id")
            if meta_org_id != str(organization_id):
                logger.warning(f"Access denied: Rate sheet {rate_sheet_id} belongs to organization {meta_org_id}, but request was for {organization_id}")
                return None  # Return None to prevent data leakage between organizations
            
            return {
                "id": result.get("id"),
                "document": result.get("document"),  # Full raw content
                "metadata": result.get("metadata")
            }
        except Exception as e:
            logger.error(f"Error getting rate sheet {rate_sheet_id} for organization_id={organization_id}: {e}")
            return None
    
    @staticmethod
    def _is_simple_query(
        query: Optional[str],
        origin_code: Optional[str],
        destination_code: Optional[str],
        container_type: Optional[str]
    ) -> bool:
        """True if query is 1-6 words and no route/container filters → vector-only, no orchestrator, short answer (low latency)."""
        if not query or not query.strip():
            return False
        words = len(query.strip().split())
        if words > 6:
            return False
        if origin_code or destination_code or container_type:
            return False
        return True

    @staticmethod
    def _is_list_or_fact_query(query: Optional[str]) -> bool:
        """True if user wants a list of routes/costs or a direct fact, not an essay. Used to force short answer and skip orchestrator."""
        if not query or not query.strip():
            return False
        q = query.lower().strip()
        list_fact_phrases = (
            "what route", "which route", "what routes", "which routes", "list ", "list the",
            "costs of", "costs for", "cost of", "cost for", "routes and cost", "routes and costs",
            "routes has", "routes have", "tell me what route", "tell me what routes",
            "price for", "price of", "prices for", "40 foot", "40-foot", "20 foot", "20-foot"
        )
        return any(p in q for p in list_fact_phrases)

    @staticmethod
    def _has_long_answer_keywords(query: Optional[str]) -> bool:
        """True if query explicitly asks for explanation/detail/compare (long answer)."""
        if not query or not query.strip():
            return False
        q = query.lower().strip()
        long_keywords = (
            "explain", "detail", "details", "breakdown", "compare", "how to", "how do", "how does", "how can",
            "why ", "walkthrough", "comprehensive", "full ", "alternatives", "options", "difference", "versus", "vs "
        )
        if "how much" in q or "how many" in q:
            return False
        return any(k in q for k in long_keywords)

    async def _get_intent_for_query(self, query: Optional[str]) -> Optional[Dict[str, Any]]:
        """Call intent classifier to get intent + answer_preferences. Used when we don't have orchestrator intent."""
        if not query or not query.strip():
            print("[INTENT] No query → skip intent classifier")
            return None
        try:
            print(f"[INTENT] Calling intent classifier: {settings.INTENT_CLASSIFIER_SERVICE_URL}/api/intent/classify")
            async with httpx.AsyncClient(timeout=8.0) as client:
                resp = await client.post(
                    f"{settings.INTENT_CLASSIFIER_SERVICE_URL}/api/intent/classify",
                    json={"email_content": query.strip(), "subject": None, "from_email": None},
                )
                if resp.status_code == 200:
                    out = resp.json()
                    print(f"[INTENT] OK: intent={out.get('intent')} prefs={out.get('answer_preferences')}")
                    return out
                print(f"[INTENT] HTTP {resp.status_code}")
        except Exception as e:
            print(f"[INTENT] Error: {e}")
            logger.debug(f"Intent classifier unavailable or error: {e}")
        return None

    @staticmethod
    def _should_skip_orchestrator(
        query: Optional[str],
        origin_code: Optional[str],
        destination_code: Optional[str],
        container_type: Optional[str]
    ) -> bool:
        """True when we can skip orchestrator for latency: no port/container filters, and query is list/fact or not asking for long explanation."""
        if origin_code or destination_code or container_type:
            return False
        if not query or not query.strip():
            return False
        if RateSheetService._has_long_answer_keywords(query):
            return False
        return True

    @staticmethod
    def _should_use_long_answer(
        query: Optional[str],
        intent_result: Optional[Dict[str, Any]],
        exact_rates: List[Dict[str, Any]],
        route_alternatives: List[Dict[str, Any]]
    ) -> bool:
        """
        Use LONG only when the user explicitly asks to explain / compare / how-to / why.
        For routes, costs, or any data question → always short/list. No long answer even if many rates.
        """
        if not query:
            return False
        if RateSheetService._is_list_or_fact_query(query):
            return False
        return RateSheetService._has_long_answer_keywords(query)

    async def search_rate_sheets(
        self,
        organization_id: int,
        query: Optional[str] = None,
        carrier_name: Optional[str] = None,
        origin_code: Optional[str] = None,
        destination_code: Optional[str] = None,
        container_type: Optional[str] = None,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """
        Two-stage semantic search:
        1. Vector search (BGE embeddings) to get top 20 results
        2. OpenAI re-ranking to get top 3 most relevant results
        
        Args:
            organization_id: Organization ID
            query: Semantic search query
            carrier_name: Filter by carrier name
            origin_code: Filter by origin port code
            destination_code: Filter by destination port code
            container_type: Filter by container type
            limit: Maximum results (ignored, always returns top 3 after re-ranking)
        
        Returns:
            List of top 3 re-ranked rate sheets with similarity scores
        """
        try:
            print(f"\n[RATE SHEET SEARCH] query={query!r} org={organization_id} carrier={carrier_name} origin={origin_code} dest={destination_code} container={container_type}")
            # FAST PATH: If no query and no filters requiring semantic search, skip AI processing
            # This significantly speeds up simple list requests
            has_semantic_filters = origin_code or destination_code or container_type
            if not query and not has_semantic_filters:
                print("[RATE SHEET SEARCH] Path: FAST (no query) → return all rate sheets, no AI")
                logger.info("Fast path: No query provided, skipping AI processing and returning all rate sheets")
                # Get all rate sheets directly from vector DB (filtered by organization_id)
                # Use a reasonable limit - most orgs won't have more than 1000 rate sheets
                # Request exactly what we need to avoid unnecessary computation
                vector_results = await self.embedding_service.search_rate_sheets(
                    query="rate sheet",  # Generic query to get all results
                    organization_id=organization_id,
                    limit=min(limit, 1000),  # Cap at 1000 to avoid excessive computation
                    filters={"carrier_name": carrier_name} if carrier_name else {}
                )
                
                if not vector_results:
                    return {
                        "answer": "",
                        "results": [],
                        "total_found": 0,
                        "total_returned": 0
                    }
                
                # Format results without AI processing
                formatted_results = []
                for result in vector_results:
                    metadata = result.get("metadata", {})
                    document = result.get("document", "")
                    
                    # Apply carrier filter if provided
                    if carrier_name and metadata.get("carrier_name", "").lower() != carrier_name.lower():
                        continue
                    
                    formatted_results.append({
                        "id": result.get("id"),
                        "file_name": metadata.get("file_name", ""),
                        "carrier_name": metadata.get("carrier_name", ""),
                        "title": metadata.get("title", ""),
                        "rate_sheet_type": metadata.get("rate_sheet_type", ""),
                        "status": metadata.get("status", ""),
                        "similarity": result.get("similarity", 0),
                        "distance": result.get("distance", 1),
                        "metadata": metadata,
                        "document": document,
                        "document_preview": document[:1000],
                        "matching_data": {}
                    })
                
                print(f"[RATE SHEET SEARCH] Returning {len(formatted_results)} rate sheets (no AI)")
                logger.info(f"Fast path: Returning {len(formatted_results)} rate sheets without AI processing")
                return {
                    "answer": "",  # No AI answer for simple list
                    "results": formatted_results[:limit],  # Respect limit
                    "total_found": len(formatted_results),
                    "total_returned": min(len(formatted_results), limit)
                }
            
            # SLOW PATH: Use agentic (Orchestrator) when there's a query, then re-rank + answer
            search_query = query or "rate sheet"
            query_lower = query.lower() if query else ""

            # --- Simple-query fast path (low latency): 1-3 words, no route/container filters → vector-only, no rerank, short answer ---
            if self._is_simple_query(query, origin_code, destination_code, container_type):
                print("[RATE SHEET SEARCH] Path: SIMPLE-QUERY (1-6 words, no filters) → vector-only, no orchestrator")
                filters = {"carrier_name": carrier_name} if carrier_name else {}
                vector_results = await self.embedding_service.search_rate_sheets(
                    query=search_query,
                    organization_id=organization_id,
                    limit=10,
                    filters=filters
                )
                formatted_fast = []
                for result in vector_results:
                    metadata = result.get("metadata", {})
                    document = result.get("document", "")
                    if carrier_name and (metadata.get("carrier_name") or "").lower() != carrier_name.lower():
                        continue
                    formatted_fast.append({
                        "id": result.get("id"),
                        "file_name": metadata.get("file_name", ""),
                        "carrier_name": metadata.get("carrier_name", ""),
                        "title": metadata.get("title", ""),
                        "rate_sheet_type": metadata.get("rate_sheet_type", ""),
                        "status": metadata.get("status", ""),
                        "similarity": result.get("similarity", 0),
                        "distance": result.get("distance", 1),
                        "metadata": metadata,
                        "document": document,
                        "document_preview": document[:1000],
                        "matching_data": self._extract_matching_data(document, query_lower)
                    })
                top_fast = formatted_fast[: min(5, limit)]
                print(f"[RATE SHEET SEARCH] Simple path: vector returned {len(formatted_fast)} results, using top {len(top_fast)}")
                intent_fast = await self._get_intent_for_query(query)
                print(f"[RATE SHEET SEARCH] Intent (simple path): intent={intent_fast.get('intent') if intent_fast else None} prefs={intent_fast.get('answer_preferences') if intent_fast else None}")
                fast_style = (intent_fast or {}).get("answer_preferences", {}).get("answer_format") or ("list" if self._is_list_or_fact_query(query) else "short")
                print(f"[RATE SHEET SEARCH] Generating answer style={fast_style} (from intent or fallback)")
                ai_answer_fast = await self.rerank_service.generate_answer(
                    query=search_query, results=top_fast, answer_style=fast_style, intent_result=intent_fast
                )
                print(f"[RATE SHEET SEARCH] Simple path done → returning answer + {len(top_fast)} results")
                logger.info(f"Simple-query fast path: {len(formatted_fast)} results, top {len(top_fast)}, short answer")
                return {
                    "answer": ai_answer_fast,
                    "results": top_fast,
                    "total_found": len(formatted_fast),
                    "total_returned": len(top_fast),
                }

            # --- Vector-only path (skip orchestrator for latency): list/fact query, no port/container filters ---
            if self._should_skip_orchestrator(query, origin_code, destination_code, container_type):
                print("[RATE SHEET SEARCH] Path: VECTOR-ONLY (skip orchestrator) → vector + rerank + answer")
                filters = {"carrier_name": carrier_name} if carrier_name else {}
                vector_results = await self.embedding_service.search_rate_sheets(
                    query=search_query,
                    organization_id=organization_id,
                    limit=10,
                    filters=filters
                )
                formatted_v = []
                for result in vector_results:
                    metadata = result.get("metadata", {})
                    document = result.get("document", "")
                    if carrier_name and (metadata.get("carrier_name") or "").lower() != carrier_name.lower():
                        continue
                    formatted_v.append({
                        "id": result.get("id"),
                        "file_name": metadata.get("file_name", ""),
                        "carrier_name": metadata.get("carrier_name", ""),
                        "title": metadata.get("title", ""),
                        "rate_sheet_type": metadata.get("rate_sheet_type", ""),
                        "status": metadata.get("status", ""),
                        "similarity": result.get("similarity", 0),
                        "distance": result.get("distance", 1),
                        "metadata": metadata,
                        "document": document,
                        "document_preview": document[:1000],
                        "matching_data": self._extract_matching_data(document, query_lower)
                    })
                rerank_candidates_v = formatted_v[:8]
                top_k_v = min(5, max(1, len(rerank_candidates_v)))
                if len(rerank_candidates_v) > top_k_v:
                    top_v = await self.rerank_service.rerank_results(
                        query=query or search_query,
                        results=rerank_candidates_v,
                        top_k=top_k_v
                    )
                else:
                    top_v = rerank_candidates_v[:top_k_v]
                print(f"[RATE SHEET SEARCH] Vector-only: vector returned {len(formatted_v)} results, rerank top_k={top_k_v} → {len(top_v)} results")
                intent_v = await self._get_intent_for_query(query)
                print(f"[RATE SHEET SEARCH] Intent (vector-only): intent={intent_v.get('intent') if intent_v else None} prefs={intent_v.get('answer_preferences') if intent_v else None}")
                vector_style = (intent_v or {}).get("answer_preferences", {}).get("answer_format") or ("list" if self._is_list_or_fact_query(query) else "short")
                print(f"[RATE SHEET SEARCH] Generating answer style={vector_style} intent_result={'yes' if intent_v else 'no'}")
                ai_answer_v = await self.rerank_service.generate_answer(
                    query=search_query, results=top_v, answer_style=vector_style, intent_result=intent_v
                )
                print(f"[RATE SHEET SEARCH] Vector-only path done → returning answer + {len(top_v)} results")
                logger.info(f"Vector-only path (no orchestrator): {len(formatted_v)} results, top {len(top_v)}, answer_style={vector_style}")
                return {
                    "answer": ai_answer_v,
                    "results": top_v,
                    "total_found": len(formatted_v),
                    "total_returned": len(top_v),
                }

            # --- Agentic path: call Orchestrator (Intent + SQL + Graph + Vector) ---
            print("[RATE SHEET SEARCH] Path: AGENTIC → calling Orchestrator (intent + SQL + graph + vector)")
            formatted_results = []
            exact_rates: List[Dict[str, Any]] = []
            route_alternatives: List[Dict[str, Any]] = []
            intent_result: Optional[Dict[str, Any]] = None
            engines_used: Optional[Dict[str, bool]] = None

            try:
                async with httpx.AsyncClient(timeout=60.0) as client:
                    resp = await client.post(
                        f"{settings.ORCHESTRATOR_SERVICE_URL}/api/orchestrator/query",
                        params={"organization_id": organization_id},
                        json={
                            "email_content": search_query,
                            "subject": None,
                            "from_email": None
                        }
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        intent_result = data.get("intent", {})
                        engines_used = data.get("engines_used", {})
                        combined = data.get("results", {})
                        exact_rates = combined.get("exact_rates", [])
                        route_alternatives = combined.get("route_alternatives", [])
                        semantic_context = combined.get("semantic_context", [])
                        print(f"[RATE SHEET SEARCH] Orchestrator OK: intent={intent_result.get('intent')} engines={engines_used} exact_rates={len(exact_rates)} semantic_context={len(semantic_context)}")

                        # Filter semantic_context by organization_id (metadata may store as string)
                        for item in semantic_context:
                            meta = item.get("metadata", {})
                            if str(meta.get("organization_id")) != str(organization_id):
                                continue
                            doc = item.get("content", "")
                            if origin_code and origin_code.lower() not in doc.lower():
                                continue
                            if destination_code and destination_code.lower() not in doc.lower():
                                continue
                            if container_type and container_type.lower() not in doc.lower():
                                continue
                            if carrier_name and (meta.get("carrier_name") or "").lower() != carrier_name.lower():
                                continue
                            matching_data = self._extract_matching_data(doc, query_lower)
                            formatted_results.append({
                                "id": item.get("id"),
                                "file_name": meta.get("file_name", ""),
                                "carrier_name": meta.get("carrier_name", ""),
                                "title": meta.get("title", ""),
                                "rate_sheet_type": meta.get("rate_sheet_type", ""),
                                "status": meta.get("status", ""),
                                "similarity": 0,
                                "distance": 0,
                                "metadata": meta,
                                "document": doc,
                                "document_preview": doc[:1000],
                                "matching_data": matching_data
                            })
                        logger.info(f"Agentic path: intent={intent_result.get('intent')}, exact_rates={len(exact_rates)}, semantic={len(formatted_results)}, engines={engines_used}")
            except Exception as orch_err:
                print(f"[RATE SHEET SEARCH] Orchestrator error: {orch_err} → fallback to vector-only")
                logger.warning(f"Orchestrator unavailable or error, falling back to vector-only search: {orch_err}")

            # Fallback: if agentic path returned no semantic results, use vector-only search
            if not formatted_results:
                print("[RATE SHEET SEARCH] Agentic returned 0 semantic results → fallback vector search")
                # Build filters
                if carrier_name:
                    search_query += f" carrier {carrier_name}"
                if origin_code:
                    search_query += f" origin {origin_code}"
                if destination_code:
                    search_query += f" destination {destination_code}"
                if container_type:
                    search_query += f" container {container_type}"
                filters = {"carrier_name": carrier_name} if carrier_name else {}

                logger.info(f"Stage 1 (fallback): Vector search for query: '{search_query}' (limit=10 for latency)")
                vector_results = await self.embedding_service.search_rate_sheets(
                    query=search_query,
                    organization_id=organization_id,
                    limit=10,
                    filters=filters
                )
                if not vector_results:
                    return {
                        "answer": "",
                        "results": [],
                        "total_found": 0,
                        "total_returned": 0,
                        "intent": intent_result,
                        "engines_used": engines_used,
                        "exact_rates": exact_rates,
                        "route_alternatives": route_alternatives
                    }

                for result in vector_results:
                    metadata = result.get("metadata", {})
                    document = result.get("document", "")
                    if origin_code and origin_code.lower() not in document.lower():
                        continue
                    if destination_code and destination_code.lower() not in document.lower():
                        continue
                    if container_type and container_type.lower() not in document.lower():
                        continue
                    matching_data = self._extract_matching_data(document, query_lower)
                    formatted_results.append({
                        "id": result.get("id"),
                        "file_name": metadata.get("file_name", ""),
                        "carrier_name": metadata.get("carrier_name", ""),
                        "title": metadata.get("title", ""),
                        "rate_sheet_type": metadata.get("rate_sheet_type", ""),
                        "status": metadata.get("status", ""),
                        "similarity": result.get("similarity", 0),
                        "distance": result.get("distance", 1),
                        "metadata": metadata,
                        "document": document,
                        "document_preview": document[:1000],
                        "matching_data": matching_data
                    })

            if not formatted_results:
                return {
                    "answer": "",
                    "results": [],
                    "total_found": 0,
                    "total_returned": 0,
                    "intent": intent_result,
                    "engines_used": engines_used,
                    "exact_rates": exact_rates,
                    "route_alternatives": route_alternatives
                }

            # Stage 2: Re-rank (cap at 8 candidates for latency; top_k up to 5, or 10 when user asks for "all routes")
            rerank_candidates = formatted_results[:8]
            q_lower = (query or "").lower()
            want_all_routes = any(p in q_lower for p in ["all route", "every route", "provide all", "all the routes", "all routes", "list all"])
            top_k = min(max(1, limit), len(rerank_candidates), 10 if want_all_routes else 5)
            print(f"[RATE SHEET SEARCH] Stage 2: Re-rank candidates={len(rerank_candidates)} top_k={top_k} (want_all_routes={want_all_routes})")
            logger.info(f"Stage 2: Re-ranking {len(rerank_candidates)} results with OpenAI, top_k={top_k}")
            top_results = await self.rerank_service.rerank_results(
                query=query or search_query,
                results=rerank_candidates,
                top_k=top_k
            )

            # Stage 3: Generate answer (list / short / long). List = routes+costs only, no prose.
            answer_style = "list" if self._is_list_or_fact_query(query) else (
                "long" if self._should_use_long_answer(
                    query, intent_result, exact_rates, route_alternatives
                ) else "short"
            )
            print(f"[RATE SHEET SEARCH] Stage 3: answer_style={answer_style} intent_result={'yes' if intent_result else 'no'} prefs={intent_result.get('answer_preferences') if intent_result else None}")
            logger.info(f"Stage 3: Generating {answer_style} answer from top {len(top_results)} results")
            ai_answer = await self.rerank_service.generate_answer(
                query=query or search_query,
                results=top_results,
                answer_style=answer_style,
                intent_result=intent_result
            )
            print(f"[RATE SHEET SEARCH] Agentic path done → returning answer + {len(top_results)} results")
            return {
                "answer": ai_answer,
                "results": top_results,
                "total_found": len(formatted_results),
                "total_returned": len(top_results),
                "intent": intent_result,
                "engines_used": engines_used,
                "exact_rates": exact_rates,
                "route_alternatives": route_alternatives
            }
        
        except Exception as e:
            print(f"[RATE SHEET SEARCH] Error: {e}")
            logger.error(f"Error searching rate sheets: {e}")
            return []
    
    def _extract_matching_data(self, document: str, query: str) -> Dict[str, Any]:
        """
        Extract relevant matching data from the document based on query
        Returns matching rows, sections, and key information from within the Excel sheets
        """
        if not query:
            return {
                "matching_rows": [],
                "matching_sections": [],
                "key_matches": [],
                "extracted_data": []
            }
        
        matching_data = {
            "matching_rows": [],
            "matching_sections": [],
            "key_matches": [],
            "extracted_data": []  # Structured data extracted from matching rows
        }
        
        # Normalize query terms: strip punctuation so "sheva?" matches "sheva" in the document
        _strip_punctuation = lambda t: re.sub(r"^[?!.,;:\"\s]+|[?!.,;:\"\s]+$", "", t)
        query_terms = query.split()
        query_terms_lower = [_strip_punctuation(term).lower() for term in query_terms if _strip_punctuation(term)]
        
        # Split document into lines
        lines = document.split('\n')
        
        # Find matching rows (lines that contain query terms)
        # Focus on "Row X:" lines which contain actual Excel data
        matching_rows = []
        extracted_data_rows = []
        
        for idx, line in enumerate(lines):
            line_lower = line.lower()
            # Check if line contains any query term
            matches = [term for term in query_terms_lower if term in line_lower]
            
            if matches:
                # Check if this is a data row (starts with "Row X:")
                if line.strip().startswith("Row ") and ":" in line:
                    # Extract structured data from row
                    row_content = line.split(":", 1)[1].strip() if ":" in line else line.strip()
                    # Parse key-value pairs from row (format: "key: value | key: value")
                    row_data = {}
                    if " | " in row_content:
                        for pair in row_content.split(" | "):
                            if ":" in pair:
                                key, value = pair.split(":", 1)
                                key = key.strip()
                                value = value.strip()
                                # Only include non-null values
                                if value and value.lower() != "null":
                                    row_data[key] = value
                    
                    matching_rows.append({
                        "line_number": idx + 1,
                        "content": line.strip(),
                        "matched_terms": matches,
                        "structured_data": row_data if row_data else None
                    })
                    
                    # Extract key data points if row has structured data
                    if row_data:
                        extracted_data_rows.append({
                            "row": idx + 1,
                            "data": row_data,
                            "matched_terms": matches
                        })
                else:
                    # Regular matching line (header, section, etc.)
                    matching_rows.append({
                        "line_number": idx + 1,
                        "content": line.strip(),
                        "matched_terms": matches
                    })
                
                # Limit to top 30 matching rows
                if len(matching_rows) >= 30:
                    break
        
        matching_data["matching_rows"] = matching_rows[:30]
        matching_data["extracted_data"] = extracted_data_rows[:20]
        
        # Extract key information patterns (ports, prices, container types, etc.)
        key_patterns = {
            "ports": ["port", "pod", "pol", "discharge", "origin", "destination"],
            "prices": ["rate", "price", "freight", "cost", "amount", "usd", "inr", "vgm"],
            "containers": ["20'", "40'", "40hc", "container", "teu", "20ft", "40ft"],
            "routes": ["via", "routing", "transit", "direct"],
            "locations": ["nhav", "mundra", "chennai", "kolkata", "bangalore", "mumbai", 
                         "chittagong", "dhaka", "karachi", "jebel", "bangkok", "laem"]
        }
        
        key_matches = []
        query_lower = query.lower()
        
        for category, patterns in key_patterns.items():
            for pattern in patterns:
                if pattern in query_lower:
                    # Find lines containing this pattern with context
                    found_contexts = []
                    for line in lines:
                        if pattern.lower() in line.lower():
                            # Extract surrounding context
                            line_idx = lines.index(line)
                            context_lines = lines[max(0, line_idx-1):min(len(lines), line_idx+2)]
                            context = "\n".join(context_lines).strip()
                            
                            found_contexts.append({
                                "category": category,
                                "pattern": pattern,
                                "context": context[:300],
                                "line_number": line_idx + 1
                            })
                            
                            if len(found_contexts) >= 3:  # Limit per pattern
                                break
                    
                    key_matches.extend(found_contexts)
        
        matching_data["key_matches"] = key_matches[:15]
        
        # Extract matching sections (grouped by sheet or section)
        sections = []
        current_section = None
        section_match_count = 0
        
        for idx, line in enumerate(lines):
            # Detect section headers (like "--- Sheet: ..." or "===")
            if "--- Sheet:" in line or line.strip().startswith("==="):
                if current_section and section_match_count > 0:
                    sections.append(current_section)
                current_section = {
                    "header": line.strip(),
                    "content": [],
                    "match_count": 0
                }
                section_match_count = 0
            elif current_section:
                # Check if line matches query
                if any(term in line.lower() for term in query_terms_lower):
                    current_section["content"].append(line.strip())
                    current_section["match_count"] += 1
                    section_match_count += 1
                    # Limit content per section
                    if len(current_section["content"]) >= 15:
                        break
        
        if current_section and section_match_count > 0:
            sections.append(current_section)
        
        # Sort sections by match count (most relevant first)
        sections.sort(key=lambda x: x.get("match_count", 0), reverse=True)
        matching_data["matching_sections"] = sections[:5]
        
        return matching_data
    
    async def delete_rate_sheet(
        self,
        rate_sheet_id: str,
        organization_id: int
    ) -> bool:
        """Delete rate sheet from all stores: PostgreSQL (structured + routes/pricing_tiers/surcharges), ChromaDB, and uploaded file on disk."""
        try:
            import httpx
            from app.core.database import AsyncSessionLocal

            # 1. Get PG record to verify ownership and get file_path for file deletion
            async with AsyncSessionLocal() as db_session:
                record = await self.structured_data_service.get_structured_data(db_session, rate_sheet_id, organization_id)
                if not record:
                    logger.warning(f"Rate sheet {rate_sheet_id} not found in PostgreSQL for org {organization_id}")
                    return False
                file_path = getattr(record, "file_path", None)

                # 2. Delete from PostgreSQL (rate_sheet_structured_data + routes, pricing_tiers, surcharges)
                pg_ok = await self.structured_data_service.delete_structured_data(db_session, rate_sheet_id, organization_id)
                if not pg_ok:
                    logger.error(f"Failed to delete rate sheet {rate_sheet_id} from PostgreSQL")
                    return False

            # 3. Delete from ChromaDB (vector store)
            from app.services.embedding_service import RATE_SHEETS_COLLECTION
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.delete(
                    f"{settings.VECTOR_DB_SERVICE_URL}/api/vector/collections/{RATE_SHEETS_COLLECTION}/documents/{rate_sheet_id}"
                )
                if response.status_code != 200:
                    logger.warning(f"ChromaDB delete returned {response.status_code}: {response.text} (PG already deleted)")

            # 4. Delete uploaded file on disk if path exists
            if file_path and isinstance(file_path, str) and os.path.exists(file_path):
                try:
                    os.remove(file_path)
                    logger.info(f"Deleted uploaded file: {file_path}")
                except OSError as e:
                    logger.warning(f"Could not delete file {file_path}: {e}")

            logger.info(f"Deleted rate sheet {rate_sheet_id} (PG + ChromaDB + file)")
            return True

        except Exception as e:
            logger.error(f"Error deleting rate sheet: {e}", exc_info=True)
            return False
    
    async def reprocess_rate_sheet(
        self,
        rate_sheet_id: str,
        organization_id: int
    ) -> Optional[Dict[str, Any]]:
        """
        Reprocess a rate sheet that failed AI extraction.
        
        This will:
        1. Get the rate sheet record from PostgreSQL
        2. Re-read the stored file (if available) or use stored raw content
        3. Re-parse the Excel data
        4. Re-run AI extraction with the fixed endpoint
        5. Update the structured data in PostgreSQL
        6. Update the graph data in ArangoDB
        
        Returns:
            Updated rate sheet data or None if not found
        """
        from app.core.database import AsyncSessionLocal
        from app.models import RateSheetStructuredData
        from sqlalchemy import select
        
        logger.info(f"🔄 Reprocessing rate sheet {rate_sheet_id} for org {organization_id}")
        
        try:
            # Step 1: Get the rate sheet record
            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(RateSheetStructuredData).where(
                        RateSheetStructuredData.rate_sheet_id == rate_sheet_id,
                        RateSheetStructuredData.organization_id == organization_id
                    )
                )
                record = result.scalar_one_or_none()
                
                if not record:
                    logger.warning(f"Rate sheet {rate_sheet_id} not found for org {organization_id}")
                    return None
                
                file_name = record.file_name
                file_path = record.file_path
                user_id = record.user_id
            
            # Step 2: Read the file content
            file_content = None
            
            # Try to read from stored file path
            if file_path and os.path.exists(file_path):
                logger.info(f"📁 Reading file from: {file_path}")
                with open(file_path, 'rb') as f:
                    file_content = f.read()
            else:
                # Try to construct path from upload_dir
                expected_path = os.path.join(self.upload_dir, str(organization_id), file_name)
                if os.path.exists(expected_path):
                    logger.info(f"📁 Reading file from: {expected_path}")
                    with open(expected_path, 'rb') as f:
                        file_content = f.read()
                else:
                    # Search in upload directory
                    for root, dirs, files in os.walk(self.upload_dir):
                        for f in files:
                            if f == file_name or rate_sheet_id in f:
                                full_path = os.path.join(root, f)
                                logger.info(f"📁 Found file at: {full_path}")
                                with open(full_path, 'rb') as file:
                                    file_content = file.read()
                                break
                        if file_content:
                            break
            
            if not file_content:
                logger.error(f"❌ Could not find file for rate sheet {rate_sheet_id}")
                # Update status to failed
                async with AsyncSessionLocal() as session:
                    result = await session.execute(
                        select(RateSheetStructuredData).where(
                            RateSheetStructuredData.rate_sheet_id == rate_sheet_id
                        )
                    )
                    record = result.scalar_one_or_none()
                    if record:
                        record.status = 'failed'
                        record.processing_error = 'File not found for reprocessing'
                        await session.commit()
                return {
                    "id": rate_sheet_id,
                    "status": "failed",
                    "error": "File not found for reprocessing. Please re-upload the file."
                }
            
            # Step 3: Parse the Excel file - need to save to temp file first
            import tempfile
            logger.info(f"📊 Parsing Excel file: {file_name}")
            
            # Save content to temp file for parsing
            with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(file_name)[1]) as tmp:
                tmp.write(file_content)
                tmp_path = tmp.name
            
            try:
                parsed_data = self.excel_parser.parse_file(tmp_path)
                parsed_data = convert_numpy_types(parsed_data)
            finally:
                # Clean up temp file
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)
            
            # Step 4: Run AI extraction (with fixed endpoint)
            logger.info(f"🤖 Running AI extraction for: {file_name}")
            extracted_data = await self.extractor.extract_structured_data(
                parsed_data=parsed_data,
                file_name=file_name,
                existing_rate_sheets=None
            )
            extracted_data = convert_numpy_types(extracted_data)
            
            routes_count = len(extracted_data.get('routes', []))
            logger.info(f"✅ AI extraction complete: {routes_count} routes extracted")
            
            # Step 5: Update structured data in PostgreSQL
            async with AsyncSessionLocal() as session:
                updated_record = await self.structured_data_service.update_structured_data(
                    session=session,
                    rate_sheet_id=rate_sheet_id,
                    structured_data=extracted_data
                )
                logger.info(f"✅ Updated PostgreSQL record for {rate_sheet_id}")
            
            # Step 6: Update graph data in ArangoDB
            try:
                await self.graph_aware_ingestion.ingest_rate_sheet(
                    rate_sheet_id=rate_sheet_id,
                    organization_id=organization_id,
                    structured_data=extracted_data
                )
                logger.info(f"✅ Updated ArangoDB graph for {rate_sheet_id}")
            except Exception as e:
                logger.warning(f"⚠️ Graph update failed (non-critical): {e}")
            
            # Step 7: Store/Update in ChromaDB (always do this to ensure sync)
            try:
                now = datetime.utcnow()
                metadata = {
                    "organization_id": organization_id,
                    "user_id": user_id,
                    "file_name": file_name,
                    "file_path": file_path,
                    "file_size_bytes": len(file_content) if file_content else 0,
                    "file_type": os.path.splitext(file_name)[1].lower(),
                    "status": "processed",
                    "created_at": now.isoformat(),
                    "updated_at": now.isoformat(),
                    "processed_at": now.isoformat(),
                }
                await self.embedding_service.store_rate_sheet(
                    rate_sheet_id=rate_sheet_id,
                    rate_sheet_data=extracted_data,
                    parsed_data=parsed_data,
                    metadata=metadata
                )
                logger.info(f"✅ Stored/Updated ChromaDB embeddings for {rate_sheet_id}")
            except Exception as e:
                logger.warning(f"⚠️ ChromaDB storage failed (non-critical): {e}")
            
            return {
                "id": rate_sheet_id,
                "status": "processed",
                "file_name": file_name,
                "carrier_name": extracted_data.get("carrier_name"),
                "routes_count": routes_count,
                "message": f"Successfully reprocessed with {routes_count} routes extracted"
            }
            
        except Exception as e:
            logger.error(f"❌ Error reprocessing rate sheet {rate_sheet_id}: {e}", exc_info=True)
            
            # Update status to failed
            try:
                async with AsyncSessionLocal() as session:
                    result = await session.execute(
                        select(RateSheetStructuredData).where(
                            RateSheetStructuredData.rate_sheet_id == rate_sheet_id
                        )
                    )
                    record = result.scalar_one_or_none()
                    if record:
                        record.status = 'failed'
                        record.processing_error = str(e)[:500]
                        await session.commit()
            except Exception:
                pass
            
            return {
                "id": rate_sheet_id,
                "status": "failed",
                "error": str(e)
            }
    
    async def reprocess_all_rate_sheets(
        self,
        organization_id: int
    ) -> Dict[str, Any]:
        """
        Reprocess all rate sheets for an organization.
        
        This will:
        1. Get all rate sheets from PostgreSQL
        2. Re-run AI extraction on each file
        3. Update the normalized tables
        
        Returns:
            Summary of reprocessing results
        """
        from app.core.database import AsyncSessionLocal
        from app.models import RateSheetStructuredData
        from sqlalchemy import select
        
        logger.info(f"🔄 Reprocessing ALL rate sheets for org {organization_id}")
        
        results = {
            "total": 0,
            "success": 0,
            "failed": 0,
            "skipped": 0,
            "details": []
        }
        
        try:
            # Get all rate sheets for this organization
            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(RateSheetStructuredData).where(
                        RateSheetStructuredData.organization_id == organization_id
                    )
                )
                rate_sheets = result.scalars().all()
                results["total"] = len(rate_sheets)
            
            logger.info(f"📋 Found {len(rate_sheets)} rate sheets to reprocess")
            
            # Reprocess each one
            for rs in rate_sheets:
                try:
                    reprocess_result = await self.reprocess_rate_sheet(
                        rate_sheet_id=rs.rate_sheet_id,
                        organization_id=organization_id
                    )
                    
                    if reprocess_result and reprocess_result.get("status") == "processed":
                        results["success"] += 1
                        results["details"].append({
                            "rate_sheet_id": rs.rate_sheet_id,
                            "file_name": rs.file_name,
                            "status": "success",
                            "routes_count": reprocess_result.get("routes_count", 0)
                        })
                    elif reprocess_result and "File not found" in reprocess_result.get("error", ""):
                        results["skipped"] += 1
                        results["details"].append({
                            "rate_sheet_id": rs.rate_sheet_id,
                            "file_name": rs.file_name,
                            "status": "skipped",
                            "reason": "File not found"
                        })
                    else:
                        results["failed"] += 1
                        results["details"].append({
                            "rate_sheet_id": rs.rate_sheet_id,
                            "file_name": rs.file_name,
                            "status": "failed",
                            "error": reprocess_result.get("error", "Unknown error") if reprocess_result else "No result"
                        })
                        
                except Exception as e:
                    results["failed"] += 1
                    results["details"].append({
                        "rate_sheet_id": rs.rate_sheet_id,
                        "file_name": rs.file_name,
                        "status": "failed",
                        "error": str(e)
                    })
            
            logger.info(f"✅ Reprocessing complete: {results['success']} success, {results['failed']} failed, {results['skipped']} skipped")
            return results
            
        except Exception as e:
            logger.error(f"❌ Error reprocessing all rate sheets: {e}", exc_info=True)
            results["error"] = str(e)
            return results
