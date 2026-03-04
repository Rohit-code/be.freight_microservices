"""Re-ranking Service using OpenAI for semantic search refinement"""
from typing import List, Dict, Any, Optional
import logging
import json
import os
from pathlib import Path

from app.core.config import settings

logger = logging.getLogger(__name__)

# Try to load .env file from parent directory if not found in current directory
try:
    from dotenv import load_dotenv
    # Check multiple possible .env locations
    env_paths = [
        Path(__file__).parent.parent.parent.parent / ".env",  # microservices/.env
        Path(__file__).parent.parent.parent / ".env",  # rate_sheet_service/.env
        Path(".env"),  # Current directory
    ]
    for env_path in env_paths:
        if env_path.exists():
            load_dotenv(env_path, override=False)  # Don't override existing env vars
            logger.info(f"Loaded .env from: {env_path}")
            break
except ImportError:
    pass  # python-dotenv not available, rely on pydantic-settings

# Initialize OpenAI client
try:
    from openai import OpenAI
    # Try to get API key from environment variable first, then from settings
    openai_api_key = os.getenv('OPENAI_API_KEY') or settings.OPENAI_API_KEY
    
    # Log for debugging
    if openai_api_key:
        logger.info(f"OpenAI API key found (length: {len(openai_api_key)} chars)")
    else:
        logger.warning("OPENAI_API_KEY not found. Please add it to your .env file:")
        logger.warning("  OPENAI_API_KEY=sk-...")
        logger.warning("Location: microservices/.env or microservices/rate_sheet_service/.env")
        logger.warning(f"Current settings.OPENAI_API_KEY: {settings.OPENAI_API_KEY}")
        logger.warning(f"Current os.getenv('OPENAI_API_KEY'): {os.getenv('OPENAI_API_KEY')}")
    
    if openai_api_key:
        client = OpenAI(api_key=openai_api_key)
        logger.info("OpenAI client initialized successfully")
    else:
        client = None
        logger.warning("OpenAI API key not found. Set OPENAI_API_KEY in .env file or environment variable.")
except ImportError:
    client = None
    openai_api_key = None
    logger.warning("OpenAI library not installed. Install with: pip install openai")
except Exception as e:
    client = None
    openai_api_key = None
    logger.error(f"Error initializing OpenAI client: {e}")


def is_openai_available() -> bool:
    """Check if OpenAI API is configured"""
    has_client = client is not None
    has_key = openai_api_key and openai_api_key.strip() != ""
    is_available = has_client and has_key
    
    if not is_available:
        logger.warning(f"OpenAI not available - client initialized: {has_client}, API key present: {has_key}")
        if not has_key:
            logger.warning("Please set OPENAI_API_KEY in your .env file: OPENAI_API_KEY=your_key_here")
    
    return is_available


class RerankService:
    """Service for re-ranking search results using OpenAI"""
    
    def __init__(self):
        self.client = client
        self.api_key = openai_api_key

    async def normalize_search_query(self, query: str) -> str:
        """
        Use AI to expand the search query with common port/city spelling variants
        so that 'Kolkata' also matches 'KOLKATA'/'KOLKATTA' in rate sheets.
        Returns the expanded query for vector search, or the original query on failure.
        """
        if not query or not query.strip():
            return query or ""
        if not is_openai_available():
            return query.strip()
        import asyncio
        user_prompt = f"""Expand this freight search query with common port/city spelling variants so vector search can match rate sheets that use different spellings (e.g. Kolkata = KOLKATA = KOLKATTA; Bangkok = BANGKOK; Singapore = SINGAPORE; Chennai = MADRAS). Add variants as extra words on one line. If no clear port names, return the query unchanged. Output ONLY the single expanded line, no explanation.

Query: {query.strip()}

Expanded query:"""

        try:
            response = await asyncio.to_thread(
                self.client.chat.completions.create,
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "You output only the expanded search query: one line, no other text."},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.0,
                max_tokens=150
            )
            expanded = (response.choices[0].message.content or "").strip()
            if expanded and len(expanded) <= 500:
                logger.info(f"Query normalized for port spellings: '{query[:50]}...' -> '{expanded[:80]}...'")
                print(f"[QUERY NORMALIZE] expanded for vector search: '{expanded[:100]}...'")
                return expanded
        except Exception as e:
            logger.warning(f"Query normalization failed, using original: {e}")
            print(f"[QUERY NORMALIZE] failed ({type(e).__name__}), using original query")
        return query.strip()

    async def rerank_results(
        self,
        query: str,
        results: List[Dict[str, Any]],
        top_k: int = 3
    ) -> List[Dict[str, Any]]:
        """
        Re-rank search results using OpenAI to find the most relevant matches
        
        Args:
            query: Original search query
            results: List of search results from vector search (top 20)
            top_k: Number of top results to return (default: 3)
        
        Returns:
            List of top-k re-ranked results with relevance scores
        """
        if not is_openai_available():
            logger.error("OpenAI not available, returning top results by similarity")
            logger.error(f"OpenAI client initialized: {client is not None}, API key present: {bool(openai_api_key)}")
            if not openai_api_key:
                logger.error("OPENAI_API_KEY is not set. Please check your .env file.")
            # Fallback: return top results by similarity score with individual reasoning
            sorted_results = sorted(results, key=lambda x: x.get("similarity", 0), reverse=True)
            # Add individual reasoning message to each result
            for idx, result in enumerate(sorted_results[:top_k], 1):
                result["ai_reasoning"] = f"Ranked #{idx} based on similarity score ({result.get('similarity', 0):.3f}). AI re-ranking unavailable - OpenAI not configured."
                result["rank"] = idx
            return sorted_results[:top_k]
        
        if not results:
            return []
        
        if len(results) <= top_k:
            # If we have fewer results than top_k, return all with individual reasoning
            for idx, result in enumerate(results, 1):
                result["ai_reasoning"] = f"Ranked #{idx} - All available results returned."
                result["rank"] = idx
            return results
        
        try:
            # Verify OpenAI is available before proceeding
            if not is_openai_available():
                logger.error("OpenAI not available in rerank_results - this should have been caught earlier")
                logger.error(f"Client: {self.client}, API Key: {'present' if self.api_key else 'missing'}")
                sorted_results = sorted(results, key=lambda x: x.get("similarity", 0), reverse=True)
                for idx, result in enumerate(sorted_results[:top_k], 1):
                    result["ai_reasoning"] = f"Ranked #{idx} based on similarity score ({result.get('similarity', 0):.3f}). OpenAI API key not configured."
                    result["rank"] = idx
                return sorted_results[:top_k]
            
            logger.info(f"Starting OpenAI re-ranking for {len(results)} results with query: '{query[:50]}...'")
            logger.info(f"OpenAI client available: {self.client is not None}, API key: {'present' if self.api_key else 'missing'}")
            
            # Prepare results summary for OpenAI with full content
            results_summary = []
            for idx, result in enumerate(results):
                metadata = result.get("metadata", {})
                # Get full document content, not just preview
                full_document = result.get("document", result.get("document_preview", ""))
                # Use more content - up to 2000 chars to ensure AI sees the actual data
                document_content = full_document[:2000] if len(full_document) > 2000 else full_document
                
                summary = {
                    "id": result.get("id"),
                    "index": idx + 1,
                    "file_name": metadata.get("file_name", ""),
                    "title": metadata.get("title", ""),
                    "carrier_name": metadata.get("carrier_name", ""),
                    "similarity_score": result.get("similarity", 0),
                    "content": document_content,  # Full content, not just preview
                    "key_info": {
                        "rate_sheet_type": metadata.get("rate_sheet_type", ""),
                        "status": metadata.get("status", ""),
                    }
                }
                
                # Add matching data if available - this shows what matched the query
                matching_data = result.get("matching_data", {})
                if matching_data:
                    # Include actual matching rows content
                    matching_rows = matching_data.get("matching_rows", [])[:10]  # First 10 matching rows
                    extracted_data = matching_data.get("extracted_data", [])[:5]  # First 5 extracted data points
                    key_matches = matching_data.get("key_matches", [])[:5]  # First 5 key matches
                    
                    summary["matching_info"] = {
                        "matched_rows_count": len(matching_data.get("matching_rows", [])),
                        "extracted_data_count": len(matching_data.get("extracted_data", [])),
                        "key_matches_count": len(matching_data.get("key_matches", [])),
                        "sample_matching_rows": [row.get("content", "")[:200] for row in matching_rows],
                        "sample_extracted_data": extracted_data,
                        "sample_key_matches": [match.get("context", "")[:200] for match in key_matches]
                    }
                
                results_summary.append(summary)
            
            # Build prompt for OpenAI
            prompt = self._build_rerank_prompt(query, results_summary, top_k)
            
            # Call OpenAI API (synchronous call in async context - OpenAI client handles this)
            # Using asyncio.to_thread for better async compatibility
            import asyncio
            logger.info(f"Calling OpenAI API with {len(results)} results, query: '{query[:50]}...'")
            
            try:
                response = await asyncio.to_thread(
                    self.client.chat.completions.create,
                    model="gpt-4o-mini",
                    messages=[
                        {
                            "role": "system",
                            "content": "You are an expert at analyzing freight forwarding rate sheets and finding the most relevant results for user queries. You understand ports, routes, container types, pricing, and shipping logistics."
                        },
                        {
                            "role": "user",
                            "content": prompt
                        }
                    ],
                    temperature=0.3,  # Lower temperature for more consistent ranking
                    response_format={"type": "json_object"}
                )
                logger.info(f"OpenAI API call successful, status: {response}")
            except Exception as api_error:
                logger.error(f"OpenAI API call failed: {api_error}", exc_info=True)
                # Fallback: use similarity scores
                sorted_results = sorted(results, key=lambda x: x.get("similarity", 0), reverse=True)
                for idx, result in enumerate(sorted_results[:top_k], 1):
                    result["ai_reasoning"] = f"Ranked #{idx} based on similarity score ({result.get('similarity', 0):.3f}). OpenAI API error: {str(api_error)}"
                    result["rank"] = idx
                return sorted_results[:top_k]
            
            # Parse response
            response_content = response.choices[0].message.content
            logger.info(f"OpenAI response received: {response_content[:200]}...")
            
            try:
                ranking_result = json.loads(response_content)
            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse OpenAI JSON response: {e}")
                logger.error(f"Response content: {response_content}")
                # Fallback: use similarity scores
                sorted_results = sorted(results, key=lambda x: x.get("similarity", 0), reverse=True)
                for idx, result in enumerate(sorted_results[:top_k], 1):
                    result["ai_reasoning"] = f"Ranked #{idx} based on similarity score ({result.get('similarity', 0):.3f}). Error parsing AI response."
                    result["rank"] = idx
                return sorted_results[:top_k]
            
            # Extract ranked indices and individual reasoning for each result
            ranked_indices = ranking_result.get("ranked_indices", [])
            individual_reasoning = ranking_result.get("individual_reasoning", {})
            overall_summary = ranking_result.get("overall_summary", "Results ranked by relevance to your query.")
            
            logger.info(f"Extracted ranked_indices: {ranked_indices}, individual_reasoning keys: {list(individual_reasoning.keys())}")
            
            if not ranked_indices:
                # Fallback: use similarity scores
                logger.warning("OpenAI didn't return ranked_indices in response, using similarity scores")
                logger.warning(f"Response keys: {list(ranking_result.keys())}")
                sorted_results = sorted(results, key=lambda x: x.get("similarity", 0), reverse=True)
                # Add individual reasoning message to each result
                for idx, result in enumerate(sorted_results[:top_k], 1):
                    result["ai_reasoning"] = f"Ranked #{idx} based on similarity score ({result.get('similarity', 0):.3f}). AI did not return ranking."
                    result["rank"] = idx
                return sorted_results[:top_k]
            
            # Map indices back to results with individual reasoning (indices are 1-based in the prompt)
            ranked_results = []
            for rank_position, idx in enumerate(ranked_indices[:top_k], 1):
                # Convert 1-based index to 0-based
                result_idx = idx - 1
                if 0 <= result_idx < len(results):
                    result = results[result_idx].copy()
                    # Get individual reasoning for this result, or generate default
                    result_reasoning = individual_reasoning.get(str(idx)) or individual_reasoning.get(idx)
                    if not result_reasoning:
                        # Generate default reasoning based on rank position
                        result_reasoning = f"Ranked #{rank_position} - Most relevant to your query based on content analysis."
                    result["ai_reasoning"] = result_reasoning
                    result["rank"] = rank_position  # Add rank position for reference
                    ranked_results.append(result)
            
            # If we got fewer results than expected, fill with similarity-based ranking
            if len(ranked_results) < top_k:
                remaining_indices = set(range(len(results))) - set(idx - 1 for idx in ranked_indices[:top_k])
                remaining_results = [results[i] for i in remaining_indices]
                remaining_results.sort(key=lambda x: x.get("similarity", 0), reverse=True)
                for idx, result in enumerate(remaining_results[:top_k - len(ranked_results)], len(ranked_results) + 1):
                    result_copy = result.copy()
                    result_copy["ai_reasoning"] = f"Ranked #{idx} based on similarity score ({result.get('similarity', 0):.3f})."
                    result_copy["rank"] = idx
                    ranked_results.append(result_copy)
            
            logger.info(f"Re-ranked {len(results)} results to top {len(ranked_results)} using OpenAI with individual reasoning")
            return ranked_results
        
        except Exception as e:
            logger.error(f"Error re-ranking results with OpenAI: {e}", exc_info=True)
            # Fallback: return top results by similarity with individual reasoning
            sorted_results = sorted(results, key=lambda x: x.get("similarity", 0), reverse=True)
            for idx, result in enumerate(sorted_results[:top_k], 1):
                result["ai_reasoning"] = f"Ranked #{idx} based on similarity score ({result.get('similarity', 0):.3f}). Error during AI re-ranking: {str(e)}"
                result["rank"] = idx
            return sorted_results[:top_k]
    
    def _build_rerank_prompt(self, query: str, results: List[Dict[str, Any]], top_k: int) -> str:
        """Build the prompt for OpenAI re-ranking"""
        
        results_text = "\n\n".join([
            f"Result {r['index']}:\n"
            f"  File: {r['file_name']}\n"
            f"  Title: {r.get('title', 'N/A')}\n"
            f"  Carrier: {r.get('carrier_name', 'N/A')}\n"
            f"  Similarity Score: {r.get('similarity_score', 0):.3f}\n"
            f"  Content:\n{r.get('content', '')}\n"
            + (f"  Matching Info:\n    Matched Rows: {len(r.get('matching_info', {}).get('sample_matching_rows', []))}\n"
               f"    Sample Matching Rows:\n" + "\n".join([f"      - {row}" for row in r.get('matching_info', {}).get('sample_matching_rows', [])[:5]]) + "\n"
               f"    Sample Extracted Data: {r.get('matching_info', {}).get('sample_extracted_data', [])[:3]}\n"
               if r.get('matching_info') else "")
            for r in results
        ])
        
        prompt = f"""You are analyzing search results for a freight forwarding rate sheet query.

User Query: "{query}"

I have {len(results)} search results from a vector similarity search. Please analyze these results and rank them by relevance to the user's query.

Consider:
1. How well each result matches the specific query terms
2. The relevance of the content (ports, routes, prices, container types, etc.)
3. The quality and completeness of the data
4. The matching information available

Results:
{results_text}

CRITICAL INSTRUCTIONS:
- You MUST rank ALL {len(results)} results provided, even if some seem less relevant
- The results have already been filtered by vector similarity search, so they ALL contain some relevant information
- Your job is to rank them from MOST relevant to LEAST relevant, not to filter them out
- Even if a result seems less relevant, it should still be ranked (just lower)
- Look carefully at the "Content" and "Matching Info" sections - they contain the actual data

Please return a JSON object with this structure:
{{
    "ranked_indices": [1, 5, 3, ...],
    "individual_reasoning": {{
        "1": "Specific explanation for why result #1 is ranked first - what makes it most relevant",
        "5": "Specific explanation for why result #5 is ranked second - what makes it relevant",
        "3": "Specific explanation for why result #3 is ranked third - what makes it relevant"
    }},
    "overall_summary": "Brief overall summary of why these top {top_k} results were selected"
}}

REQUIREMENTS:
- "ranked_indices" MUST contain exactly {top_k} indices (or all available if fewer than {top_k}), ordered from most relevant to least relevant
- You MUST rank all results - do NOT return an empty array
- "individual_reasoning" should be an object where keys are the result indices (as strings) and values are specific explanations
- Each reasoning should mention specific details from the content: port names, prices, routes, container types, data completeness, etc.
- Even if a result has less relevant information, still rank it (just lower) and explain why it's less relevant
- Look at the "Content" field carefully - it contains the actual rate sheet data including ports, prices, routes, etc.

Return the JSON response now:"""
        
        return prompt
    
    async def generate_answer(
        self,
        query: str,
        results: List[Dict[str, Any]],
        answer_style: str = "auto",
        intent_result: Optional[Dict[str, Any]] = None,
        structured_routes: Optional[List[Dict[str, Any]]] = None
    ) -> str:
        """
        Generate a direct answer from rate sheet data. Uses intent (orchestrator/intent_classifier)
        when provided so the AI gets one clear instruction; otherwise falls back to answer_style.
        If structured_routes is provided (from PostgreSQL), they are prepended to context so the model can answer with exact rates.
        """
        if not is_openai_available():
            logger.warning("OpenAI not available, cannot generate answer")
            return "Unable to generate answer. Please review the rate sheets below for details."
        
        if not results:
            return "No relevant rate sheets found to answer your query."
        
        # Use only intent.answer_preferences (from orchestrator/intent_classifier). No hardcoded query parsing here.
        prefs = (intent_result or {}).get("answer_preferences") or {}
        try:
            style = (prefs.get("answer_format") or answer_style or "auto").lower()
            use_list = style == "list"
            use_short = style == "short" or use_list
            include_validity = bool(prefs.get("include_validity"))
            container_filter = prefs.get("container_filter")
            list_all_routes = bool(prefs.get("list_all_routes"))
            sort_alphabetically = bool(prefs.get("sort_alphabetically"))
            region_filter = (prefs.get("region_filter") or "").strip() or None
            asks_for_volume_or_throughput = bool(prefs.get("asks_for_volume_or_throughput"))
        except Exception:
            use_list = use_short = False
            include_validity = list_all_routes = sort_alphabetically = False
            container_filter = region_filter = None
            asks_for_volume_or_throughput = False
        # Fallback: detect volume/throughput question from query when intent has no signal
        if not asks_for_volume_or_throughput and query:
            q = query.lower()
            asks_for_volume_or_throughput = (
                ("how many" in q and ("container" in q or "teu" in q or "volume" in q))
                or "containers processed" in q or "volume processed" in q or "total teus" in q
            )
        # Fallback: detect India (or other region) from query when intent did not set region_filter
        if not region_filter and query:
            q = query.lower()
            india_plus = any(w in q for w in ["list", "containers", "rates", "costs", "feb", "february", "cheapest", "lowest", "rate", "fcl"])
            if "india" in q and india_plus:
                region_filter = "India"
        print(f"[GENERATE_ANSWER] style={style} use_list={use_list} use_short={use_short} include_validity={include_validity} container_filter={container_filter} list_all_routes={list_all_routes} sort_alphabetically={sort_alphabetically} region_filter={region_filter} asks_volume={asks_for_volume_or_throughput} (intent={'yes' if intent_result else 'no'})")

        # Cursor-style: behave like Cursor with a codebase – data below is the only source of truth
        _cursor_rules = (
            "You work like Cursor: the rate sheet data provided below is your ONLY source of truth. "
            "Answer ONLY from that data. Do not guess, infer, or use external knowledge about ports or rates. "
            "If the answer is not in the data, say so clearly (e.g. 'The provided rate sheets do not contain that route/port/rate.'). "
            "Never invent a port name, route, or price. "
            "Port names may appear in different spellings or cases in the data (e.g. Kolkata = KOLKATA = KOLKATTA = Calcutta; Bangkok = BANGKOK; Singapore = SINGAPORE; Laem Chabang = LAEM CHABANG; Chennai = MADRAS). Treat them as the SAME port when matching the user's question to the data—do not say 'no route' just because the spelling differs. "
            "When the user asks for 'all', 'list', or 'every' route/cost, scan the ENTIRE provided data and include every relevant item—do not sample or truncate. "
            "Use markdown for structure when helpful (headers, bullets); no fluff like 'Overview', 'Understanding', or 'Conclusion' unless the user asked for explanation. "
            "If the user asks for information not in the data (e.g. container counts, TEUs, volume, throughput) and the data only has freight rates, say: "
            "'The rate sheets provided do not contain that; they only include freight rates by route.' "
            "If the data DOES include TEUs, volume, or targets, use that to answer."
        )

        try:
            # Prepare content from results for answer generation
            results_content = []
            for idx, result in enumerate(results, 1):
                metadata = result.get("metadata", {})
                full_document = result.get("document", result.get("document_preview", ""))
                
                # Get matching data to highlight what's relevant
                matching_data = result.get("matching_data", {})
                matching_rows = matching_data.get("matching_rows", [])[:15] if matching_data else []
                
                # Extract key information from metadata
                file_name = metadata.get('file_name', 'Unknown')
                title = metadata.get('title', 'N/A')
                carrier = metadata.get('carrier_name', 'N/A')
                rate_type = metadata.get('rate_sheet_type', 'N/A')
                valid_from = (metadata.get('valid_from') or '').strip()
                valid_to = (metadata.get('valid_to') or '').strip()
                validity_line = f"Valid: {valid_from} to {valid_to}\n" if (valid_from or valid_to) else ""
                
                # Build structured result info. Clarify: origin = port (from route lines), carrier = shipping line.
                result_info = f"""Rate Sheet {idx}: {file_name}
Carrier (shipping line): {carrier} | Origin PORT is in route lines below, NOT the carrier name.
Title: {title}
Type: {rate_type}
{validity_line}

Key Rate Information (each route shows origin PORT → destination):
"""
                
                # Extract structured matching rows with relevant data
                if matching_rows:
                    for row in matching_rows:
                        content = row.get('content', '').strip()
                        structured_data = row.get('structured_data', {})
                        
                        if structured_data:
                            # Format structured data nicely
                            data_parts = []
                            for key, value in structured_data.items():
                                if value and str(value).lower() != 'null':
                                    data_parts.append(f"{key}: {value}")
                            if data_parts:
                                result_info += f"  • {' | '.join(data_parts)}\n"
                        elif content:
                            # Use raw content but limit length
                            clean_content = content[:300].replace('\n', ' ').strip()
                            if clean_content:
                                result_info += f"  • {clean_content}\n"
                
                # For short answers: always include enough document context so the model can find the route
                # even when matching_rows is sparse (e.g. query had "sheva?" so no row matched "sheva")
                if use_short and full_document:
                    if list_all_routes:
                        result_info += "\nFull route list (list every route from this data):\n"
                        result_info += full_document[:14000] if len(full_document) > 14000 else full_document
                    else:
                        result_info += "\nDocument excerpt (for context):\n"
                        result_info += full_document[:10000] if len(full_document) > 10000 else full_document
                    result_info += "\n"
                
                # DEBUG: log what we're sending so we can see why model might say "no route"
                doc_len = len(full_document)
                doc_upper = (full_document or "").upper()
                has_bangkok = "BANGKOK" in doc_upper
                has_kolkatta = "KOLKATTA" in doc_upper
                has_kolkata = "KOLKATA" in doc_upper
                has_laem = "LAEM CHABANG" in doc_upper or "LAEM CHABANG" in (full_document or "")
                print(f"[GENERATE_ANSWER DEBUG] result {idx}: doc_len={doc_len} | BANGKOK={has_bangkok} KOLKATTA={has_kolkatta} KOLKATA={has_kolkata} LAEM_CHABANG={has_laem}")
                if idx == 1 and full_document:
                    snippet = (full_document[:500] or "").replace("\n", " ")
                    print(f"[GENERATE_ANSWER DEBUG] first result document snippet (500 chars): {snippet}")
                
                # For long answer only: add comprehensive document context
                if not use_short and full_document:
                    # Extract more comprehensive context for detailed explanations
                    doc_lines = full_document.split('\n')
                    structured_sections = []
                    for line in doc_lines[:200]:
                        line_lower = line.lower().strip()
                        if any(keyword in line_lower for keyword in ['route', 'pricing', 'surcharge', 'container', 'port', 'origin', 'destination', 'validity', 'carrier']):
                            if line.strip():
                                structured_sections.append(f"Section: {line.strip()[:150]}")
                        if any(keyword in line_lower for keyword in 
                               ['route', 'port', 'container', 'price', 'rate', 'origin', 'destination', 
                                'transit', 'detention', 'free', 'surcharge', 'currency', 'valid', 'effective']):
                            clean_line = line.strip()
                            if clean_line and len(clean_line) > 10:
                                structured_sections.append(clean_line[:250])
                    if structured_sections:
                        result_info += f"\nComplete Rate Sheet Structure:\n"
                        for section in structured_sections[:25]:
                            if section:
                                result_info += f"  • {section}\n"
                    if len(full_document) > 1000:
                        result_info += f"\nNote: This rate sheet contains {len(full_document)} characters of detailed information.\n"
                
                results_content.append(result_info)
            
            # If we have structured routes from PostgreSQL, prepend so the model uses them for the answer
            if structured_routes and len(structured_routes) > 0 and results_content:
                lines = ["Structured routes from database (use these for the answer):"]
                for r in structured_routes[:15]:
                    route = r.get("route", r) if isinstance(r.get("route"), dict) else r
                    orig = route.get("origin_port") or route.get("origin_code") or ""
                    dest = route.get("destination_port") or route.get("destination_code") or ""
                    cont = route.get("container_type") or ""
                    rate = route.get("base_rate")
                    curr = route.get("currency") or "USD"
                    if rate is not None:
                        lines.append(f"  {orig} → {dest} | {cont}: {curr} {rate}")
                block = "\n".join(lines)
                results_content[0] = block + "\n\n" + results_content[0]
                print(f"[GENERATE_ANSWER DEBUG] Injected {len(structured_routes)} structured routes into context")
            
            if use_list:
                # One instruction block from intent (orchestrator/intent_classifier). No if/else on query.
                instructions = []
                # Region filter FIRST so the model cannot miss it
                if region_filter and str(region_filter).lower() == "india":
                    instructions.append("CRITICAL – INDIA ONLY: List ONLY routes where the origin port OR the destination port is in India. Indian ports: NHAVA SHEVA, MUNDRA, PIPAVAV, CHENNAI, KATTUPALLI, KOLKATA, HALDIA, VIZAG, VISAKHAPATNAM, KOLKATTA. Do NOT list any route that has no Indian port (e.g. do NOT list SINGAPORE→COLOMBO, SINGAPORE→CHITTAGONG, SINGAPORE→DHAKA, SINGAPORE→KARACHI, SINGAPORE→JEBEL ALI, SINGAPORE→JAKARTA, SINGAPORE→BANGKOK, PORT KLANG→JAKARTA, LAEM CHABANG→CHITTAGONG, LAEM CHABANG→KARACHI).")
                elif region_filter:
                    instructions.append(f"CRITICAL: List ONLY routes where origin OR destination is in {region_filter}. Exclude all other routes.")
                instructions.extend([
                    "Use ORIGIN PORT from the route data (e.g. PORT KLANG, LAEM CHABANG). Do NOT use carrier name (e.g. MAXICON) as origin.",
                    "Format for clarity: GROUP BY ORIGIN PORT. Under each origin, list destinations with rates. Example: **SINGAPORE** then next lines: KOLKATA (20'): USD 750 | (40'): USD 1500; COLOMBO (20'): USD 1400 | (40'): USD 2800; etc. Then **PORT KLANG** and its destinations. Use blank line between origin groups. This makes the list scannable and avoids truncation.",
                    "Do NOT truncate. Include EVERY route from the data. If the list is long, keep the grouped format so the full list fits and is readable.",
                ])
                if container_filter == "20'":
                    instructions.append("Filter to 20' only. Label each line (20'). Do not include 40' rates.")
                elif container_filter == "40'":
                    instructions.append("Filter to 40' only. Label each line (40'). Do not include 20' rates.")
                else:
                    instructions.append("Include BOTH 20' and 40' rates for each route where available. Label each line (20') or (40'). Do not omit 40' when the data has it.")
                if sort_alphabetically:
                    instructions.append("Sort the list alphabetically: first by origin port (A–Z), then by destination port (A–Z).")
                if list_all_routes:
                    instructions.append("List EVERY route in the data (all origins, all destinations). Do not show only one destination. No sampling.")
                else:
                    instructions.append("Show ONE line per route (one rate per origin–destination–container). Do not list the same route multiple times with different costs.")
                if include_validity:
                    instructions.append("Include validity (Valid From – Valid To) on every line. Format: origin → destination (20'): cost | Valid: from–to.")
                instruction_block = " ".join(instructions)
                content_slice = results_content[:10] if list_all_routes else results_content[:5]
                # Allow enough tokens for full route list; grouped-by-origin format is more compact
                max_tokens = 8192 if list_all_routes else 350
                volume_hint = "Note: The user is asking for volume/container count or TEUs; if the data does not contain that, say so clearly.\n\n" if asks_for_volume_or_throughput else ""
                region_hint = ""
                if region_filter and str(region_filter).lower() == "india":
                    region_hint = "IMPORTANT: The user asked for India only. Output ONLY routes where origin OR destination is an Indian port. Do NOT include COLOMBO, CHITTAGONG, DHAKA, KARACHI, JEBEL ALI, JEDDAH, JAKARTA, BANGKOK, etc. unless the other end is India.\n\n"
                prompt = f"""{volume_hint}{region_hint}Like Cursor: the data below is your only source. Scan it completely and list every route/cost that matches the query. Do not truncate.

User query: "{query}"

Rate sheet data (unified; do not refer to "Rate Sheet 1" or sheet-wise):
{chr(10).join(content_slice)}

Format instructions (follow exactly): {instruction_block}

Output: grouped-by-origin format (origin as header, then destinations with 20'/40' and costs). Include EVERY route from the data; do not cut off. Follow any specific request (sorted, validity, 20' only, 40' only). FORBIDDEN: "Overview", "Understanding", "Conclusion", using carrier name as origin."""
                system_content = _cursor_rules + "\n\nLike Cursor: check ALL the data below and output every matching route and cost. Use grouped-by-origin format for readability. Do not truncate. Use origin port, never carrier name. No intros, no conclusions."
                if region_filter and str(region_filter).lower() == "india":
                    system_content += " When the user asks for India, list ONLY routes that have an Indian port as origin or destination; exclude all other routes."
            elif use_short:
                # Short: one place data, very concise. Only the direct answer.
                volume_hint = "Note: The user is asking for volume/container count or TEUs; if the data does not contain that, say so clearly.\n\n" if asks_for_volume_or_throughput else ""
                region_hint_short = ""
                if region_filter and str(region_filter).lower() == "india":
                    region_hint_short = "CRITICAL – India only: The user asked for rates IN India. Consider ONLY routes where origin OR destination is an Indian port (NHAVA SHEVA, MUNDRA, PIPAVAV, CHENNAI, KATTUPALLI, KOLKATA, HALDIA, VIZAG, KOLKATTA). Do NOT give the globally cheapest (e.g. Singapore→Laem Chabang is Thailand, not India). The cheapest rate IN India is the minimum among routes that touch India.\n\n"
                prompt = f"""{volume_hint}{region_hint_short}Like Cursor: answer only from the data below. If the answer is not there, say so.

Query: "{query}"

Data (unified; do not say 'Rate Sheet 1' or sheet-wise):
{chr(10).join(results_content[:3])}

Reply in 1-3 lines. Give the exact data asked (routes/costs or one number). No fluff, no overview."""
                max_tokens = 120
                system_content = _cursor_rules + "\n\nLike Cursor: give only the direct answer from the data below. One place. No fluff, no overviews. Maximum 1-3 short lines. If the data does not contain the answer, say so."
                if region_filter and str(region_filter).lower() == "india":
                    system_content += " When the user asks for 'cheapest/lowest rate IN India' or 'rate in India', answer using ONLY routes that have an Indian port as origin or destination; do not pick a route like Singapore→Laem Chabang (Thailand)."
            else:
                # Long answer: detailed (existing prompt)
                volume_hint = "Note: The user is asking for volume/container count or TEUs; if the data does not contain that, say so clearly.\n\n" if asks_for_volume_or_throughput else ""
                prompt = f"""{volume_hint}You are an expert freight forwarding consultant and trainer with 15+ years of experience. A user has asked a question about rate sheets, and you have access to relevant rate sheet data.

User Question: "{query}"

Relevant Rate Sheet Data:
{chr(10).join(results_content)}

Based on the rate sheet data above, provide a comprehensive, in-depth, and highly detailed answer to the user's question.

CRITICAL REQUIREMENTS FOR DEPTH AND QUALITY:
1. **Depth Over Breadth**: Provide deep, detailed explanations. Don't just list facts - explain the "why" and "how" behind everything
2. **Comprehensive Coverage**: Cover all aspects of the question thoroughly. If they ask about understanding rate sheets, explain:
   - What each component means in business context
   - How to read and interpret the data
   - Step-by-step walkthroughs with actual examples from the data
   - Common pitfalls and what to watch out for
   - How to compare rates effectively
   - Industry terminology and abbreviations
   - How to use this information in real business decisions
3. **Practical Walkthroughs**: Include detailed, step-by-step instructions with specific examples from the actual rate sheet data provided
4. **Technical Details**: Don't shy away from technical terms - explain them clearly. Include:
   - Container specifications and their implications
   - Port codes and their meanings
   - Transit time calculations
   - Detention and demurrage concepts
   - Surcharges and additional fees
   - Service types (FCL, LCL, etc.)
5. **Real Examples**: Use actual data from the rate sheets provided to illustrate every point. Reference specific routes, ports, prices, and conditions
6. **Business Context**: Explain how this information is used in real freight forwarding operations:
   - How to quote customers
   - How to compare carrier options
   - How to identify the best routes
   - How to calculate total costs
   - How to plan logistics timelines
7. **Visual Structure**: Use clear hierarchical structure with:
   - Main sections with descriptive headings
   - Subsections for detailed topics
   - Bullet points for lists
   - Numbered steps for walkthroughs
   - Tables or structured formats for comparisons
8. **Educational Approach**: Write as if teaching someone who wants to become proficient, not just get a quick answer
9. **Actionable Insights**: Provide specific, actionable advice they can use immediately
10. **Complete Picture**: Address all aspects of the question - don't leave gaps. If explaining "how to check" rate sheets, cover:
    - Where to find specific information
    - How to navigate the sheet structure
    - What each field means
    - How to cross-reference data
    - How to verify accuracy
    - How to extract the information you need

FORMATTING REQUIREMENTS:
- Start with a brief introduction that acknowledges the depth of the question
- Use clear, descriptive section headings (use ## for main sections, ### for subsections)
- Include detailed examples with actual data from the rate sheets
- Use bullet points for lists, numbered steps for procedures
- Highlight important concepts and terms
- End with a comprehensive summary and next steps

STYLE GUIDELINES:
- Write in a professional, educational tone - like a senior consultant teaching a junior colleague
- Be thorough and detailed - aim for 800-1500 words for complex questions
- Use industry terminology but explain it clearly
- Reference specific examples from the provided data
- Make it practical and actionable
- Don't oversimplify - provide the depth they're asking for

Use this long format ONLY because the user explicitly asked to explain, compare, or understand in depth. If they had asked only for data/routes/costs, you would have replied in 1-3 lines.

Provide your comprehensive, in-depth answer now:"""
                max_tokens = 800
                system_content = _cursor_rules + "\n\nLike Cursor: base your answer only on the rate sheet data provided. You are an expert consultant; explain and teach from that data. Do not invent routes or figures. If something is not in the data, say so. Provide depth when the user asks for explanation or understanding."
            
            # Call OpenAI API to generate answer
            import asyncio
            out_style = "list" if use_list else "short" if use_short else "long"
            print(f"[GENERATE_ANSWER] Calling OpenAI for {out_style} answer (max_tokens see prompt)")
            logger.info(f"Generating answer for query: '{query[:50]}...' (style={out_style})")
            
            response = await asyncio.to_thread(
                self.client.chat.completions.create,
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": system_content},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.0 if (use_short or use_list) else 0.7,
                max_tokens=max_tokens
            )
            
            answer = response.choices[0].message.content.strip()
            logger.info(f"Generated answer (length: {len(answer)} chars)")
            return answer
        
        except Exception as e:
            logger.error(f"Error generating answer: {e}", exc_info=True)
            return f"Unable to generate answer due to an error. Please review the rate sheets below for details. Error: {str(e)}"
    