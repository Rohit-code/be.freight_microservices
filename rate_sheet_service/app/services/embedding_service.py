import httpx
import logging
import json
import asyncio
from typing import List, Dict, Any, Optional
from app.core.config import settings

logger = logging.getLogger(__name__)

# Collection name for rate sheets in vector DB (same as emails pattern)
RATE_SHEETS_COLLECTION = "rate_sheets"


class EmbeddingService:
    """Service for storing rate sheets in ChromaDB with BGE embeddings (same as email service)"""
    
    def __init__(self):
        self.vector_db_service_url = settings.VECTOR_DB_SERVICE_URL
    
    async def ensure_collection_exists(self):
        """Ensure the rate_sheets collection exists in vector DB"""
        max_retries = 3
        timeout_seconds = 60.0  # Increased timeout for collection creation
        
        for attempt in range(max_retries):
            try:
                async with httpx.AsyncClient(timeout=timeout_seconds) as client:
                    # Try to create collection (will return existing if already exists)
                    response = await client.post(
                        f"{self.vector_db_service_url}/api/vector/collections",
                        json={"name": RATE_SHEETS_COLLECTION},
                        timeout=timeout_seconds
                    )
                    if response.status_code in [200, 201]:
                        logger.info(f"✅ Collection '{RATE_SHEETS_COLLECTION}' exists/created")
                        return True
                    else:
                        logger.warning(f"Unexpected status code {response.status_code} when ensuring collection")
                        if attempt < max_retries - 1:
                            await asyncio.sleep(2)
                            continue
                        return False
            except httpx.ReadTimeout as e:
                if attempt < max_retries - 1:
                    logger.warning(f"⚠️ Timeout ensuring collection exists (attempt {attempt + 1}/{max_retries}), retrying...")
                    await asyncio.sleep(3)  # Wait 3 seconds before retry
                    continue
                else:
                    logger.error(f"❌ Max retries reached. Failed to ensure collection exists after {max_retries} attempts")
                    return False
            except Exception as e:
                import traceback
                error_details = str(e) if str(e) else repr(e)
                logger.error(f"Error ensuring collection exists: {error_details}", exc_info=True)
                if attempt < max_retries - 1:
                    await asyncio.sleep(2)
                    continue
                return False
        
        return False
    
    def _build_semantic_content(self, rate_sheet_data: Dict[str, Any], parsed_data: Dict[str, Any]) -> str:
        """
        Build COMPLETE content for vector storage (ChromaDB).
        
        STORES EVERYTHING:
        - ALL routes with ALL pricing data (AI-extracted, structured)
        - ENTIRE sheet text (from Pandas, for semantic search)
        - Carrier information
        - Validity dates
        - Transit times
        - Free detention
        - Remarks and notes
        
        This ensures semantic search can find ANY data in the rate sheet.
        BGE embeddings (BAAI/bge-base-en-v1.5) will index everything.
        """
        parts = []
        
        # ========== AI-EXTRACTED STRUCTURED DATA ==========
        parts.append("=== AI-EXTRACTED STRUCTURED DATA ===")
        
        # ========== METADATA ==========
        parts.append("=== RATE SHEET METADATA ===")
        parts.append(f"File: {rate_sheet_data.get('file_name', 'Unknown')}")
        parts.append(f"Carrier: {rate_sheet_data.get('carrier_name', 'Unknown')}")
        parts.append(f"Type: {rate_sheet_data.get('rate_sheet_type', 'ocean_freight')}")
        
        # Validity (human-readable, useful for semantic search)
        validity = rate_sheet_data.get('validity', {})
        if validity:
            parts.append(f"Valid From: {validity.get('valid_from', 'N/A')}")
            parts.append(f"Valid To: {validity.get('valid_to', 'N/A')}")
        
        parts.append("")
        
        # ========== ALL ROUTES WITH ALL PRICING ==========
        routes = rate_sheet_data.get("routes", [])
        
        if routes:
            # Summary for quick reference
            origins = set()
            destinations = set()
            for route in routes:
                origins.add(route.get('origin_port', 'N/A'))
                destinations.add(route.get('destination_port', 'N/A'))
            
            parts.append("=== ROUTE SUMMARY ===")
            parts.append(f"Total Routes: {len(routes)}")
            parts.append(f"Origin Ports: {', '.join(sorted(origins))}")
            parts.append(f"Destination Ports: {', '.join(sorted(destinations))}")
            parts.append("")
            
            # ========== COMPLETE ROUTE DETAILS ==========
            parts.append("=== ALL ROUTES AND PRICING ===")
            
            for idx, route in enumerate(routes, 1):
                origin = route.get('origin_port', 'N/A')
                dest = route.get('destination_port', 'N/A')
                service = route.get('service_type', 'FCL')
                routing = route.get('routing', 'N/A')
                transit_days = route.get('transit_time_days')
                transit_text = route.get('transit_time_text', '')
                free_detention_days = route.get('free_detention_days')
                free_detention_text = route.get('free_detention_text', '')
                remarks = route.get('remarks', '')
                
                # Route header
                parts.append(f"\nRoute {idx}: {origin} to {dest}")
                parts.append(f"  Service: {service}")
                if routing and routing != 'N/A':
                    parts.append(f"  Routing: {routing}")
                if transit_days:
                    parts.append(f"  Transit Time: {transit_days} days")
                elif transit_text:
                    parts.append(f"  Transit Time: {transit_text}")
                if free_detention_days:
                    parts.append(f"  Free Detention: {free_detention_days} days")
                elif free_detention_text:
                    parts.append(f"  Free Detention: {free_detention_text}")
                
                # ALL pricing tiers - no truncation
                pricing_tiers = route.get("pricing_tiers", [])
                if pricing_tiers:
                    parts.append(f"  Pricing:")
                    for tier in pricing_tiers:
                        container_type = tier.get('container_type', 'N/A')
                        base_rate = tier.get('base_rate', 'N/A')
                        currency = tier.get('currency', 'USD')
                        vgm_max = tier.get('vgm_max_weight_mt')
                        
                        price_line = f"    - {container_type}: {currency} {base_rate}"
                        if vgm_max:
                            price_line += f" (VGM up to {vgm_max} MT)"
                        parts.append(price_line)
                        
                        # Include surcharges if present (handle None)
                        surcharges = tier.get('surcharges') or []
                        if surcharges:
                            for surcharge in surcharges:
                                if isinstance(surcharge, dict):
                                    surcharge_type = surcharge.get('surcharge_type', '')
                                    surcharge_amount = surcharge.get('amount', '')
                                    if surcharge_type and surcharge_amount:
                                        parts.append(f"      + {surcharge_type}: {currency} {surcharge_amount}")
                
                # Remarks
                if remarks:
                    parts.append(f"  Remarks: {remarks}")
        
        # Relationships reasoning (semantic)
        relationships = rate_sheet_data.get("relationships", {})
        if relationships.get("is_related"):
            parts.append("")
            parts.append("=== Relationships ===")
            parts.append(f"Type: {relationships.get('relationship_type', '')}")
            if relationships.get('reasoning'):
                parts.append(f"Reasoning: {relationships.get('reasoning')}")
        
        # AI Analysis Notes (semantic)
        if rate_sheet_data.get("extraction_notes"):
            parts.append("")
            parts.append("=== Notes ===")
            parts.append(rate_sheet_data.get("extraction_notes", ""))
        
        # Extract text-heavy content from raw Excel (policies, clauses, notes)
        # Skip numeric columns, focus on text
        if parsed_data and parsed_data.get("sheets"):
            text_content = self._extract_text_content(parsed_data)
            if text_content:
                parts.append("")
                parts.append("=== Additional Content ===")
                parts.append(text_content)
        
        # ========== ENTIRE SHEET TEXT (from Pandas) ==========
        # This ensures semantic search can find ANY data, even if AI extraction missed something
        full_sheet_text = rate_sheet_data.get("_full_sheet_text")
        if full_sheet_text:
            parts.append("")
            parts.append("=== COMPLETE RAW SHEET DATA (for comprehensive semantic search) ===")
            parts.append(full_sheet_text)
            logger.info(f"📄 [EMBEDDING] Including full sheet text: {len(full_sheet_text)} chars")
        
        return "\n".join(parts)
    
    def _extract_text_content(self, parsed_data: Dict[str, Any]) -> str:
        """
        Extract text-heavy content from parsed Excel data.
        Focuses on columns likely to contain policies, notes, clauses.
        """
        text_parts = []
        text_keywords = ['note', 'remark', 'clause', 'term', 'condition', 'policy', 
                        'exception', 'description', 'comment', 'info', 'detail']
        
        for sheet in parsed_data.get("sheets", []):
            sheet_data = sheet.get("data", [])
            columns = sheet.get("columns", [])
            
            # Find text-heavy columns
            for col in columns:
                col_lower = str(col).lower()
                if any(kw in col_lower for kw in text_keywords):
                    # Extract values from this column
                    for row in sheet_data[:50]:  # Limit rows
                        val = row.get(col)
                        if val and isinstance(val, str) and len(val) > 20:
                            text_parts.append(val)
        
        return "\n".join(text_parts[:20])  # Limit to 20 text entries
    
    def _build_raw_content(self, rate_sheet_data: Dict[str, Any], parsed_data: Dict[str, Any]) -> str:
        """
        Build COMPLETE raw content from BOTH AI-extracted data AND original parsed Excel data.
        
        This ensures ChromaDB has EVERYTHING:
        1. AI-extracted structured data (routes, pricing) - for semantic search
        2. Complete raw Excel data (all rows, all columns) - for complete sheet reconstruction
        
        This is the FULL sheet content, not just what AI extracted.
        """
        parts = []
        
        # ========== PART 1: AI-EXTRACTED STRUCTURED DATA ==========
        # This is what AI understood from the sheet
        parts.append("=== AI-EXTRACTED STRUCTURED DATA ===")
        parts.append(self._build_semantic_content(rate_sheet_data, parsed_data))
        parts.append("")
        
        # ========== PART 2: COMPLETE RAW EXCEL DATA ==========
        # This is the FULL original sheet - everything that was in the Excel file
        parts.append("=== COMPLETE RAW EXCEL SHEET DATA ===")
        
        if parsed_data and parsed_data.get("sheets"):
            parts.append(f"File Type: {parsed_data.get('file_type', 'Unknown')}")
            
            # Excel metadata
            excel_metadata = parsed_data.get("metadata", {})
            if excel_metadata:
                parts.append("\nExcel File Properties:")
                if excel_metadata.get("title"):
                    parts.append(f"  Title: {excel_metadata.get('title')}")
                if excel_metadata.get("author"):
                    parts.append(f"  Author: {excel_metadata.get('author')}")
                if excel_metadata.get("created"):
                    parts.append(f"  Created: {excel_metadata.get('created')}")
                if excel_metadata.get("modified"):
                    parts.append(f"  Modified: {excel_metadata.get('modified')}")
            
            # ALL sheets with ALL data
            for sheet in parsed_data.get("sheets", []):
                parts.append("")
                parts.append(f"--- Sheet: {sheet.get('name', 'Unknown')} ---")
                parts.append(f"Total Rows: {sheet.get('rows', 0)}, Total Columns: {sheet.get('columns_count', 0)}")
                
                # Column headers
                columns = sheet.get("columns", [])
                if columns:
                    parts.append(f"Columns: {', '.join(str(col) for col in columns)}")
                
                # ALL ROWS - no truncation (complete sheet)
                sheet_data = sheet.get("data", [])
                if sheet_data:
                    parts.append("\nComplete Sheet Data (All Rows):")
                    for idx, row in enumerate(sheet_data, 1):
                        # Convert row to readable format
                        row_values = []
                        for col_idx, col_name in enumerate(columns):
                            if col_idx < len(row):
                                cell_value = row[col_idx] if isinstance(row, (list, tuple)) else row.get(col_name, "")
                                if cell_value is not None and str(cell_value).strip():
                                    row_values.append(f"{col_name}: {cell_value}")
                        
                        if row_values:
                            parts.append(f"  Row {idx}: {' | '.join(row_values)}")
                
                # Merged cells info (if any)
                merged_cells = sheet.get("merged_cells", [])
                if merged_cells:
                    parts.append(f"\nMerged Cells: {', '.join(merged_cells[:20])}")  # First 20
        
        return "\n".join(parts)
    
    async def store_rate_sheet(
        self,
        rate_sheet_id: str,
        rate_sheet_data: Dict[str, Any],
        parsed_data: Dict[str, Any],
        metadata: Dict[str, Any]
    ) -> str:
        """
        Store rate sheet in ChromaDB with BGE embeddings (same pattern as email service)
        
        Args:
            rate_sheet_id: Unique ID for the rate sheet
            rate_sheet_data: AI-analyzed structured data
            parsed_data: Raw parsed Excel data
            metadata: Additional metadata
        
        Returns:
            Document ID from vector DB
        """
        try:
            await self.ensure_collection_exists()
            
            # Build full raw content (like email service stores full raw email)
            raw_content = self._build_raw_content(rate_sheet_data, parsed_data)
            
            # Prepare metadata (all rate sheet fields)
            full_metadata = {
                "id": rate_sheet_id,
                "type": "rate_sheet",
                "organization_id": str(metadata.get("organization_id", "")),
                "user_id": str(metadata.get("user_id", "")),
                "file_name": metadata.get("file_name", ""),
                "file_path": metadata.get("file_path", ""),
                "file_size_bytes": str(metadata.get("file_size_bytes", 0)),
                "file_type": metadata.get("file_type", ""),
                "carrier_name": rate_sheet_data.get("carrier_name", ""),
                "title": rate_sheet_data.get("title", ""),
                "rate_sheet_type": rate_sheet_data.get("rate_sheet_type", "unknown"),
                "status": metadata.get("status", "processed"),
                "valid_from": rate_sheet_data.get("validity", {}).get("valid_from", ""),
                "valid_to": rate_sheet_data.get("validity", {}).get("valid_to", ""),
                "effective_date": rate_sheet_data.get("validity", {}).get("effective_date", ""),
                "confidence_score": str(rate_sheet_data.get("confidence_score", 0)),
                "is_related": str(rate_sheet_data.get("relationships", {}).get("is_related", False)),
                "relationship_type": rate_sheet_data.get("relationships", {}).get("relationship_type", ""),
                "detected_format": rate_sheet_data.get("detected_format", ""),
                "created_at": metadata.get("created_at", ""),
                "updated_at": metadata.get("updated_at", ""),
                "processed_at": metadata.get("processed_at", ""),
            }
            
            # Store in vector DB (same pattern as email service)
            # Use longer timeout for large documents with COMPLETE data and implement retry logic
            max_retries = 3
            timeout_seconds = 180.0  # 3 minutes for large documents with all routes/pricing
            
            # Log content size for monitoring
            content_size = len(raw_content)
            logger.info(f"Storing rate sheet {rate_sheet_id} in ChromaDB: {content_size} chars, {len(rate_sheet_data.get('routes', []))} routes")
            
            for attempt in range(max_retries):
                try:
                    async with httpx.AsyncClient(timeout=timeout_seconds) as client:
                        response = await client.post(
                            f"{self.vector_db_service_url}/api/vector/collections/{RATE_SHEETS_COLLECTION}/documents",
                            json={
                                "documents": [raw_content],  # COMPLETE content with all routes + pricing + BGE embeddings
                                "metadatas": [full_metadata],  # All metadata fields
                                "ids": [rate_sheet_id]
                            },
                            timeout=timeout_seconds
                        )
                        
                        if response.status_code == 200:
                            logger.info(f"✅ Stored rate sheet {rate_sheet_id} in ChromaDB ({content_size} chars, BGE embeddings)")
                            return rate_sheet_id
                        else:
                            logger.error(f"Failed to store rate sheet: {response.text}")
                            if attempt < max_retries - 1:
                                logger.info(f"Retrying... (attempt {attempt + 2}/{max_retries})")
                                await asyncio.sleep(3)  # Wait 3 seconds before retry
                                continue
                            raise Exception(f"Failed to store rate sheet: {response.text}")
                            
                except httpx.ReadTimeout as e:
                    if attempt < max_retries - 1:
                        logger.warning(f"⚠️ Timeout storing rate sheet (attempt {attempt + 1}/{max_retries}), retrying with longer wait...")
                        await asyncio.sleep(5)  # Wait 5 seconds before retry on timeout
                        continue
                    else:
                        logger.error(f"❌ Max retries reached. Failed to store rate sheet after {max_retries} attempts ({content_size} chars)")
                        raise Exception(f"Failed to store rate sheet in ChromaDB: ReadTimeout after {max_retries} attempts") from e
        
        except Exception as e:
            import traceback
            error_details = str(e) if str(e) else repr(e)
            logger.error(f"Error storing rate sheet in ChromaDB: {error_details}", exc_info=True)
            raise Exception(f"Failed to store rate sheet in ChromaDB: {error_details}") from e
    
    async def search_rate_sheets(
        self,
        query: str,
        organization_id: int,  # REQUIRED - Multi-tenant isolation
        limit: int = 10,
        filters: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """
        Search rate sheets using semantic search (BGE embeddings)
        
        IMPORTANT: This enforces organization-level data isolation (multi-tenant SaaS).
        Each organization can ONLY see their own rate sheets.
        
        Args:
            query: Search query text
            organization_id: Organization ID (REQUIRED for data isolation)
            limit: Maximum number of results
            filters: Additional filters
        
        Returns:
            List of rate sheets with similarity scores (filtered by organization_id)
        """
        try:
            # Validate organization_id is provided
            if not organization_id:
                logger.error("organization_id is required for rate sheet search (multi-tenant isolation)")
                raise ValueError("organization_id is required for data isolation")
            
            await self.ensure_collection_exists()
            
            async with httpx.AsyncClient(timeout=30.0) as client:
                # Query ChromaDB (currently doesn't support where filters, so we filter post-query)
                # Note: Vector DB service currently uses post-query filtering
                # Future enhancement: Add where filters directly to vector DB query for better performance
                # Optimize: Request only what we need (limit) instead of limit * 3 to reduce computation
                # Only request more if we have filters that might filter out results
                n_results = limit * 3 if filters else limit
                response = await client.post(
                    f"{self.vector_db_service_url}/api/vector/collections/{RATE_SHEETS_COLLECTION}/query",
                    json={
                        "query_texts": [query],
                        "n_results": n_results
                    },
                    timeout=30.0
                )
                response.raise_for_status()
                result = response.json()
                
                # Format results similar to email service
                results = result.get("results", {})
                ids = results.get("ids", [[]])[0]
                documents = results.get("documents", [[]])[0]
                metadatas = results.get("metadatas", [[]])[0]
                distances = results.get("distances", [[]])[0]
                
                # CRITICAL: Filter by organization_id FIRST for multi-tenant isolation
                # This ensures users can ONLY see rate sheets from their own organization
                filtered_results = []
                for doc_id, doc, meta, dist in zip(ids, documents, metadatas, distances):
                    # SECURITY: Enforce organization isolation - skip if organization_id doesn't match
                    meta_org_id = meta.get("organization_id")
                    if meta_org_id != str(organization_id):
                        logger.debug(f"Skipping rate sheet {doc_id} - organization_id mismatch: {meta_org_id} != {organization_id}")
                        continue
                    
                    # Apply additional filters if provided
                    if filters:
                        skip = False
                        for key, value in filters.items():
                            if meta.get(key) != str(value):
                                skip = True
                                break
                        if skip:
                            continue
                    
                    filtered_results.append({
                        "id": doc_id,
                        "document": doc,
                        "metadata": meta,
                        "distance": dist,
                        "similarity": 1 - dist  # Convert distance to similarity
                    })
                    
                    # Stop once we have enough results
                    if len(filtered_results) >= limit:
                        break
                
                logger.info(f"Search returned {len(filtered_results)} rate sheets for organization_id={organization_id} (filtered from {len(ids)} total results)")
                return filtered_results
        except Exception as e:
            logger.error(f"Error searching rate sheets for organization_id={organization_id}: {e}")
            return []
    
    async def get_rate_sheet_by_id(self, rate_sheet_id: str) -> Optional[Dict[str, Any]]:
        """Get rate sheet by ID from ChromaDB"""
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(
                    f"{self.vector_db_service_url}/api/vector/collections/{RATE_SHEETS_COLLECTION}/documents/{rate_sheet_id}",
                    timeout=30.0
                )
                if response.status_code == 200:
                    result = response.json()
                    return {
                        "id": result.get("id"),
                        "document": result.get("document"),  # Full raw content
                        "metadata": result.get("metadata")
                    }
                return None
        except Exception as e:
            logger.error(f"Error getting rate sheet: {e}")
            return None
