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

CRITICAL: Only classify as "rate_inquiry" if the email EXPLICITLY mentions:
- Shipping rates, freight rates, or pricing
- Specific ports/locations (origin AND/OR destination)
- Container types (20ft, 40ft, FCL, LCL)
- Cargo/shipping/freight/logistics context

If the email is casual, personal, or unrelated to freight/shipping, classify as "general" with LOW confidence (0.2-0.4).

EMAIL SUBJECT: {subject or "Not provided"}
FROM: {from_email or "Not provided"}
EMAIL CONTENT:
{email_content}

EXAMPLES:
- "What are your rates from Mumbai to Singapore for 20ft containers?" → rate_inquiry (0.95)
- "Please quote for shipping from India to Thailand" → rate_inquiry (0.90)
- "its very late now" → general (0.3) - NOT freight related
- "Hello, how are you?" → general (0.2) - casual message
- "Where is my shipment BL12345?" → tracking (0.9)

Classify the intent:
1. **Intent** (choose one):
   - "rate_inquiry": ONLY if asking about shipping rates/pricing with freight context
   - "tracking": Asking about shipment status/tracking
   - "booking": Requesting to book a shipment
   - "general": Casual messages, greetings, or non-freight inquiries

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
    "requires_graph_traversal": false
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
            "vessel", "carrier", "transit", "destination", "origin"
        ])
        
        # Determine intent - require freight context for rate_inquiry
        if freight_context and any(word in content_lower for word in ["rate", "price", "quote", "quotation", "cost", "pricing"]):
            intent = "rate_inquiry"
            confidence = 0.7
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
        
        return {
            "intent": intent,
            "confidence": confidence,
            "entities": entities,
            "query_type": "fuzzy_match",
            "requires_structured_data": intent == "rate_inquiry" and freight_context,
            "requires_vector_search": freight_context,
            "requires_graph_traversal": False
        }
