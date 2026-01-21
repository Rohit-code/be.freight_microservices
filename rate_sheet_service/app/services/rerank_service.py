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
        results: List[Dict[str, Any]]
    ) -> str:
        """
        Generate a direct answer to the user's query based on the rate sheet results
        
        Args:
            query: User's question/query
            results: Top ranked rate sheet results
            
        Returns:
            Direct answer extracted from the rate sheets
        """
        if not is_openai_available():
            logger.warning("OpenAI not available, cannot generate answer")
            return "Unable to generate answer. Please review the rate sheets below for details."
        
        if not results:
            return "No relevant rate sheets found to answer your query."
        
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
                
                # Build structured result info
                result_info = f"""Rate Sheet {idx}: {file_name}
Carrier: {carrier}
Title: {title}
Type: {rate_type}

Key Rate Information:
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
                
                # Add comprehensive document context for deep explanations
                if full_document:
                    # Extract more comprehensive context for detailed explanations
                    doc_lines = full_document.split('\n')
                    
                    # Extract structured sections (routes, pricing tiers, surcharges, etc.)
                    structured_sections = []
                    current_section = None
                    
                    for line in doc_lines[:200]:  # Process more lines for comprehensive context
                        line_lower = line.lower().strip()
                        
                        # Identify section headers
                        if any(keyword in line_lower for keyword in ['route', 'pricing', 'surcharge', 'container', 'port', 'origin', 'destination', 'validity', 'carrier']):
                            if line.strip():
                                structured_sections.append(f"Section: {line.strip()[:150]}")
                        
                        # Extract data rows with key information
                        if any(keyword in line_lower for keyword in 
                               ['route', 'port', 'container', 'price', 'rate', 'origin', 'destination', 
                                'transit', 'detention', 'free', 'surcharge', 'currency', 'valid', 'effective']):
                            clean_line = line.strip()
                            if clean_line and len(clean_line) > 10:  # Skip very short lines
                                structured_sections.append(clean_line[:250])
                    
                    if structured_sections:
                        result_info += f"\nComplete Rate Sheet Structure:\n"
                        # Include more lines for comprehensive understanding
                        for section in structured_sections[:25]:  # Top 25 relevant sections
                            if section:
                                result_info += f"  • {section}\n"
                    
                    # Add document length info for context
                    doc_length = len(full_document)
                    if doc_length > 1000:
                        result_info += f"\nNote: This rate sheet contains {doc_length} characters of detailed information including routes, pricing tiers, surcharges, and operational details.\n"
                
                results_content.append(result_info)
            
            # Build prompt for answer generation
            prompt = f"""You are an expert freight forwarding consultant and trainer with 15+ years of experience. A user has asked a question about rate sheets, and you have access to relevant rate sheet data.

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

If the question asks for explanations or walkthroughs, provide extensive detail. If they say "I don't know anything" or "explain to me", treat it as a request for comprehensive education, not a quick overview.

Provide your comprehensive, in-depth answer now:"""
            
            # Call OpenAI API to generate answer
            import asyncio
            logger.info(f"Generating answer for query: '{query[:50]}...'")
            
            response = await asyncio.to_thread(
                self.client.chat.completions.create,
                model="gpt-4o-mini",
                messages=[
                    {
                        "role": "system",
                        "content": "You are an expert freight forwarding consultant and trainer with 15+ years of industry experience. You provide comprehensive, in-depth, and highly detailed explanations based on rate sheet data. You excel at teaching complex concepts, providing step-by-step walkthroughs, and explaining the business context behind technical information. You synthesize information from multiple sources and present it in a professional, educational format that helps users become proficient. You provide extensive detail when questions ask for explanations, walkthroughs, or understanding - never oversimplify or provide only basic information when depth is requested."
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                temperature=0.7,
                max_tokens=2500
            )
            
            answer = response.choices[0].message.content.strip()
            logger.info(f"Generated answer (length: {len(answer)} chars)")
            return answer
        
        except Exception as e:
            logger.error(f"Error generating answer: {e}", exc_info=True)
            return f"Unable to generate answer due to an error. Please review the rate sheets below for details. Error: {str(e)}"
    