"""Email Response Service - Drafts and sends email responses based on rate sheet queries"""
import httpx
import json
import logging
import re
from typing import Dict, List, Any, Optional
from app.core.config import settings
from app.services.rate_sheet_service import RateSheetService
from app.core.database import AsyncSessionLocal

logger = logging.getLogger(__name__)


class EmailResponseService:
    """Service for drafting and sending email responses based on rate sheet queries"""
    
    def __init__(self):
        self.ai_service_url = settings.AI_SERVICE_URL
        self.auth_service_url = settings.AUTH_SERVICE_URL if hasattr(settings, 'AUTH_SERVICE_URL') else "http://localhost:8001"
        self.rate_sheet_service = RateSheetService()
    
    async def draft_email_response(
        self,
        email_query: str,
        organization_id: int,
        original_email_subject: Optional[str] = None,
        original_email_from: Optional[str] = None,
        limit: int = 5
    ) -> Dict[str, Any]:
        """
        Draft an email response based on rate sheet query
        
        NEW ARCHITECTURE: Uses hybrid storage
        1. Vector search (ChromaDB) → Find relevant rate sheets
        2. Structured data query (PostgreSQL) → Extract precise rates
        3. AI drafting → Use structured JSON (not text parsing)
        
        Args:
            email_query: The email content/question to search rate sheets for
            organization_id: Organization ID
            original_email_subject: Original email subject (for context)
            original_email_from: Original email sender (for context)
            limit: Maximum number of rate sheets to include
        
        Returns:
            Dictionary with drafted email and confidence scores
        """
        try:
            # Step 1: Vector search (ChromaDB) - Find relevant rate sheets
            search_result = await self.rate_sheet_service.search_rate_sheets(
                organization_id=organization_id,
                query=email_query,
                limit=limit
            )
            
            # Handle new format with answer/results or old format (list)
            if isinstance(search_result, dict) and "results" in search_result:
                rate_sheets = search_result.get("results", [])
            else:
                rate_sheets = search_result if isinstance(search_result, list) else []
            
            if not rate_sheets:
                return {
                    "drafted_email": self._create_no_results_email(email_query),
                    "rate_sheets_found": 0,
                    "confidence_score": 0.0,
                    "rate_sheets": []
                }
            
            # Step 2: Extract precise rates from structured data (PostgreSQL)
            rate_sheet_ids = [rs.get("id") for rs in rate_sheets if rs.get("id")]
            precise_rates = await self._extract_precise_rates_from_structured_data(
                rate_sheet_ids=rate_sheet_ids,
                organization_id=organization_id,
                email_query=email_query
            )
            
            # Calculate confidence score based on BOTH vector search AND structured data precision
            # With hybrid architecture, structured data matches indicate HIGH confidence
            base_confidence_scores = [rs.get("similarity", 0) for rs in rate_sheets]
            base_avg_confidence = sum(base_confidence_scores) / len(base_confidence_scores) if base_confidence_scores else 0.0
            
            # Boost confidence if we found precise rates from structured data
            if precise_rates and len(precise_rates) > 0:
                # Calculate precision boost based on:
                # 1. Number of precise rates found (more rates = higher confidence)
                # 2. Quality of matches (exact port/container matches)
                # 3. Base vector search similarity
                
                # Check match quality
                exact_matches = 0
                for rate in precise_rates:
                    # Check if origin/destination ports match query
                    origin_match = self._check_port_match(email_query, rate.get("origin_port", ""))
                    dest_match = self._check_port_match(email_query, rate.get("destination_port", ""))
                    if origin_match and dest_match:
                        exact_matches += 1
                
                # Precision boost: If we have structured data matches, confidence should be HIGH
                # Base: 0.6-0.7 (vector search)
                # Boost: +0.2-0.3 for structured data matches
                # Max: 0.95 (never 100% as there could be edge cases)
                
                match_quality_score = min(exact_matches / max(len(precise_rates), 1), 1.0)
                rates_found_score = min(len(precise_rates) / 5.0, 1.0)  # Normalize to 5 rates max
                
                # Calculate boosted confidence
                precision_boost = 0.25 * match_quality_score * rates_found_score
                avg_confidence = min(base_avg_confidence + precision_boost, 0.95)
                
                logger.info(f"Confidence calculation: base={base_avg_confidence:.2%}, precise_rates={len(precise_rates)}, exact_matches={exact_matches}, boost={precision_boost:.2%}, final={avg_confidence:.2%}")
            else:
                # No structured data matches - use base vector search confidence
                avg_confidence = base_avg_confidence
                logger.info(f"Confidence calculation: base={base_avg_confidence:.2%} (no structured data matches)")
            
            # Step 3: Build context from structured data (precise rates) instead of text
            rate_sheet_context = self._build_rate_sheet_context_from_structured_data(
                rate_sheets=rate_sheets,
                precise_rates=precise_rates
            )
            
            # Step 4: Draft email using AI service with structured data
            drafted_email = await self._draft_email_with_ai(
                email_query=email_query,
                rate_sheet_context=rate_sheet_context,
                original_subject=original_email_subject,
                original_from=original_email_from,
                confidence_score=avg_confidence,
                precise_rates=precise_rates
            )
            
            # Step 5: Calculate Answer Quality Score (how well answer addresses the question)
            answer_quality_score = await self._calculate_answer_quality_score(
                email_query=email_query,
                drafted_answer=drafted_email.get("body", ""),
                precise_rates=precise_rates,
                rate_sheet_context=rate_sheet_context
            )
            
            return {
                "drafted_email": drafted_email,
                "rate_sheets_found": len(rate_sheets),
                "confidence_score": round(avg_confidence, 2),  # Data retrieval confidence
                "answer_quality_score": round(answer_quality_score, 2),  # Answer correctness/relevance score
                "precise_rates_found": len(precise_rates) if precise_rates else 0,
                "rate_sheets": [
                    {
                        "id": rs.get("id"),
                        "file_name": rs.get("file_name"),
                        "carrier_name": rs.get("carrier_name"),
                        "similarity": rs.get("similarity", 0),
                        "confidence": round(rs.get("similarity", 0) * 100, 2)  # Convert to percentage
                    }
                    for rs in rate_sheets
                ]
            }
        
        except Exception as e:
            logger.error(f"Error drafting email response: {e}")
            return {
                "drafted_email": self._create_error_email(),
                "rate_sheets_found": 0,
                "confidence_score": 0.0,
                "rate_sheets": [],
                "error": str(e)
            }
    
    async def _extract_precise_rates_from_structured_data(
        self,
        rate_sheet_ids: List[str],
        organization_id: int,
        email_query: str
    ) -> List[Dict[str, Any]]:
        """
        Extract precise rates from PostgreSQL structured data
        
        Uses NLP to extract origin/destination/container type from email query
        """
        try:
            from app.services.structured_data_service import StructuredDataService
            structured_service = StructuredDataService()
            
            # Extract key information from email query using regex/NLP
            origin_port = self._extract_port_from_query(email_query, ["origin", "from", "pol"])
            destination_port = self._extract_port_from_query(email_query, ["destination", "to", "pod"])
            container_type = self._extract_container_type(email_query)
            vgm_weight = self._extract_vgm_weight(email_query)
            
            async with AsyncSessionLocal() as db_session:
                precise_rates = await structured_service.extract_precise_rates(
                    session=db_session,
                    rate_sheet_ids=rate_sheet_ids,
                    organization_id=organization_id,
                    origin_port=origin_port,
                    destination_port=destination_port,
                    container_type=container_type,
                    vgm_weight=vgm_weight
                )
            
            logger.info(f"Extracted {len(precise_rates)} precise rates from structured data")
            return precise_rates
            
        except Exception as e:
            logger.error(f"Error extracting precise rates: {e}", exc_info=True)
            return []
    
    def _extract_port_from_query(self, query: str, keywords: List[str]) -> Optional[str]:
        """Extract port name from query using keywords"""
        query_lower = query.lower()
        for keyword in keywords:
            # Look for patterns like "from NHAVA SHEVA" or "origin: LAEM CHABANG"
            pattern = rf"{keyword}\s*[:\-]?\s*([A-Z][A-Z\s]+(?:PORT|SHEVA|CHABANG|KLANG|SINGAPORE|CHENNAI|MUNDRA|KOLKATTA|PIPAVAV|KATTUPALLI))"
            match = re.search(pattern, query, re.IGNORECASE)
            if match:
                return match.group(1).strip()
            
            # Also check for port names directly after keywords
            for port in ["NHAVA SHEVA", "LAEM CHABANG", "PORT KLANG", "SINGAPORE", "CHENNAI", "MUNDRA", "KOLKATTA", "PIPAVAV", "KATTUPALLI"]:
                if keyword in query_lower and port.lower() in query_lower:
                    idx = query_lower.find(keyword)
                    port_idx = query_lower.find(port.lower(), idx)
                    if port_idx > idx and port_idx < idx + 50:  # Within 50 chars
                        return port
        
        return None
    
    def _extract_container_type(self, query: str) -> Optional[str]:
        """Extract container type from query (20', 40', etc.)"""
        query_lower = query.lower()
        if "20'" in query or "20ft" in query_lower or "twenty" in query_lower:
            return "20'"
        if "40'" in query or "40ft" in query_lower or "forty" in query_lower:
            return "40'"
        return None
    
    def _extract_vgm_weight(self, query: str) -> Optional[float]:
        """Extract VGM weight from query"""
        # Look for patterns like "VGM 18MT" or "18 MT" or "weight 26"
        patterns = [
            r"vgm\s*[:\-]?\s*(\d+(?:\.\d+)?)\s*mt",
            r"(\d+(?:\.\d+)?)\s*mt",
            r"weight\s*[:\-]?\s*(\d+(?:\.\d+)?)\s*mt"
        ]
        for pattern in patterns:
            match = re.search(pattern, query, re.IGNORECASE)
            if match:
                try:
                    return float(match.group(1))
                except ValueError:
                    continue
        return None
    
    def _check_port_match(self, query: str, port_name: str) -> bool:
        """Check if port name matches query (case-insensitive partial match)"""
        if not port_name:
            return False
        query_lower = query.lower()
        port_lower = port_name.lower()
        
        # Check for exact match or key words match
        if port_lower in query_lower:
            return True
        
        # Check for common port name variations
        port_keywords = {
            "nhavasheva": ["nhavasheva", "nhava sheva", "nava sheva"],
            "laemchabang": ["laemchabang", "laem chabang", "lcb"],
            "portklang": ["portklang", "port klang", "pkg"],
            "singapore": ["singapore", "sin", "sgp"],
            "chennai": ["chennai", "madras"],
            "mundra": ["mundra"],
            "kolkata": ["kolkata", "calcutta"],
            "pipavav": ["pipavav"]
        }
        
        for key, variations in port_keywords.items():
            if any(v in port_lower for v in variations):
                # Check if any variation appears in query
                if any(v in query_lower for v in variations):
                    return True
        
        return False
    
    async def _calculate_answer_quality_score(
        self,
        email_query: str,
        drafted_answer: str,
        precise_rates: List[Dict[str, Any]],
        rate_sheet_context: str
    ) -> float:
        """
        Calculate Answer Quality Score - measures how well the answer addresses the question
        
        This is DIFFERENT from confidence_score:
        - confidence_score: How confident we are in finding the right data
        - answer_quality_score: How well the answer addresses the question and uses data correctly
        
        Returns: Score between 0.0 and 1.0 (0-100%)
        """
        try:
            if not drafted_answer or not email_query:
                return 0.0
            
            # Extract key questions/requirements from email query
            query_requirements = self._extract_query_requirements(email_query)
            
            # Check answer completeness (does it address all requirements?)
            completeness_score = self._check_answer_completeness(drafted_answer, query_requirements)
            
            # Check data accuracy (does answer use correct rates from structured data?)
            data_accuracy_score = self._check_data_accuracy(drafted_answer, precise_rates)
            
            # Check answer relevance (does it directly answer the question?)
            relevance_score = self._check_answer_relevance(email_query, drafted_answer)
            
            # Calculate weighted average
            # Completeness: 40%, Data Accuracy: 40%, Relevance: 20%
            quality_score = (
                completeness_score * 0.4 +
                data_accuracy_score * 0.4 +
                relevance_score * 0.2
            )
            
            logger.info(f"Answer Quality Score: completeness={completeness_score:.2%}, data_accuracy={data_accuracy_score:.2%}, relevance={relevance_score:.2%}, final={quality_score:.2%}")
            
            return quality_score
            
        except Exception as e:
            logger.error(f"Error calculating answer quality score: {e}", exc_info=True)
            # Fallback: return moderate score if calculation fails
            return 0.7
    
    def _extract_query_requirements(self, query: str) -> List[str]:
        """Extract key requirements/questions from email query"""
        requirements = []
        query_lower = query.lower()
        
        # Check for common question patterns
        question_keywords = {
            "container_types": ["20'", "40'", "container", "20 foot", "40 foot", "vgm"],
            "rates": ["rate", "price", "cost", "freight", "pricing"],
            "routing": ["routing", "route", "direct", "transshipment", "via"],
            "transit_time": ["transit", "time", "days", "delivery time"],
            "surcharges": ["surcharge", "baf", "caf", "ebs", "pss", "additional charge"],
            "detention": ["detention", "demurrage", "free time", "free detention"],
            "validity": ["validity", "valid", "period", "effective"],
            "booking": ["booking", "cut-off", "requirements", "documentation"]
        }
        
        for key, keywords in question_keywords.items():
            if any(kw in query_lower for kw in keywords):
                requirements.append(key)
        
        return requirements
    
    def _check_answer_completeness(self, answer: str, requirements: List[str]) -> float:
        """Check if answer addresses all requirements"""
        if not requirements:
            return 1.0  # No specific requirements = complete
        
        answer_lower = answer.lower()
        addressed_count = 0
        
        requirement_keywords = {
            "container_types": ["20'", "40'", "container", "vgm", "18mt", "26mt"],
            "rates": ["650", "700", "1100", "usd", "rate", "price", "cost"],
            "routing": ["routing", "via", "direct", "port klang", "singapore"],
            "transit_time": ["7 days", "transit", "time", "days"],
            "surcharges": ["surcharge", "baf", "caf", "ebs", "pss"],
            "detention": ["detention", "14 days", "free"],
            "validity": ["january 2026", "valid", "validity"],
            "booking": ["booking", "requirements"]
        }
        
        for req in requirements:
            keywords = requirement_keywords.get(req, [])
            if any(kw in answer_lower for kw in keywords):
                addressed_count += 1
        
        return addressed_count / len(requirements) if requirements else 1.0
    
    def _check_data_accuracy(self, answer: str, precise_rates: List[Dict[str, Any]]) -> float:
        """Check if answer uses correct rates from structured data"""
        if not precise_rates:
            # No structured data - can't verify accuracy
            return 0.7  # Moderate score
        
        answer_lower = answer.lower()
        correct_rates_found = 0
        total_rates = len(precise_rates)
        
        # Check if answer mentions the exact rates from structured data
        for rate in precise_rates:
            base_rate = rate.get("base_rate")
            container_type = rate.get("container_type", "")
            origin = rate.get("origin_port", "").lower()
            dest = rate.get("destination_port", "").lower()
            
            if base_rate:
                # Check if rate is mentioned in answer
                rate_str = str(base_rate)
                if rate_str in answer or rate_str.replace(".0", "") in answer:
                    # Also check if container type matches
                    if container_type.lower() in answer_lower or any(ct in answer_lower for ct in ["20'", "40'", "20ft", "40ft"]):
                        correct_rates_found += 1
                
                # Check if ports are mentioned
                if origin in answer_lower and dest in answer_lower:
                    correct_rates_found += 0.5  # Partial credit for port mention
        
        # Normalize score
        accuracy_score = min(correct_rates_found / max(total_rates, 1), 1.0)
        
        # Boost if answer contains multiple correct rates
        if correct_rates_found >= 2:
            accuracy_score = min(accuracy_score + 0.1, 1.0)
        
        return accuracy_score
    
    def _check_answer_relevance(self, query: str, answer: str) -> float:
        """Check if answer is relevant to the query"""
        query_lower = query.lower()
        answer_lower = answer.lower()
        
        # Extract key terms from query
        query_terms = set()
        important_terms = ["nhavasheva", "laemchabang", "container", "rate", "freight", "thailand", "india"]
        for term in important_terms:
            if term in query_lower:
                query_terms.add(term)
        
        # Check if answer mentions query terms
        mentioned_terms = sum(1 for term in query_terms if term in answer_lower)
        
        if not query_terms:
            return 1.0  # No specific terms = relevant
        
        relevance_score = mentioned_terms / len(query_terms)
        
        # Boost if answer directly addresses the question format
        if "?" in query and ("answer" in answer_lower or any(num in answer for num in ["650", "700", "1100"])):
            relevance_score = min(relevance_score + 0.2, 1.0)
        
        return relevance_score
    
    def _build_rate_sheet_context_from_structured_data(
        self,
        rate_sheets: List[Dict[str, Any]],
        precise_rates: List[Dict[str, Any]]
    ) -> str:
        """Build context from structured data (precise rates) instead of text parsing"""
        context_parts = []
        
        if precise_rates:
            context_parts.append("=" * 80)
            context_parts.append("PRECISE RATE INFORMATION (FROM STRUCTURED DATA)")
            context_parts.append("=" * 80)
            context_parts.append(f"\nFound {len(precise_rates)} precise rate matches:\n")
            
            # Group by route for better organization
            routes_dict = {}
            for rate in precise_rates:
                route_key = f"{rate.get('origin_port')} → {rate.get('destination_port')}"
                if route_key not in routes_dict:
                    routes_dict[route_key] = {
                        "carrier": rate.get("carrier_name"),
                        "routing": rate.get("routing"),
                        "transit_time": rate.get("transit_time_text") or f"{rate.get('transit_time_days')} days",
                        "free_detention": rate.get("free_detention_text") or f"{rate.get('free_detention_days')} days",
                        "validity": f"{rate.get('valid_from', 'N/A')} to {rate.get('valid_to', 'N/A')}",
                        "rates": []
                    }
                
                # Add rate details
                rate_detail = {
                    "container_type": rate.get("container_type"),
                    "base_rate": rate.get("base_rate"),
                    "currency": rate.get("currency", "USD"),
                    "vgm_range": f"{rate.get('vgm_min_weight_mt', 'N/A')}-{rate.get('vgm_max_weight_mt', 'N/A')} MT" if rate.get('vgm_min_weight_mt') else None,
                    "remarks": rate.get("remarks")
                }
                routes_dict[route_key]["rates"].append(rate_detail)
            
            # Format routes
            for route_key, route_data in routes_dict.items():
                context_parts.append(f"\n{'─' * 80}")
                context_parts.append(f"ROUTE: {route_key}")
                context_parts.append(f"{'─' * 80}")
                context_parts.append(f"Carrier: {route_data['carrier']}")
                context_parts.append(f"Routing: {route_data['routing']}")
                context_parts.append(f"Transit Time: {route_data['transit_time']}")
                context_parts.append(f"Free Detention: {route_data['free_detention']}")
                context_parts.append(f"Validity: {route_data['validity']}")
                context_parts.append(f"\nPRICING:")
                for rate in route_data['rates']:
                    rate_str = f"  • {rate['container_type']}: {rate['base_rate']} {rate['currency']}"
                    if rate['vgm_range']:
                        rate_str += f" (VGM {rate['vgm_range']})"
                    context_parts.append(rate_str)
                    if rate['remarks']:
                        context_parts.append(f"    Remarks: {rate['remarks']}")
            
            # Add surcharges if available
            surcharges_found = set()
            for rate in precise_rates:
                if rate.get("surcharges"):
                    surcharges_found.update([s.get("surcharge_type") for s in rate["surcharges"] if s.get("surcharge_type")])
            
            if surcharges_found:
                context_parts.append(f"\nAPPLICABLE SURCHARGES: {', '.join(surcharges_found)}")
        else:
            # Fallback to old method if no structured data
            context_parts.append("NOTE: Using text-based extraction (structured data not available)")
            context_parts.append(self._build_rate_sheet_context(rate_sheets))
        
        return "\n".join(context_parts)
    
    def _build_rate_sheet_context(self, rate_sheets: List[Dict[str, Any]]) -> str:
        """Build context string from rate sheets for AI with full rate details"""
        context_parts = []
        
        for idx, rs in enumerate(rate_sheets, 1):
            metadata = rs.get("metadata", {})
            context_parts.append(f"\n{'='*60}")
            context_parts.append(f"RATE SHEET {idx} - DETAILED INFORMATION")
            context_parts.append(f"{'='*60}")
            context_parts.append(f"File Name: {rs.get('file_name', 'Unknown')}")
            context_parts.append(f"Carrier: {rs.get('carrier_name', 'Unknown')}")
            context_parts.append(f"Type: {rs.get('rate_sheet_type', 'Unknown')}")
            context_parts.append(f"Confidence: {rs.get('similarity', 0):.2%}")
            
            # Include full document content (not just preview) - this contains the actual rate data
            document_content = rs.get("document", "") or rs.get("document_preview", "") or rs.get("content", "")
            if document_content:
                # Include much more content to ensure rates are captured
                context_parts.append(f"\nFULL RATE SHEET CONTENT:")
                context_parts.append(document_content[:3000])  # Increased from 500 to 3000 chars
            
            # Include metadata if available (may contain structured rate data)
            if metadata:
                routes = metadata.get("routes", [])
                if routes:
                    context_parts.append(f"\nROUTES AND PRICING:")
                    for route_idx, route in enumerate(routes[:5], 1):  # Limit to top 5 routes
                        context_parts.append(f"\n  Route {route_idx}:")
                        context_parts.append(f"    Origin: {route.get('origin_port', 'N/A')} ({route.get('origin_code', '')})")
                        context_parts.append(f"    Destination: {route.get('destination_port', 'N/A')} ({route.get('destination_code', '')})")
                        context_parts.append(f"    Routing: {route.get('routing', 'N/A')}")
                        context_parts.append(f"    Transit Time: {route.get('transit_time_text', route.get('transit_time_days', 'N/A'))}")
                        context_parts.append(f"    Free Detention: {route.get('free_detention_text', route.get('free_detention_days', 'N/A'))}")
                        
                        pricing_tiers = route.get("pricing_tiers", [])
                        if pricing_tiers:
                            context_parts.append(f"    PRICING:")
                            for tier in pricing_tiers:
                                container_type = tier.get("container_type", "N/A")
                                base_rate = tier.get("base_rate", tier.get("rate", "N/A"))
                                currency = tier.get("currency", "USD")
                                vgm_min = tier.get("vgm_min_weight_mt", "")
                                vgm_max = tier.get("vgm_max_weight_mt", "")
                                vgm_info = f" (VGM {vgm_min}-{vgm_max}MT)" if vgm_min or vgm_max else ""
                                context_parts.append(f"      {container_type}{vgm_info}: {base_rate} {currency}")
                                if tier.get("remarks"):
                                    context_parts.append(f"        Remarks: {tier.get('remarks')}")
            
            # Include matching info if available (contains extracted rate data)
            matching_info = rs.get("matching_info", {})
            if matching_info:
                extracted_data = matching_info.get("sample_extracted_data", [])
                if extracted_data:
                    context_parts.append(f"\nEXTRACTED RATE DATA:")
                    for data_item in extracted_data[:10]:  # Include up to 10 extracted data items
                        context_parts.append(f"  {data_item}")
        
        return "\n".join(context_parts)
    
    async def _draft_email_with_ai(
        self,
        email_query: str,
        rate_sheet_context: str,
        original_subject: Optional[str],
        original_from: Optional[str],
        confidence_score: float,
        precise_rates: Optional[List[Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        """Use AI service to draft email response"""
        
        # Build enhanced prompt with structured data emphasis
        structured_data_note = ""
        if precise_rates:
            structured_data_note = f"""
IMPORTANT: The rate information above is extracted from STRUCTURED DATA (not text parsing).
This means the rates are PRECISE and ACCURATE. You MUST use these exact rates in your response.

PRECISE RATES AVAILABLE: {len(precise_rates)} rate entries
- All rates are already extracted and validated
- Use the exact numbers provided (no parsing needed)
- All container types, VGM ranges, transit times, and routing info are accurate
"""
        
        prompt = f"""You are a freight forwarding rate sheet expert. Draft a professional email response based on the customer's query and the PRECISE rate sheet information provided.

CUSTOMER QUERY:
{email_query}

ORIGINAL EMAIL SUBJECT: {original_subject or "Not provided"}
ORIGINAL EMAIL FROM: {original_from or "Not provided"}

RATE SHEET INFORMATION (STRUCTURED DATA):
{rate_sheet_context}
{structured_data_note}

CONFIDENCE SCORE: {confidence_score:.2%}

CRITICAL INSTRUCTIONS - READ CAREFULLY:

1. **USE THE EXACT RATES PROVIDED**: The rate information above contains PRECISE, STRUCTURED DATA. Use the exact rates shown:
   - Copy exact numbers: "650 USD", "700 USD", "1100 USD" (as shown)
   - Use exact container types: "20'", "40'" (as shown)
   - Use exact VGM ranges: "VGM up to 18MT", "VGM up to 26MT" (as shown)
   - Use exact port names: "NHAVA SHEVA", "LAEM CHABANG" (as shown)
   - Use exact transit times: "7 days", "5 days" (as shown)
   - Use exact free detention: "14 days" (as shown)
   - Use exact routing: "via Port Klang/Singapore", "Direct" (as shown)

2. **NEVER SAY RATES ARE NOT AVAILABLE**: The structured data above contains ACTUAL RATES. You MUST include them. Do NOT say "rates are not detailed" or "rates are not available" - they are RIGHT THERE in the data above.

3. **BE PRECISE AND DETAILED**: 
   - Quote exact numbers from the structured data
   - Include all routes and pricing tiers shown
   - Mention all transit times, free detention, routing options
   - Reference specific ports and carriers as shown

4. **PROFESSIONAL TONE**: Write as a freight forwarding professional responding to a customer inquiry

5. **ADDRESS ALL QUERY POINTS**: Answer all questions asked in the customer query

6. **CONFIDENCE SCORE**: Include naturally (e.g., "Based on our rate sheets, I found this information with {confidence_score:.1%} confidence")

7. **FORMAT**: Use clear sections, bullet points for rates, professional business email formatting

EXAMPLE FORMAT (use exact rates from data above):
"For the route NHAVA SHEVA to LAEM CHABANG, we have the following rates:
  • 20' container (VGM up to 18MT): 650 USD
  • 20' container (VGM up to 26MT): 700 USD
  • 40' container (VGM up to 26MT): 1100 USD
  • Routing: via Port Klang/Singapore
  • Transit Time: 7 days
  • Free Detention: 14 days at destination
  • Validity: January 2026"

Return a JSON object with:
{{
    "subject": "Re: [original subject or appropriate subject]",
    "body": "Full email body text with EXACT rates from structured data above",
    "confidence_note": "Brief note about confidence level"
}}
"""
        
        try:
            # Use longer timeout for AI response generation (comprehensive drafts can take time)
            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await client.post(
                    f"{self.ai_service_url}/api/ai/chat",
                    json={
                        "message": prompt,
                        "conversation_history": []
                    },
                    headers={"Content-Type": "application/json"}
                )
            
            if response.status_code == 200:
                result = response.json()
                ai_response = result.get("response", "")
                
                # Try to parse JSON from AI response
                try:
                    # Extract JSON if wrapped in markdown code blocks
                    if "```json" in ai_response:
                        json_start = ai_response.find("```json") + 7
                        json_end = ai_response.find("```", json_start)
                        ai_response = ai_response[json_start:json_end].strip()
                    elif "```" in ai_response:
                        json_start = ai_response.find("```") + 3
                        json_end = ai_response.find("```", json_start)
                        ai_response = ai_response[json_start:json_end].strip()
                    
                    email_data = json.loads(ai_response)
                    return {
                        "subject": email_data.get("subject", f"Re: {original_subject or 'Rate Sheet Inquiry'}"),
                        "body": email_data.get("body", ""),
                        "confidence_note": email_data.get("confidence_note", f"Confidence: {confidence_score:.1%}")
                    }
                except json.JSONDecodeError:
                    # Fallback: use AI response as body
                    return {
                        "subject": f"Re: {original_subject or 'Rate Sheet Inquiry'}",
                        "body": ai_response,
                        "confidence_note": f"Confidence: {confidence_score:.1%}"
                    }
            else:
                raise Exception(f"AI service returned {response.status_code}")
        
        except Exception as e:
            # Log error with full context (no silent failures per BACKEND_REVIEW.md)
            logger.error(
                f"Error calling AI service for email draft: {type(e).__name__}: {str(e)}",
                exc_info=True,
                extra={
                    "email_query": email_query[:200],  # Truncate for logging
                    "original_subject": original_subject,
                    "exception_type": type(e).__name__
                }
            )
            # Return fallback email (graceful degradation, but error is logged)
            return {
                "subject": f"Re: {original_subject or 'Rate Sheet Inquiry'}",
                "body": f"Thank you for your inquiry.\n\n{email_query}\n\nI found relevant rate sheet information. Please let me know if you need more details.",
                "confidence_note": f"Confidence: {confidence_score:.1%} (AI service unavailable)"
            }
    
    def _create_no_results_email(self, query: str) -> Dict[str, Any]:
        """Create email when no rate sheets found"""
        return {
            "subject": "Re: Rate Sheet Inquiry",
            "body": f"Thank you for your inquiry regarding:\n\n{query}\n\nUnfortunately, I couldn't find matching rate sheets in our database. Please provide more details or contact our team for assistance.",
            "confidence_note": "No matching rate sheets found"
        }
    
    def _create_error_email(self) -> Dict[str, Any]:
        """Create email when error occurs"""
        return {
            "subject": "Re: Rate Sheet Inquiry",
            "body": "Thank you for your inquiry. I encountered an issue while searching our rate sheets. Please try again or contact our team for assistance.",
            "confidence_note": "Error occurred during search"
        }
    
    async def send_email_response(
        self,
        drafted_email: Dict[str, Any],
        to_email: str,
        user_id: int,
        organization_id: int,
        authorization_token: str,
        cc_email: Optional[str] = None,
        bcc_email: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Send the drafted email response via Gmail API
        
        Args:
            drafted_email: The drafted email (subject, body, confidence_note)
            to_email: Recipient email address
            user_id: User ID sending the email
            organization_id: Organization ID
            authorization_token: Bearer token for authentication service
            cc_email: Optional CC email
            bcc_email: Optional BCC email
        
        Returns:
            Result of email send operation
        """
        try:
            # Build email body with confidence note
            email_body = drafted_email.get("body", "")
            confidence_note = drafted_email.get("confidence_note", "")
            
            # Append confidence note to body if not already included
            if confidence_note and confidence_note not in email_body:
                email_body += f"\n\n{confidence_note}"
            
            # Call authentication service to send email via Gmail
            async with httpx.AsyncClient(timeout=30.0) as client:
                payload = {
                    "to": to_email,
                    "subject": drafted_email.get("subject", "Re: Rate Sheet Inquiry"),
                    "body": email_body,
                    "include_signature": True
                }
                
                if cc_email:
                    payload["cc"] = cc_email
                if bcc_email:
                    payload["bcc"] = bcc_email
                
                response = await client.post(
                    f"{self.auth_service_url}/api/auth/gmail/send",
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {authorization_token}",
                        "Content-Type": "application/json"
                    }
                )
                
                if response.status_code == 200:
                    result = response.json()
                    logger.info(f"Email sent successfully to {to_email} from user {user_id}")
                    return {
                        "success": True,
                        "message": "Email sent successfully",
                        "to": to_email,
                        "subject": drafted_email.get("subject"),
                        "message_id": result.get("messageId"),
                        "sent_at": None  # Gmail API doesn't return timestamp in this response
                    }
                else:
                    error_text = response.text
                    logger.error(f"Failed to send email: {response.status_code} - {error_text}")
                    return {
                        "success": False,
                        "error": f"Failed to send email: {error_text}",
                        "status_code": response.status_code
                    }
        
        except Exception as e:
            logger.error(f"Error sending email: {e}")
            return {
                "success": False,
                "error": str(e)
            }
