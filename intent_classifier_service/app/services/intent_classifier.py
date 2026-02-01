"""
Intent Classifier Service
Classifies email intents and extracts structured query parameters
"""
import logging
import httpx
import json
from typing import Dict, Any, Optional, List
from app.core.config import settings

logger = logging.getLogger(__name__)


class IntentClassifier:
    """Service for classifying email intents and extracting query parameters"""
    
    def __init__(self):
        self.ai_service_url = settings.AI_SERVICE_URL
    
    async def classify_intent(
        self,
        email_content: str,
        subject: Optional[str] = None,
        from_email: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Classify email intent and extract structured query parameters
        
        Returns:
        {
            "intent": "rate_inquiry" | "tracking" | "booking" | "general",
            "confidence": 0.0-1.0,
            "entities": {
                "origin_port": "NHAVA SHEVA",
                "destination_port": "LAEM CHABANG",
                "container_type": "20'",
                "cargo_type": "steel coils",
                "quantity": "50 tons",
                "carrier_preference": "MAERSK",
                "date_range": {...}
            },
            "query_type": "exact_match" | "fuzzy_match" | "comparison",
            "requires_structured_data": true/false
        }
        """
        try:
            # Build prompt for intent classification
            prompt = f"""You are an expert freight forwarding email classifier. Analyze the following email and classify its intent.

CRITICAL: Classify as "rate_inquiry" if the email asks about data that comes from rate sheet documents:
- Shipping rates, freight rates, or pricing (e.g. "rates from X to Y", "how much", "quote")
- Volume/TEU/throughput (e.g. "total TEUs for Laem Chabang in January", "how many containers did X process", "volume by port")
- Specific ports/locations (origin AND/OR destination) with freight/rate-sheet context
- Container types (20ft, 40ft, FCL, LCL) or list of routes/costing

Classify as "general" ONLY if the email is casual, personal, or clearly unrelated (e.g. "Hello", "how are you", "its very late").
Do NOT classify as "general" when the user asks for TEUs, volume, container counts, or rates by location/month – those are rate_inquiry.

EMAIL SUBJECT: {subject or "Not provided"}
FROM: {from_email or "Not provided"}
EMAIL CONTENT:
{email_content}

EXAMPLES:
- "What are your rates from Mumbai to Singapore for 20ft containers?" → rate_inquiry (0.95)
- "Please quote for shipping from India to Thailand" → rate_inquiry (0.90)
- "What's the total TEUs for Laem Chabang in January?" → rate_inquiry (0.85), asks_for_volume_or_throughput=true – asking for volume count
- "How many containers did Maxicon process in January?" → rate_inquiry (0.85), asks_for_volume_or_throughput=true – volume/throughput count
- "Give me all containers list India has in February give the costs" → rate_inquiry (0.9), list_all_routes=true, region_filter="India", asks_for_volume_or_throughput=false – list ONLY routes where origin OR destination is in India
- "cheapest FCL rate in india in february" → rate_inquiry (0.9), answer_format=short, region_filter="India" – cheapest among routes that touch India (e.g. Singapore→Kattupalli), NOT the globally cheapest (e.g. Singapore→Laem Chabang is Thailand)
- "its very late now" → general (0.3) - NOT freight related
- "Hello, how are you?" → general (0.2) - casual message
- "Where is my shipment BL12345?" → tracking (0.9)

Classify the intent:
1. **Intent** (choose one):
   - "rate_inquiry": Asking about data from rate sheets – rates, pricing, TEUs, volume, container counts, totals by location/period, routes, costing
   - "tracking": Asking about shipment status/tracking
   - "booking": Requesting to book a shipment
   - "general": Casual messages, greetings, or clearly non–rate-sheet inquiries (not TEU/volume/rates by port)

2. **Confidence**: 
   - 0.9-1.0: Clear freight-related request with specific details
   - 0.7-0.9: Freight-related but missing some details
   - 0.3-0.6: Ambiguous, might be freight-related
   - 0.1-0.3: Not freight-related (casual/personal messages)

3. **Extract Entities** (ONLY if present in the email):
   - origin_port: Origin port name ONLY (e.g., "NHAVA SHEVA", "MUMBAI", "PORT KLANG")
     * Extract ONLY the port name, remove country names, parentheses, and extra text
     * Examples: "NHAVA SHEVA (Mumbai), India" → "NHAVA SHEVA"
     *            "Mumbai, India" → "MUMBAI"
     *            "PORT KLANG, Malaysia" → "PORT KLANG"
   - destination_port: Destination port name ONLY (e.g., "SINGAPORE", "LAEM CHABANG", "BANGKOK")
     * Same rules - extract ONLY port name, remove country/extra text
   - container_type: Container type (e.g., "20'", "40'", "FCL", "20ft", "40ft")
   - cargo_type: Type of cargo
   - Use null for any entity NOT mentioned in the email

4. **Answer preferences** (how to format the reply when returning rate sheet data):
   - answer_format: "list" if they want a list of routes/costs (e.g. "give me routes and costing", "list all routes"); "short" if they want 1-3 lines (e.g. "how much", "price"); "long" only if they explicitly ask to "explain", "compare", "how to", "why", "walkthrough", "detailed"
   - include_validity: true if they mention "validity", "valid dates", "valid from", "valid to", "with validity"
   - container_filter: "20'" ONLY if they explicitly ask for 20-foot/20ft/20' ONLY; "40'" ONLY if they ask for 40-foot/40ft/40' ONLY; null if they ask for "container sizes", "what container you have", "all containers", or both/unspecified
   - list_all_routes: true if they say "all routes", "every route", "provide all", "list all", "all the routes", "all containers list", "give me all containers"
   - sort_alphabetically: true if they say "sorted", "alphabetical", "alphabetically", "in order"
   - region_filter: set to a country/region name (e.g. "India", "Thailand") when the user asks for rates that involve that place (e.g. "containers list india has", "rates for india", "india in feb", "all routes to india", "cheapest rate in india", "cheapest FCL in india", "rate in india"). Use so the answer considers ONLY routes where origin OR destination is in that region (for lists or for single answers like "cheapest in India").
   - asks_for_volume_or_throughput: true ONLY when they ask for a COUNT or number (e.g. "how many containers", "total TEUs", "volume processed", "throughput", "container count"). Set FALSE when they ask for a list of rates/costs/pricing (e.g. "all containers list ... give the costs", "list of containers and rates", "container rates for India") – that is a rate list, not volume data.

Return ONLY valid JSON:
{{
    "intent": "general",
    "confidence": 0.3,
    "entities": {{
        "origin_port": null,
        "destination_port": null,
        "container_type": null,
        "cargo_type": null,
        "quantity": null,
        "carrier_preference": null,
        "date_range": null,
        "incoterms": null
    }},
    "query_type": "fuzzy_match",
    "requires_structured_data": false,
    "requires_vector_search": false,
    "requires_graph_traversal": false,
    "answer_preferences": {{
        "answer_format": "list",
        "include_validity": false,
        "container_filter": null,
        "list_all_routes": false,
        "sort_alphabetically": false,
        "region_filter": null,
        "asks_for_volume_or_throughput": false
    }}
}}"""

            # Call AI service
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{self.ai_service_url}/api/ai/chat",
                    json={
                        "message": prompt,
                        "conversation_history": [],
                        "temperature": 0.1  # Low temperature for consistent classification
                    }
                )
                response.raise_for_status()
                result = response.json()
                
                # Extract JSON from AI response
                content = result.get("response", "")
                
                # Try to parse JSON from response
                try:
                    # Look for JSON in the response
                    json_start = content.find("{")
                    json_end = content.rfind("}") + 1
                    if json_start >= 0 and json_end > json_start:
                        json_str = content[json_start:json_end]
                        classification = json.loads(json_str)
                        ap = classification.get("answer_preferences") or {}
                        ap.setdefault("answer_format", "list")
                        ap.setdefault("include_validity", False)
                        ap.setdefault("container_filter", None)
                        ap.setdefault("list_all_routes", False)
                        ap.setdefault("sort_alphabetically", False)
                        ap.setdefault("region_filter", None)
                        ap.setdefault("asks_for_volume_or_throughput", False)
                        classification["answer_preferences"] = ap
                    else:
                        # Fallback: basic classification
                        classification = self._fallback_classification(email_content, subject)
                except json.JSONDecodeError:
                    logger.warning("Failed to parse AI response as JSON, using fallback")
                    classification = self._fallback_classification(email_content, subject)
                
                return classification
                
        except Exception as e:
            logger.error(f"Error classifying intent: {e}")
            # Fallback to basic classification
            return self._fallback_classification(email_content, subject)
    
    def _fallback_classification(
        self,
        email_content: str,
        subject: Optional[str] = None
    ) -> Dict[str, Any]:
        """Fallback classification using keyword matching"""
        content_lower = f"{subject or ''} {email_content}".lower()
        
        # First check if content has ANY freight-related context
        freight_context = any(word in content_lower for word in [
            "ship", "freight", "cargo", "container", "port", "fcl", "lcl",
            "export", "import", "logistics", "consignment", "bl", "booking",
            "vessel", "carrier", "transit", "destination", "origin",
            "teu", "teus", "volume", "throughput"  # volume/TEU questions are rate-sheet data
        ])
        # Also treat as freight context if asking for TEU/volume by location (e.g. "total TEUs for Laem Chabang")
        volume_teu_question = any(phrase in content_lower for phrase in [
            "total teu", "teus for", "volume for", "how many container", "containers processed"
        ])
        if volume_teu_question:
            freight_context = True

        # Determine intent - require freight context for rate_inquiry
        if freight_context and any(word in content_lower for word in ["rate", "price", "quote", "quotation", "cost", "pricing"]):
            intent = "rate_inquiry"
            confidence = 0.7
        elif freight_context and any(word in content_lower for word in ["teu", "teus", "volume", "throughput", "total teu", "containers processed"]):
            intent = "rate_inquiry"
            confidence = 0.75
        elif freight_context and any(word in content_lower for word in ["track", "status", "where", "location", "delivery"]):
            intent = "tracking"
            confidence = 0.7
        elif freight_context and any(word in content_lower for word in ["book", "booking", "reserve", "schedule"]):
            intent = "booking"
            confidence = 0.7
        else:
            # No freight context - classify as general with low confidence
            intent = "general"
            confidence = 0.3
        
        # Extract basic entities (only if freight context exists)
        entities = {}
        
        if freight_context:
            # Common port patterns
            port_keywords = ["nhava sheva", "nhavasheva", "mumbai", "chennai", "delhi", "bangalore", 
                            "singapore", "hong kong", "dubai", "rotterdam", "los angeles",
                            "laem chabang", "bangkok", "port klang", "thailand", "india", "malaysia"]
            
            for keyword in port_keywords:
                if keyword in content_lower:
                    if "from" in content_lower:
                        entities["origin_port"] = keyword.upper()
                    elif "to" in content_lower:
                        entities["destination_port"] = keyword.upper()
        
        # Answer preferences from keywords
        ap = {"answer_format": "short", "include_validity": False, "container_filter": None, "list_all_routes": False, "sort_alphabetically": False, "region_filter": None}
        if any(w in content_lower for w in ["list all", "all routes", "every route", "provide all", "all the routes", "all containers list", "all containers", "give me all containers"]):
            ap["list_all_routes"] = True
            ap["answer_format"] = "list"
        if any(w in content_lower for w in ["validity", "valid dates", "valid from", "valid to", "with validity"]):
            ap["include_validity"] = True
        if any(w in content_lower for w in ["sorted", "alphabetical", "alphabetically", "in order"]):
            ap["sort_alphabetically"] = True
        # Only filter to one container type if they explicitly ask for "20 foot" or "40 foot" only (not "container sizes" or "what container")
        if any(w in content_lower for w in ["container sizes", "container size", "what container", "all container"]):
            ap["container_filter"] = None  # show both 20' and 40'
        elif "20" in content_lower and ("foot" in content_lower or "ft" in content_lower or "20'" in content_lower) and "40" not in content_lower:
            ap["container_filter"] = "20'"
        elif "40" in content_lower and ("foot" in content_lower or "ft" in content_lower or "40'" in content_lower) and "20" not in content_lower:
            ap["container_filter"] = "40'"
        if any(w in content_lower for w in ["routes", "routing", "costing", "costs", "rates"]) and not any(w in content_lower for w in ["explain", "how to", "why ", "compare", "detailed"]):
            ap["answer_format"] = "list"
        # Volume = count/number; rate list = costs/pricing. "containers list" + "costs" = rate list, not volume
        wants_rate_list = any(w in content_lower for w in ["costs", "rates", "cost", "rate", "pricing"]) and any(w in content_lower for w in ["containers list", "all containers", "container list", "list of container"])
        ap["asks_for_volume_or_throughput"] = False if wants_rate_list else any(w in content_lower for w in [
            "how many container", "how many teu", "containers processed", "volume processed",
            "teus processed", "container count", "volume target", "total teus", "location target"
        ])
        # Region filter: "in india", "for india", "to india", "india in", "cheapest ... india" → only routes involving that region
        if any(w in content_lower for w in ["india has", "for india", "to india", "india in", "in india", "rates india", "india feb", "india february", "rate in india"]) or ("india" in content_lower and any(w in content_lower for w in ["containers list", "all containers", "list all", "rates", "costs", "cheapest", "lowest", "fcl", "fcl rate"])):
            ap["region_filter"] = "India"

        return {
            "intent": intent,
            "confidence": confidence,
            "entities": entities,
            "query_type": "fuzzy_match",
            "requires_structured_data": intent == "rate_inquiry" and freight_context,
            "requires_vector_search": freight_context,
            "requires_graph_traversal": False,
            "answer_preferences": ap
        }
