"""
Agent Orchestrator Service
Coordinates SQL, Graph, and Vector retrieval engines based on query intent
"""
import asyncio
import logging
import httpx
from typing import Dict, Any, List, Optional
from datetime import datetime
from app.core.config import settings

logger = logging.getLogger(__name__)


class AgentOrchestrator:
    """Orchestrates multiple retrieval engines for intelligent query processing"""
    
    def __init__(self):
        self.rate_sheet_service_url = settings.RATE_SHEET_SERVICE_URL
        self.graph_service_url = settings.KNOWLEDGE_GRAPH_SERVICE_URL
        self.vector_service_url = settings.VECTOR_DB_SERVICE_URL
        self.intent_service_url = settings.INTENT_CLASSIFIER_SERVICE_URL
    
    async def orchestrate_query(
        self,
        organization_id: int,
        email_content: str,
        subject: Optional[str] = None,
        from_email: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Orchestrate query across multiple retrieval engines
        
        Flow:
        1. Classify intent
        2. Route to appropriate engines based on intent
        3. Combine results
        4. Return unified response
        """
        try:
            import time
            start_time = time.time()
            
            # Step 1: Classify intent
            print(f"\n⏱️ [ORCHESTRATOR] Starting orchestration at {start_time}")
            logger.info(f"⏱️ [ORCHESTRATOR] Starting orchestration")
            
            intent_result = await self._classify_intent(email_content, subject, from_email)
            intent_time = time.time() - start_time
            print(f"⏱️ [ORCHESTRATOR] Intent classification completed in {intent_time:.2f}s")
            logger.info(f"⏱️ [ORCHESTRATOR] Intent classification completed in {intent_time:.2f}s")
            
            # Step 2: Run SQL, Graph, Vector in parallel (latency reduction)
            intent_type = intent_result.get("intent", "")
            is_pricing_intent = intent_type in ["rate_inquiry", "rate_request", "quote_request", "pricing_inquiry"]
            entities = intent_result.get("entities", {})
            run_sql = intent_result.get("requires_structured_data", False) or is_pricing_intent
            run_graph = intent_result.get("requires_graph_traversal", False) or (bool(entities.get("origin_port") and entities.get("destination_port")))
            run_vector = intent_result.get("requires_vector_search", True) or is_pricing_intent
            
            async def _sql():
                return await self._sql_retrieval(organization_id=organization_id, entities=entities) if run_sql else []
            async def _graph():
                return await self._graph_retrieval(organization_id=organization_id, entities=entities) if run_graph else []
            async def _vector():
                return await self._vector_retrieval(organization_id=organization_id, query=email_content) if run_vector else []
            
            retrieval_start = time.time()
            sql_results, graph_results, vector_results = await asyncio.gather(_sql(), _graph(), _vector())
            retrieval_time = time.time() - retrieval_start
            print(f"⏱️ [ORCHESTRATOR] SQL+Graph+Vector (parallel) completed in {retrieval_time:.2f}s")
            logger.info(f"⏱️ [ORCHESTRATOR] Parallel retrieval: sql={len(sql_results)}, graph={len(graph_results)}, vector={len(vector_results)} in {retrieval_time:.2f}s")
            
            results = {
                "intent": intent_result,
                "sql_results": sql_results,
                "graph_results": graph_results,
                "vector_results": vector_results
            }
            
            # Step 3: Combine and rank results
            combined_results = self._combine_results(results)
            
            total_time = time.time() - start_time
            print(f"⏱️ [ORCHESTRATOR] Total orchestration completed in {total_time:.2f}s")
            logger.info(f"⏱️ [ORCHESTRATOR] Total orchestration completed in {total_time:.2f}s")
            
            return {
                "intent": intent_result,
                "results": combined_results,
                # Expose raw results for disagreement detection in Decision Engine
                "raw_results": {
                    "sql_results": results["sql_results"],
                    "graph_results": results["graph_results"],
                    "vector_results": results["vector_results"]
                },
                "engines_used": {
                    "sql": len(results["sql_results"]) > 0,
                    "graph": len(results["graph_results"]) > 0,
                    "vector": len(results["vector_results"]) > 0
                }
            }
            
        except Exception as e:
            logger.error(f"Error orchestrating query: {e}", exc_info=True)
            raise
    
    async def _classify_intent(
        self,
        email_content: str,
        subject: Optional[str],
        from_email: Optional[str]
    ) -> Dict[str, Any]:
        """Classify email intent"""
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{self.intent_service_url}/api/intent/classify",
                    json={
                        "email_content": email_content,
                        "subject": subject,
                        "from_email": from_email
                    }
                )
                response.raise_for_status()
                return response.json()
        except Exception as e:
            logger.error(f"Error classifying intent: {e}")
            # Fallback: assume rate inquiry
            return {
                "intent": "rate_inquiry",
                "confidence": 0.5,
                "entities": {},
                "query_type": "fuzzy_match",
                "requires_structured_data": True,
                "requires_vector_search": True,
                "requires_graph_traversal": False
            }
    
    async def _sql_retrieval(
        self,
        organization_id: int,
        entities: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """SQL retrieval for exact rates - tries both directions"""
        try:
            origin_port = entities.get("origin_port")
            destination_port = entities.get("destination_port")
            container_type = entities.get("container_type")
            
            all_routes = []
            
            async with httpx.AsyncClient(timeout=30.0) as client:
                # Query 1: As extracted (origin → destination)
                response = await client.post(
                    f"{self.rate_sheet_service_url}/api/rate-sheets/query-routes?organization_id={organization_id}",
                    json={
                        "origin_port": origin_port,
                        "destination_port": destination_port,
                        "container_type": container_type
                    }
                )
                response.raise_for_status()
                result = response.json()
                routes_forward = result.get("routes", [])
                all_routes.extend(routes_forward)
                
                # Query 2: Reverse direction (destination → origin)
                # Shipping rate sheets are often stored by seller's perspective
                # e.g., "Thailand export rates" = routes FROM Thailand
                if origin_port and destination_port:
                    response = await client.post(
                        f"{self.rate_sheet_service_url}/api/rate-sheets/query-routes?organization_id={organization_id}",
                        json={
                            "origin_port": destination_port,  # Swapped
                            "destination_port": origin_port,   # Swapped
                            "container_type": container_type
                        }
                    )
                    response.raise_for_status()
                    result = response.json()
                    routes_reverse = result.get("routes", [])
                    
                    # Mark reverse routes so they can be identified
                    for route in routes_reverse:
                        route["_reverse_direction"] = True
                        route["_original_query"] = f"{origin_port} → {destination_port}"
                    
                    all_routes.extend(routes_reverse)
                
                logger.info(f"SQL retrieval found {len(all_routes)} routes "
                           f"(forward: {len(routes_forward)}, reverse: {len(routes_reverse) if origin_port and destination_port else 0})")
                
            return all_routes
        except Exception as e:
            logger.error(f"Error in SQL retrieval: {e}")
            return []
    
    async def _graph_retrieval(
        self,
        organization_id: int,
        entities: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Graph traversal for lane logic and alternatives"""
        try:
            origin_port = entities.get("origin_port")
            destination_port = entities.get("destination_port")
            container_type = entities.get("container_type")
            
            if not origin_port or not destination_port:
                return []
            
            results = []
            
            # Find routes by lane
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(
                    f"{self.graph_service_url}/api/graph/routes/by-lane",
                    params={
                        "organization_id": organization_id,
                        "origin_port": origin_port,
                        "destination_port": destination_port,
                        "container_type": container_type
                    }
                )
                response.raise_for_status()
                lane_result = response.json()
                results.extend(lane_result.get("routes", []))
            
            # Find alternative routes (transshipment)
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(
                    f"{self.graph_service_url}/api/graph/routes/alternatives",
                    params={
                        "organization_id": organization_id,
                        "origin_port": origin_port,
                        "destination_port": destination_port,
                        "max_hops": 2
                    }
                )
                response.raise_for_status()
                alt_result = response.json()
                results.append({
                    "type": "alternatives",
                    "alternatives": alt_result.get("alternatives", [])
                })
            
            return results
        except Exception as e:
            logger.error(f"Error in graph retrieval: {e}")
            return []
    
    async def _vector_retrieval(
        self,
        organization_id: int,
        query: str
    ) -> List[Dict[str, Any]]:
        """
        Vector retrieval for semantic context - PRIMARY SOURCE
        
        ChromaDB contains COMPLETE rate sheet data:
        - All routes with all pricing
        - All container types
        - Complete raw Excel data
        - Semantic understanding via BGE embeddings
        
        This is the MAIN source of information for draft generation.
        """
        try:
            print(f"\n   🔵 [VECTOR RETRIEVAL] Calling ChromaDB vector service...")
            print(f"      - URL: {self.vector_service_url}/api/vector/collections/rate_sheets/query")
            print(f"      - Query: {query[:200]}...")
            print(f"      - n_results: 15")
            print(f"      - organization_id: {organization_id}")
            logger.info(f"   🔵 [VECTOR RETRIEVAL] Calling ChromaDB: url={self.vector_service_url}, query_length={len(query)}, n_results=15")
            
            async with httpx.AsyncClient(timeout=60.0) as client:  # Increased timeout for ChromaDB
                response = await client.post(
                    f"{self.vector_service_url}/api/vector/collections/rate_sheets/query",
                    json={
                        "query_texts": [query],
                        "n_results": 15,  # Increased from 10 to 15 for better coverage
                        "where": {"organization_id": str(organization_id)}  # ChromaDB stores as string
                    },
                    timeout=60.0
                )
                response.raise_for_status()
                result = response.json()
                
                print(f"      ✅ ChromaDB responded successfully")
                print(f"      - Response keys: {list(result.keys())}")
                logger.info(f"      ✅ ChromaDB responded: response_keys={list(result.keys())}")
                
                # ChromaDB returns nested structure: results.documents is a list of lists
                results = result.get("results", {})
                ids = results.get("ids", [[]])[0] if results.get("ids") else []
                documents = results.get("documents", [[]])[0] if results.get("documents") else []
                metadatas = results.get("metadatas", [[]])[0] if results.get("metadatas") else []
                
                print(f"      - Documents count: {len(documents)}")
                print(f"      - Metadatas count: {len(metadatas)}")
                logger.info(f"      - Documents: {len(documents)}, Metadatas: {len(metadatas)}")
                
                # Log document previews
                for idx, doc in enumerate(documents[:3], 1):
                    doc_preview = doc[:300] + "..." if len(doc) > 300 else doc
                    print(f"      Document {idx} preview (first 300 chars): {doc_preview}")
                    logger.debug(f"      Document {idx} preview: {doc_preview}")
                
                # Combine documents with their metadata and id for context (id needed for rate sheet search)
                combined = []
                for i, doc in enumerate(documents):
                    combined.append({
                        "id": ids[i] if i < len(ids) else None,
                        "content": doc,
                        "metadata": metadatas[i] if i < len(metadatas) else {}
                    })
                
                print(f"      ✅ Combined {len(combined)} results for return")
                logger.info(f"      ✅ Combined {len(combined)} results for return")
                return combined
        except Exception as e:
            print(f"      ❌ Error in vector retrieval: {e}")
            logger.error(f"      ❌ Error in vector retrieval: {e}")
            import traceback
            logger.error(f"      ❌ Traceback: {traceback.format_exc()}")
            return []
    
    def _combine_results(self, results: Dict[str, Any]) -> Dict[str, Any]:
        """Combine results from multiple engines"""
        combined = {
            "exact_rates": [],
            "route_alternatives": [],
            "semantic_context": []
        }
        
        # Extract exact rates from SQL results
        if results.get("sql_results"):
            combined["exact_rates"] = results["sql_results"]
        
        # Extract route alternatives from graph results
        graph_results = results.get("graph_results", [])
        for result in graph_results:
            if isinstance(result, dict) and result.get("type") == "alternatives":
                combined["route_alternatives"] = result.get("alternatives", [])
            elif isinstance(result, dict) and result.get("rate_sheet_id"):
                # Direct route match
                combined["exact_rates"].append(result)
        
        # Extract semantic context from vector results
        if results.get("vector_results"):
            combined["semantic_context"] = results["vector_results"]
        
        return combined
