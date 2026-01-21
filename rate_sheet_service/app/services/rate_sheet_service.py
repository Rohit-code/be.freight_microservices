"""Rate Sheet Service - stores all data in ChromaDB with BGE embeddings (same as email service)"""
from typing import List, Dict, Any, Optional
from datetime import datetime
import os
import uuid
import logging
import numpy as np

from app.services.excel_parser import ExcelParser
from app.services.ai_analyzer import AIAnalyzer
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
    """Main service for rate sheet operations - stores everything in ChromaDB (like email service)"""
    
    def __init__(self):
        self.excel_parser = ExcelParser()
        self.ai_analyzer = AIAnalyzer()
        self.embedding_service = EmbeddingService()
        self.rerank_service = RerankService()
        self.upload_dir = settings.UPLOAD_DIR
        os.makedirs(self.upload_dir, exist_ok=True)
    
    async def upload_rate_sheet(
        self,
        file_content: bytes,
        file_name: str,
        organization_id: int,
        user_id: int
    ) -> Dict[str, Any]:
        """
        Upload and process a rate sheet file - stores in ChromaDB with BGE embeddings
        
        Args:
            file_content: File content bytes
            file_name: Original file name
            organization_id: Organization ID
            user_id: User ID who uploaded
        
        Returns:
            Dictionary with rate sheet data (stored in ChromaDB)
        """
        # Save file
        file_path = await self._save_file(file_content, file_name, organization_id)
        file_size = len(file_content)
        file_ext = os.path.splitext(file_name)[1].lower()
        
        # Generate unique ID
        rate_sheet_id = str(uuid.uuid4())
        now = datetime.utcnow().isoformat()
        
        try:
            # Parse Excel file
            parsed_data = self.excel_parser.parse_file(file_path)
            
            # Get existing rate sheets for relationship detection
            existing_rate_sheets = await self._get_recent_rate_sheets(organization_id, limit=10)
            
            # AI Analysis
            ai_analysis = await self.ai_analyzer.analyze_rate_sheet(
                parsed_data=parsed_data,
                file_name=file_name,
                existing_rate_sheets=existing_rate_sheets
            )
            
            # Prepare metadata for ChromaDB storage
            metadata = {
                "organization_id": organization_id,
                "user_id": user_id,
                "file_name": file_name,
                "file_path": file_path,
                "file_size_bytes": file_size,
                "file_type": file_ext,
                "status": "processed",
                "created_at": now,
                "updated_at": now,
                "processed_at": now,
            }
            
            # Store in ChromaDB with BGE embeddings (same pattern as email service)
            await self.embedding_service.store_rate_sheet(
                rate_sheet_id=rate_sheet_id,
                rate_sheet_data=ai_analysis,
                parsed_data=parsed_data,
                metadata=metadata
            )
            
            # Convert numpy types to native Python types for JSON serialization
            # Convert ai_analysis and parsed_data to ensure no numpy types
            converted_ai_analysis = convert_numpy_types(ai_analysis)
            converted_parsed_data = convert_numpy_types(parsed_data)
            
            response_data = {
                "id": rate_sheet_id,
                **metadata,
                **converted_ai_analysis,
                "parsed_data": converted_parsed_data  # Include parsed data for reference
            }
            
            # Final conversion to ensure all values are JSON serializable
            return convert_numpy_types(response_data)
        
        except Exception as e:
            logger.error(f"Error processing rate sheet {rate_sheet_id}: {e}")
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
                    "processing_error": str(e),
                    "created_at": now,
                    "updated_at": now,
                }
                await self.embedding_service.store_rate_sheet(
                    rate_sheet_id=rate_sheet_id,
                    rate_sheet_data={"error": str(e)},
                    parsed_data={},
                    metadata=failed_metadata
                )
            except Exception as store_error:
                logger.error(f"Error storing failed rate sheet: {store_error}")
            
            raise
    
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
            # Build search query
            search_query = query or "rate sheet"
            
            # Add filters to query if provided
            if carrier_name:
                search_query += f" carrier {carrier_name}"
            if origin_code:
                search_query += f" origin {origin_code}"
            if destination_code:
                search_query += f" destination {destination_code}"
            if container_type:
                search_query += f" container {container_type}"
            
            # Build filters
            filters = {}
            if carrier_name:
                filters["carrier_name"] = carrier_name
            
            # Stage 1: Vector search - get top 20 results
            logger.info(f"Stage 1: Vector search for query: '{query}'")
            vector_results = await self.embedding_service.search_rate_sheets(
                query=search_query,
                organization_id=organization_id,
                limit=20,  # Get top 20 for re-ranking
                filters=filters
            )
            
            if not vector_results:
                logger.info("No results found in vector search")
                return []
            
            # Format results with detailed matching data from sheets
            formatted_results = []
            query_lower = query.lower() if query else ""
            
            for result in vector_results:
                metadata = result.get("metadata", {})
                document = result.get("document", "")
                
                # Apply additional filters
                if origin_code and origin_code.lower() not in document.lower():
                    continue
                if destination_code and destination_code.lower() not in document.lower():
                    continue
                if container_type and container_type.lower() not in document.lower():
                    continue
                
                # Extract matching rows/data from the full document
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
                    "document": document,  # Full document for re-ranking
                    "document_preview": document[:1000],  # Preview
                    "matching_data": matching_data  # Specific matching rows/sections
                })
            
            if not formatted_results:
                logger.info("No results after filtering")
                return []
            
            # Stage 2: OpenAI re-ranking - get top 3 most relevant
            logger.info(f"Stage 2: Re-ranking {len(formatted_results)} results with OpenAI")
            top_results = await self.rerank_service.rerank_results(
                query=query or search_query,
                results=formatted_results,
                top_k=3
            )
            
            # Stage 3: Generate direct answer from the top results
            logger.info(f"Stage 3: Generating direct answer from top {len(top_results)} results")
            ai_answer = await self.rerank_service.generate_answer(
                query=query or search_query,
                results=top_results
            )
            
            # Each result now has its own individual ai_reasoning explaining why it's ranked in that position
            logger.info(f"Re-ranking complete. Returning top {len(top_results)} results with individual reasoning and AI answer")
            
            return {
                "answer": ai_answer,
                "results": top_results,
                "total_found": len(formatted_results),
                "total_returned": len(top_results)
            }
        
        except Exception as e:
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
        
        query_terms = query.split()
        query_terms_lower = [term.lower() for term in query_terms]
        
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
        """Delete rate sheet from ChromaDB"""
        try:
            import httpx
            
            # Verify ownership first
            rate_sheet = await self.get_rate_sheet(rate_sheet_id, organization_id)
            if not rate_sheet:
                return False
            
            # Delete from ChromaDB
            from app.services.embedding_service import RATE_SHEETS_COLLECTION
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.delete(
                    f"{settings.VECTOR_DB_SERVICE_URL}/api/vector/collections/{RATE_SHEETS_COLLECTION}/documents/{rate_sheet_id}"
                )
                
                if response.status_code == 200:
                    logger.info(f"Deleted rate sheet {rate_sheet_id}")
                    return True
                else:
                    logger.error(f"Failed to delete rate sheet: {response.text}")
                    return False
        
        except Exception as e:
            logger.error(f"Error deleting rate sheet: {e}")
            return False
