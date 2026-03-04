"""
Graph-Aware Rate Sheet Ingestion
Implements the new architecture: Structured First, Vector Second

NOTE: Vector storage is handled by EmbeddingService (not duplicated here).
This service ONLY handles graph relationship creation in ArangoDB.
"""
import logging
import httpx
from typing import Dict, Any, List, Optional
from datetime import datetime
from app.core.config import settings

logger = logging.getLogger(__name__)


class GraphAwareIngestion:
    """
    Handles graph-aware ingestion of rate sheets.
    
    Storage responsibilities:
    - PostgreSQL: Structured data (StructuredDataService)
    - ChromaDB: Semantic content (EmbeddingService) - NOT duplicated here
    - ArangoDB: Graph relationships (this service)
    """
    
    def __init__(self):
        self.graph_service_url = settings.KNOWLEDGE_GRAPH_SERVICE_URL
    
    async def ingest_rate_sheet(
        self,
        rate_sheet_id: str,
        organization_id: int,
        structured_data: Dict[str, Any],
        raw_content: str  # Kept for API compatibility, not used for vector storage
    ):
        """
        Ingest rate sheet graph relationships into ArangoDB.
        
        NOTE: Vector storage is handled by EmbeddingService (embedding_service.py).
        This service ONLY creates graph relationships to avoid duplicate storage.
        """
        try:
            carrier_name = structured_data.get("carrier_name", "")
            routes = structured_data.get("routes", [])
            validity = structured_data.get("validity", {})
            
            valid_from = None
            valid_to = None
            if validity:
                valid_from_str = validity.get("valid_from")
                valid_to_str = validity.get("valid_to")
                if valid_from_str:
                    valid_from = datetime.fromisoformat(valid_from_str)
                if valid_to_str:
                    valid_to = datetime.fromisoformat(valid_to_str)
            
            # Create graph relationships in ArangoDB
            # Vector storage is handled separately by EmbeddingService
            await self._create_graph_relationships(
                rate_sheet_id=rate_sheet_id,
                organization_id=organization_id,
                carrier_name=carrier_name,
                routes=routes,
                valid_from=valid_from,
                valid_to=valid_to
            )
            
            logger.info(f"✅ Graph ingestion complete for {rate_sheet_id}")
            
        except Exception as e:
            logger.error(f"Error in graph ingestion: {e}", exc_info=True)
            # Don't fail the upload if graph storage fails
            # Structured data in PostgreSQL is the critical path
    
    async def _create_graph_relationships(
        self,
        rate_sheet_id: str,
        organization_id: int,
        carrier_name: str,
        routes: List[Dict[str, Any]],
        valid_from: Optional[datetime],
        valid_to: Optional[datetime]
    ):
        """Create graph relationships in ArangoDB"""
        try:
            # Format routes for the graph service
            formatted_routes = []
            for route in routes:
                formatted_routes.append({
                    "origin_port": route.get("origin_port", route.get("origin", "")),
                    "destination_port": route.get("destination_port", route.get("destination", "")),
                    "container_type": route.get("container_type"),
                    "base_rate": route.get("base_rate", route.get("rate")),
                    "transit_time": route.get("transit_time")
                })
            
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{self.graph_service_url}/api/graph/rate-sheets/{rate_sheet_id}",
                    json={
                        "organization_id": organization_id,
                        "carrier_name": carrier_name or "Unknown",
                        "routes": formatted_routes,
                        "valid_from": valid_from.isoformat() if valid_from else None,
                        "valid_to": valid_to.isoformat() if valid_to else None
                    }
                )
                response.raise_for_status()
                logger.info(f"✅ Created graph relationships in ArangoDB for {rate_sheet_id}")
        except httpx.ConnectError as e:
            logger.warning(f"⚠️  Knowledge Graph Service not available (non-critical): {e}")
        except Exception as e:
            logger.warning(f"⚠️  Failed to create graph relationships (non-critical): {e}")
            # Non-critical - continue without graph
