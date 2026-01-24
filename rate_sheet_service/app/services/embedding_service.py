import httpx
import logging
import json
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
        try:
            async with httpx.AsyncClient() as client:
                # Try to create collection (will return existing if already exists)
                response = await client.post(
                    f"{self.vector_db_service_url}/api/vector/collections",
                    json={"name": RATE_SHEETS_COLLECTION},
                    timeout=30.0
                )
                return response.status_code in [200, 201]
        except Exception as e:
            logger.error(f"Error ensuring collection exists: {e}")
            return False
    
    def _build_raw_content(self, rate_sheet_data: Dict[str, Any], parsed_data: Dict[str, Any]) -> str:
        """
        Build full raw content from rate sheet data for storage in ChromaDB
        Similar to how emails store full raw content + embeddings
        
        This stores BOTH:
        1. AI-analyzed structured data (routes, pricing tiers, surcharges, etc.)
        2. Raw parsed Excel data (all sheets, columns, rows, merged cells)
        
        This ensures complete embedding coverage - both structured extraction and original data
        """
        parts = []
        
        # File Information
        parts.append(f"Rate Sheet File: {rate_sheet_data.get('file_name', 'Unknown')}")
        parts.append(f"Carrier: {rate_sheet_data.get('carrier_name', 'Unknown')}")
        parts.append(f"Type: {rate_sheet_data.get('rate_sheet_type', 'unknown')}")
        parts.append(f"Title: {rate_sheet_data.get('title', '')}")
        
        # Validity
        validity = rate_sheet_data.get('validity', {})
        if validity.get('valid_from'):
            parts.append(f"Valid From: {validity['valid_from']}")
        if validity.get('valid_to'):
            parts.append(f"Valid To: {validity['valid_to']}")
        if validity.get('effective_date'):
            parts.append(f"Effective Date: {validity['effective_date']}")
        
        parts.append("")  # Separator
        
        # Routes and Pricing (full structured data)
        routes = rate_sheet_data.get("routes", [])
        for idx, route in enumerate(routes, 1):
            parts.append(f"=== Route {idx} ===")
            parts.append(f"Origin Port: {route.get('origin_port', '')}")
            parts.append(f"Origin Country: {route.get('origin_country', '')}")
            parts.append(f"Origin City: {route.get('origin_city', '')}")
            parts.append(f"Origin Code: {route.get('origin_code', '')}")
            parts.append(f"Destination Port: {route.get('destination_port', '')}")
            parts.append(f"Destination Country: {route.get('destination_country', '')}")
            parts.append(f"Destination City: {route.get('destination_city', '')}")
            parts.append(f"Destination Code: {route.get('destination_code', '')}")
            parts.append(f"Routing: {route.get('routing', '')}")
            parts.append(f"Transit Time: {route.get('transit_time_text', '')} ({route.get('transit_time_days', '')} days)")
            parts.append(f"Service Type: {route.get('service_type', '')}")
            parts.append(f"Direct: {route.get('is_direct', False)}")
            parts.append(f"Free Detention: {route.get('free_detention_text', '')} ({route.get('free_detention_days', '')} days)")
            parts.append(f"Remarks: {route.get('remarks', '')}")
            
            # Pricing Tiers
            pricing_tiers = route.get("pricing_tiers", [])
            for tier_idx, tier in enumerate(pricing_tiers, 1):
                parts.append(f"  --- Pricing Tier {tier_idx} ---")
                parts.append(f"  Container Type: {tier.get('container_type', '')}")
                parts.append(f"  Container Size: {tier.get('container_size', '')}")
                parts.append(f"  Container Height: {tier.get('container_height', '')}")
                parts.append(f"  Base Rate: {tier.get('base_rate', '')} {tier.get('currency', 'USD')}")
                if tier.get('min_weight_kg'):
                    parts.append(f"  Weight Range: {tier.get('min_weight_kg')} - {tier.get('max_weight_kg')} kg")
                if tier.get('vgm_min_weight_mt'):
                    parts.append(f"  VGM Range: {tier.get('vgm_min_weight_mt')} - {tier.get('vgm_max_weight_mt')} MT")
                if tier.get('minimum_charge'):
                    parts.append(f"  Minimum Charge: {tier.get('minimum_charge')} {tier.get('currency', 'USD')}")
                if tier.get('remarks'):
                    parts.append(f"  Remarks: {tier.get('remarks')}")
                
                # Surcharges
                surcharges = tier.get("surcharges", [])
                if surcharges:
                    parts.append(f"  Surcharges:")
                    for surcharge in surcharges:
                        surcharge_info = f"    - {surcharge.get('surcharge_type', '')}: "
                        if surcharge.get('is_percentage'):
                            surcharge_info += f"{surcharge.get('percentage_value', '')}%"
                        else:
                            surcharge_info += f"{surcharge.get('amount', '')} {surcharge.get('currency', '')}"
                        parts.append(surcharge_info)
                
                # Charges
                charges = tier.get("charges", [])
                if charges:
                    parts.append(f"  Charges:")
                    for charge in charges:
                        charge_info = f"    - {charge.get('charge_type', '')}: {charge.get('amount', '')} {charge.get('currency', '')}"
                        parts.append(charge_info)
            
            parts.append("")  # Route separator
        
        # Relationships
        relationships = rate_sheet_data.get("relationships", {})
        if relationships.get("is_related"):
            parts.append("=== Relationships ===")
            parts.append(f"Relationship Type: {relationships.get('relationship_type', '')}")
            parts.append(f"Related To: {', '.join(relationships.get('related_to_rate_sheets', []))}")
            parts.append(f"Reasoning: {relationships.get('reasoning', '')}")
        
        # AI Analysis Notes
        if rate_sheet_data.get("extraction_notes"):
            parts.append("")
            parts.append(f"=== Extraction Notes ===")
            parts.append(rate_sheet_data.get("extraction_notes", ""))
        
        # Raw Parsed Excel Data (for complete embedding - includes all original data)
        if parsed_data and parsed_data.get("sheets"):
            parts.append("")
            parts.append("=== Raw Excel Data ===")
            parts.append(f"File Type: {parsed_data.get('file_type', '')}")
            
            # Excel metadata
            excel_metadata = parsed_data.get("metadata", {})
            if excel_metadata:
                parts.append("Excel File Properties:")
                if excel_metadata.get("title"):
                    parts.append(f"  Title: {excel_metadata.get('title')}")
                if excel_metadata.get("author"):
                    parts.append(f"  Author: {excel_metadata.get('author')}")
                if excel_metadata.get("created"):
                    parts.append(f"  Created: {excel_metadata.get('created')}")
                if excel_metadata.get("modified"):
                    parts.append(f"  Modified: {excel_metadata.get('modified')}")
            
            # All sheets data
            for sheet in parsed_data.get("sheets", []):
                parts.append("")
                parts.append(f"--- Sheet: {sheet.get('name', 'Unknown')} ---")
                parts.append(f"Rows: {sheet.get('rows', 0)}, Columns: {sheet.get('columns_count', 0)}")
                
                # Column headers
                columns = sheet.get("columns", [])
                if columns:
                    parts.append(f"Columns: {', '.join(str(col) for col in columns)}")
                
                # Merged cells info
                merged_cells = sheet.get("merged_cells", [])
                if merged_cells:
                    parts.append(f"Merged Cells: {', '.join(merged_cells[:10])}")  # First 10
                
                # Sample data (all rows as text representation)
                sheet_data = sheet.get("data", [])
                if sheet_data:
                    parts.append("Data:")
                    # Include all rows (or limit to reasonable size for embedding)
                    max_rows_for_embedding = 100  # Limit to prevent huge embeddings
                    for idx, row in enumerate(sheet_data[:max_rows_for_embedding], 1):
                        row_str = " | ".join(f"{k}: {v}" for k, v in row.items() if v is not None and str(v).strip())
                        if row_str:
                            parts.append(f"  Row {idx}: {row_str}")
                    
                    if len(sheet_data) > max_rows_for_embedding:
                        parts.append(f"  ... ({len(sheet_data) - max_rows_for_embedding} more rows)")
                
                # Sample data per column (for reference)
                sample_data = sheet.get("sample_data", {})
                if sample_data:
                    parts.append("Column Samples:")
                    for col_name, col_info in list(sample_data.items())[:20]:  # First 20 columns
                        parts.append(f"  {col_name}: {col_info.get('dtype', '')}, "
                                   f"non-null: {col_info.get('non_null_count', 0)}, "
                                   f"sample: {col_info.get('sample_values', [])[:3]}")
        
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
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    f"{self.vector_db_service_url}/api/vector/collections/{RATE_SHEETS_COLLECTION}/documents",
                    json={
                        "documents": [raw_content],  # Full raw content for retrieval + embeddings
                        "metadatas": [full_metadata],  # All metadata fields
                        "ids": [rate_sheet_id]
                    },
                    timeout=60.0  # Longer timeout for embedding generation
                )
                
                if response.status_code == 200:
                    logger.info(f"Stored rate sheet {rate_sheet_id} in ChromaDB (raw content + BGE embeddings)")
                    return rate_sheet_id
                else:
                    logger.error(f"Failed to store rate sheet: {response.text}")
                    raise Exception(f"Failed to store rate sheet: {response.text}")
        
        except Exception as e:
            logger.error(f"Error storing rate sheet in ChromaDB: {e}")
            raise
    
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
