"""
Email Response Service V2
Uses the proper agentic architecture:
Router (Intent Classifier) -> Orchestrator -> Validator (Decision Engine) -> Draft Generator

Flow:
1. Orchestrator: Coordinates SQL/Graph/Vector tools based on intent
2. Decision Engine: Validates results and calculates confidence
3. Draft Generator: Creates professional email response with validated data
"""
import httpx
import json
import logging
from typing import Dict, Any, Optional, List
from app.core.config import settings

logger = logging.getLogger(__name__)


class EmailResponseServiceV2:
    """
    Email response service using proper agentic architecture.
    
    Flow:
    - Step 1: Call Orchestrator (which internally calls Intent Classifier)
    - Step 2: Call Decision Engine to validate and calculate confidence
    - Step 3: Generate AI draft with validated data
    """
    
    def __init__(self):
        self.orchestrator_url = settings.ORCHESTRATOR_SERVICE_URL  # 8013
        self.decision_engine_url = settings.DECISION_ENGINE_SERVICE_URL  # 8014
        self.ai_service_url = settings.AI_SERVICE_URL  # 8003
    
    async def draft_email_response(
        self,
        organization_id: int,
        email_content: str,
        subject: Optional[str] = None,
        from_email: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Draft email response using proper agentic architecture:
        1. Orchestrator (coordinates SQL/Graph/Vector based on intent)
        2. Decision Engine (validates and calculates confidence)
        3. Draft Generator (AI generates response with validated data)
        """
        try:
            logger.info(f"📝 [AGENTIC FLOW] Starting email draft for org={organization_id}")
            
            # Step 1: Call Orchestrator (which calls Intent Classifier internally)
            logger.info("🔀 Step 1: Calling Orchestrator Service...")
            orchestration_result = await self._call_orchestrator(
                organization_id=organization_id,
                email_content=email_content,
                subject=subject,
                from_email=from_email
            )
            
            intent = orchestration_result.get("intent", {})
            results = orchestration_result.get("results", {})
            engines_used = orchestration_result.get("engines_used", {})
            
            logger.info(f"✅ Orchestrator completed: intent={intent.get('intent', 'unknown')}, "
                       f"confidence={intent.get('confidence', 0):.2f}, "
                       f"engines_used={engines_used}")
            
            # Check if this is a non-freight email - skip drafting for general/casual messages
            intent_type = intent.get("intent", "").lower()
            intent_confidence = intent.get("confidence", 0.0)
            
            if intent_type == "general" or (intent_type not in ["rate_inquiry", "tracking", "booking"] and intent_confidence < 0.5):
                logger.info(f"⏭️  Skipping draft for non-freight email: intent={intent_type}, confidence={intent_confidence:.2f}")
                return {
                    "draft": {
                        "subject": f"Re: {subject or 'Your Message'}",
                        "body": "",  # No draft for non-freight emails
                        "to": from_email or "",
                        "cc": [],
                        "bcc": []
                    },
                    "intent": intent,
                    "decision": {"decision": "skip", "confidence_score": 0.0, "reasoning": "Non-freight email - manual response required"},
                    "confidence_score": 0.0,
                    "action": "skip",
                    "engines_used": engines_used,
                    "rate_sheets_found": 0,
                    "skipped": True,
                    "skip_reason": "Non-freight email detected - not generating auto-draft"
                }
            
            # Step 2: Call Decision Engine to validate and calculate confidence
            logger.info("🎯 Step 2: Calling Decision Engine...")
            decision_result = await self._call_decision_engine(
                intent_result=intent,
                orchestration_results=orchestration_result
            )
            
            logger.info(f"✅ Decision Engine completed: decision={decision_result.get('decision', 'unknown')}, "
                       f"confidence_score={decision_result.get('confidence_score', 0):.2f}")
            
            # Step 3: Generate Draft with validated data
            logger.info("📧 Step 3: Generating AI Draft...")
            draft = await self._generate_draft(
                email_content=email_content,
                subject=subject,
                from_email=from_email,
                intent_result=intent,
                orchestration_results=results,
                decision_result=decision_result
            )
            
            logger.info(f"✅ Draft generated: {len(draft.get('body', ''))} chars")
            
            space_insufficient = draft.pop("space_insufficient", False)
            
            return {
                "draft": draft,
                "intent": intent,
                "decision": decision_result,
                "confidence_score": decision_result.get("confidence_score", 0.0),
                "action": decision_result.get("decision", "review_required"),
                "engines_used": engines_used,
                "rate_sheets_found": len(results.get("exact_rates", [])) + len(results.get("semantic_context", [])),
                "space_insufficient": space_insufficient,
            }
            
        except Exception as e:
            logger.error(f"Error in agentic email drafting flow: {e}", exc_info=True)
            raise
    
    async def _call_orchestrator(
        self,
        organization_id: int,
        email_content: str,
        subject: Optional[str],
        from_email: Optional[str]
    ) -> Dict[str, Any]:
        """
        Call the Orchestrator Service which:
        1. Classifies intent via Intent Classifier
        2. Routes to appropriate tools (SQL/Graph/Vector) based on intent
        3. Combines results from all tools
        """
        try:
            # Orchestrator makes multiple downstream calls (Intent, SQL, Graph, Vector)
            # Each can take time, so we need a generous timeout (120 seconds)
            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await client.post(
                    f"{self.orchestrator_url}/api/orchestrator/query",
                    params={"organization_id": organization_id},
                    json={
                        "email_content": email_content,
                        "subject": subject,
                        "from_email": from_email
                    },
                    timeout=120.0
                )
                response.raise_for_status()
                return response.json()
        except httpx.ConnectError as e:
            logger.error(f"Cannot connect to Orchestrator Service at {self.orchestrator_url}: {e}")
            # Return fallback with basic intent
            return {
                "intent": {
                    "intent": "rate_inquiry",
                    "confidence": 0.3,
                    "entities": {},
                    "requires_structured_data": True,
                    "requires_vector_search": True,
                    "requires_graph_traversal": False
                },
                "results": {
                    "exact_rates": [],
                    "route_alternatives": [],
                    "semantic_context": []
                },
                "engines_used": {"sql": False, "graph": False, "vector": False},
                "_error": f"Orchestrator unavailable: {str(e)}"
            }
        except Exception as e:
            logger.error(f"Error calling Orchestrator: {e}")
            raise
    
    async def _call_decision_engine(
        self,
        intent_result: Dict[str, Any],
        orchestration_results: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Call the Decision Engine Service which:
        1. Validates results (ports, dates, data consistency)
        2. Calculates confidence score (weighted scoring)
        3. Makes decision: auto_send, review_required, or escalate
        """
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{self.decision_engine_url}/api/decision/verify",
                    json={
                        "intent_result": intent_result,
                        "orchestration_results": orchestration_results
                    },
                    timeout=30.0
                )
                response.raise_for_status()
                return response.json()
        except httpx.ConnectError as e:
            logger.error(f"Cannot connect to Decision Engine at {self.decision_engine_url}: {e}")
            # Return fallback decision
            return {
                "confidence_score": 0.4,
                "decision": "review_required",
                "reasoning": f"Decision Engine unavailable: {str(e)}",
                "validity_checks": {},
                "data_quality": {}
            }
        except Exception as e:
            logger.error(f"Error calling Decision Engine: {e}")
            raise
    
    async def _generate_draft(
        self,
        email_content: str,
        subject: Optional[str],
        from_email: Optional[str],
        intent_result: Dict[str, Any],
        orchestration_results: Dict[str, Any],
        decision_result: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Generate email draft using AI with validated data from all tools.
        
        NO GUESSING CONTRACT:
        - For pricing-related intents, exact_rates MUST be present
        - If no exact_rates, generate clarification draft instead
        - Zero tolerance for hallucinated prices
        
        Uses:
        - exact_rates: From SQL tool (PostgreSQL)
        - route_alternatives: From Graph tool (ArangoDB)
        - semantic_context: From Vector tool (ChromaDB)
        """
        print("=" * 100)
        print("🔵 [DRAFT GENERATION] Starting draft generation process")
        print("=" * 100)
        logger.info("=" * 100)
        logger.info("🔵 [DRAFT GENERATION] Starting draft generation process")
        logger.info("=" * 100)
        
        # Extract data from orchestration results
        exact_rates = orchestration_results.get("exact_rates", [])
        route_alternatives = orchestration_results.get("route_alternatives", [])
        semantic_context = orchestration_results.get("semantic_context", [])
        
        print(f"\n📊 [DRAFT GENERATION] Data received from orchestrator:")
        print(f"   - exact_rates count: {len(exact_rates)}")
        print(f"   - route_alternatives count: {len(route_alternatives)}")
        print(f"   - semantic_context count: {len(semantic_context)}")
        logger.info(f"📊 [DRAFT GENERATION] Data received: exact_rates={len(exact_rates)}, route_alternatives={len(route_alternatives)}, semantic_context={len(semantic_context)}")
        
        # Log semantic_context structure
        if semantic_context:
            print(f"\n🔍 [DRAFT GENERATION] Semantic context structure (first 3 items):")
            for idx, item in enumerate(semantic_context[:3]):
                if isinstance(item, str):
                    preview = item[:200] + "..." if len(item) > 200 else item
                    print(f"   Item {idx+1} (str, length={len(item)}): {preview}")
                elif isinstance(item, dict):
                    print(f"   Item {idx+1} (dict): keys={list(item.keys())}")
                    if "content" in item:
                        preview = item["content"][:200] + "..." if len(item["content"]) > 200 else item["content"]
                        print(f"      content preview: {preview}")
                else:
                    print(f"   Item {idx+1} (type={type(item)}): {str(item)[:200]}")
            logger.info(f"🔍 [DRAFT GENERATION] Semantic context preview logged (showing first 3 of {len(semantic_context)} items)")
        
        # NO GUESSING CONTRACT: Must have exact rates OR semantic context for pricing drafts
        # This prevents hallucinated prices and accidental commitments
        pricing_intents = ["rate_inquiry", "quote_request", "pricing", "rate_quote", "freight_quote"]
        intent_type = intent_result.get("intent", "").lower()
        
        # If we have semantic context (rate sheets found via vector search), use it even without exact routes
        # This handles cases where routes exist but don't match exactly (e.g., PORT KLANG → SINGAPORE vs NHAVA SHEVA → SINGAPORE)
        has_semantic_context = len(semantic_context) > 0
        
        if intent_type in pricing_intents and len(exact_rates) == 0 and not has_semantic_context:
            logger.warning(f"⚠️  No exact rates or semantic context found for pricing intent '{intent_type}' - generating clarification draft")
            return self._generate_clarification_draft(
                email_content=email_content,
                subject=subject,
                from_email=from_email,
                intent_result=intent_result,
                decision_result=decision_result
            )
        
        # If we have semantic context but no exact rates, still generate a draft using the context
        if intent_type in pricing_intents and len(exact_rates) == 0 and has_semantic_context:
            print(f"\n⚠️  [DRAFT GENERATION] No exact rates but found {len(semantic_context)} rate sheets via semantic search - using ChromaDB context for draft")
            logger.info(f"⚠️  [DRAFT GENERATION] No exact rates but found {len(semantic_context)} rate sheets via semantic search - using ChromaDB context for draft")
        
        # Build context sections
        # PRIORITY: ChromaDB Vector Search Results (semantic_context) are PRIMARY
        context_parts = []
        
        print(f"\n📝 [DRAFT GENERATION] Building context sections for AI prompt...")
        logger.info("📝 [DRAFT GENERATION] Building context sections for AI prompt")
        
        # Check if requested origin port exists in results
        entities = intent_result.get("entities", {})
        requested_origin = entities.get("origin_port", "").upper() if entities.get("origin_port") else None
        requested_dest = entities.get("destination_port", "").upper() if entities.get("destination_port") else None
        
        # Extract origin ports from exact_rates AND semantic_context to check if requested origin exists
        available_origins = set()
        
        # PRIORITY 1: From semantic_context (Vector search results) - PRIMARY SOURCE
        # ChromaDB contains COMPLETE sheet data, so it's the most comprehensive
        if semantic_context:
            print(f"\n🔵 [DRAFT GENERATION] Processing {len(semantic_context)} items from ChromaDB semantic_context (PRIMARY SOURCE)")
            logger.info(f"🔵 [DRAFT GENERATION] Processing {len(semantic_context)} items from ChromaDB semantic_context (PRIMARY SOURCE)")
            for item_idx, item in enumerate(semantic_context):
                print(f"   Processing semantic_context item {item_idx+1}/{len(semantic_context)}")
                logger.debug(f"   Processing semantic_context item {item_idx+1}/{len(semantic_context)}")
                if isinstance(item, str):
                    doc_text = item
                elif isinstance(item, dict):
                    doc_text = item.get("content", item.get("document", str(item)))
                else:
                    doc_text = str(item)
                
                # Extract origin ports from semantic context
                lines = doc_text.split('\n')
                for line in lines:
                    line_upper = line.upper()
                    # Look for route patterns: "Route X: ORIGIN to DESTINATION" or "ORIGIN → DESTINATION"
                    if " to " in line or " → " in line:
                        parts = line.split(" to ") if " to " in line else line.split(" → ")
                        if len(parts) >= 2:
                            origin_part = parts[0]
                            # Remove "Route X:" prefix if present
                            if ":" in origin_part:
                                origin_part = origin_part.split(":")[-1]
                            origin = origin_part.strip().upper()
                            # Filter out common non-port words
                            if origin and origin not in ["ROUTE", "FROM", "ORIGIN", "POL"]:
                                available_origins.add(origin)
        
        # PRIORITY 2: From exact_rates (SQL results) - Secondary source
        # SQL is for exact matches, but ChromaDB has everything
        if exact_rates:
            for rate in exact_rates:
                route_data = rate.get("route", rate)
                origin = route_data.get("origin_port", "").upper()
                if origin:
                    available_origins.add(origin)
        
        # Vessel space check: requested quantity vs space_available on routes
        entities = intent_result.get("entities", {})
        requested_quantity = self._parse_quantity(entities.get("quantity"))
        space_insufficient = False
        space_alert_lines = []
        if requested_quantity is not None and exact_rates:
            for rate in exact_rates:
                route_data = rate.get("route", rate)
                space_avail = route_data.get("space_available")
                if space_avail is not None:
                    try:
                        space_avail_int = int(space_avail)
                    except (TypeError, ValueError):
                        continue
                    if requested_quantity > space_avail_int:
                        space_insufficient = True
                        unit = route_data.get("space_unit") or "TEU"
                        space_alert_lines.append(
                            f"Requested: {requested_quantity} {unit}; available on vessel/route: {space_avail_int} {unit}. "
                            "Space is not sufficient. Please contact us for alternative options or updated space."
                        )
            if space_alert_lines:
                context_parts.append("**ALERT - VESSEL SPACE INSUFFICIENT**\n")
                context_parts.append(" ".join(space_alert_lines))
                context_parts.append("\nInclude the above alert clearly in your response so the customer knows space is limited.\n")
        
        # Check if requested origin matches any available origins
        origin_mismatch = False
        if requested_origin:
            if not available_origins:
                # No routes found at all - this is handled by the clarification draft logic
                pass
            else:
                # Check if requested origin is in available origins (exact or partial match)
                # Also check for country-level matches (e.g., "INDIA" should match "NHAVA SHEVA", "MUNDRA", etc.)
                india_ports = ["NHAVA SHEVA", "MUNDRA", "CHENNAI", "KOLKATA", "PIPAVAV", "KATTUPALLI", "VIZAG", "VISAKHAPATNAM"]
                is_india_query = requested_origin in ["INDIA", "INDIAN"] or any(india_port in requested_origin for india_port in india_ports)
                
                origin_found = any(
                    requested_origin in origin or origin in requested_origin 
                    for origin in available_origins
                )
                
                # Special case: If query is for India but available origins are not Indian ports
                if is_india_query and not any(india_port in origin for origin in available_origins for india_port in india_ports):
                    origin_found = False
                
                if not origin_found:
                    origin_mismatch = True
                    context_parts.append(f"**🚨 CRITICAL: ORIGIN PORT MISMATCH**\n")
                    context_parts.append(f"Customer requested rates FROM: {entities.get('origin_port', 'Unknown')}\n")
                    context_parts.append(f"Available origin ports in database: {', '.join(sorted(available_origins))}\n")
                    context_parts.append(f"⚠️  NO ROUTES FOUND FROM THE REQUESTED ORIGIN PORT.\n")
                    context_parts.append(f"❌ DO NOT present routes from different origin ports as if they match the request.\n")
                    context_parts.append(f"✅ Instead, clearly state that routes FROM the requested origin are not available.\n")
        
        # ========== PRIORITY ORDER: ChromaDB Vector Search is PRIMARY ==========
        
        # 1. SEMANTIC CONTEXT from ChromaDB (Vector Search) - PRIMARY SOURCE
        # This contains COMPLETE sheet data with ALL routes, ALL pricing, ALL information
        if semantic_context:
            print(f"\n🔵 [DRAFT GENERATION] Formatting semantic_context from ChromaDB (PRIMARY SOURCE)")
            logger.info("🔵 [DRAFT GENERATION] Formatting semantic_context from ChromaDB (PRIMARY SOURCE)")
            semantic_text = self._format_semantic_context(semantic_context, requested_origin=requested_origin)
            print(f"   ✅ Formatted semantic_text length: {len(semantic_text)} characters")
            print(f"   ✅ Formatted semantic_text preview (first 500 chars):\n{semantic_text[:500]}...")
            logger.info(f"✅ [DRAFT GENERATION] Formatted semantic_text length: {len(semantic_text)} characters")
            logger.debug(f"✅ [DRAFT GENERATION] Formatted semantic_text preview: {semantic_text[:500]}...")
            if origin_mismatch:
                context_parts.append(f"**⚠️ SEMANTIC SEARCH RESULTS (ChromaDB) - Origin Mismatch Detected:**\n{semantic_text}")
                print(f"   ⚠️  Origin mismatch detected - adding warning to context")
            else:
                context_parts.append(f"**📊 PRIMARY: SEMANTIC SEARCH RESULTS (ChromaDB - Complete Rate Sheet Data):**\n{semantic_text}")
                print(f"   ✅ Added semantic_context to context_parts (PRIMARY SOURCE)")
            logger.info(f"✅ [DRAFT GENERATION] Added semantic_context to context_parts (origin_mismatch={origin_mismatch})")
        
        # 2. EXACT RATES from SQL (PostgreSQL) - Secondary/Validation
        # Used to validate and cross-reference semantic search results
        if exact_rates:
            rates_text = self._format_exact_rates(exact_rates)
            context_parts.append(f"\n**✅ VALIDATION: EXACT RATES (PostgreSQL - Cross-reference):**\n{rates_text}")
        
        # 3. ROUTE ALTERNATIVES from Graph (ArangoDB) - Supplementary
        # Provides alternative routing options
        if route_alternatives:
            alternatives_text = self._format_route_alternatives(route_alternatives)
            context_parts.append(f"\n**🔄 SUPPLEMENTARY: ALTERNATIVE ROUTES (ArangoDB Graph):**\n{alternatives_text}")
        
        # Combine all context
        full_context = "\n".join(context_parts) if context_parts else "No specific rate data found."
        
        print(f"\n📋 [DRAFT GENERATION] Combined context summary:")
        print(f"   - Total context_parts: {len(context_parts)}")
        print(f"   - Full context length: {len(full_context)} characters")
        print(f"   - Full context preview (first 1000 chars):\n{full_context[:1000]}...")
        logger.info(f"📋 [DRAFT GENERATION] Combined context: {len(context_parts)} parts, {len(full_context)} chars")
        logger.debug(f"📋 [DRAFT GENERATION] Full context preview: {full_context[:1000]}...")
        
        # Build the prompt
        confidence_score = decision_result.get("confidence_score", 0.0)
        decision = decision_result.get("decision", "review_required")
        reasoning = decision_result.get("reasoning", "")
        
        print(f"\n📊 [DRAFT GENERATION] Decision Engine results:")
        print(f"   - Confidence Score: {confidence_score:.1%}")
        print(f"   - Decision: {decision}")
        print(f"   - Reasoning: {reasoning}")
        logger.info(f"📊 [DRAFT GENERATION] Decision Engine: confidence={confidence_score:.1%}, decision={decision}")
        
        # Initialize prompt variable to avoid UnboundLocalError
        prompt = ""
        
        # Create the prompt string
        prompt = f"""You are an expert freight forwarding customer service representative. Draft a professional and helpful email response.

CUSTOMER EMAIL:
Subject: {subject or "Freight Rate Inquiry"}
From: {from_email or "Customer"}

{email_content}

---

INTENT CLASSIFICATION:
- Type: {intent_result.get('intent', 'unknown')}
- Confidence: {intent_result.get('confidence', 0.0):.1%}
- Entities: {json.dumps(intent_result.get('entities', {}), indent=2)}

---

AVAILABLE RATE DATA (USE THIS DATA IN YOUR RESPONSE):

{full_context}

---

DECISION ENGINE ANALYSIS:
- Confidence Score: {confidence_score:.1%}
- Decision: {decision}
- Reasoning: {reasoning}

---

INSTRUCTIONS:
1. **CRITICAL - PRIORITY ORDER**: 
   - **PRIMARY SOURCE**: Use data from "SEMANTIC SEARCH RESULTS (ChromaDB)" section FIRST
     * This contains COMPLETE rate sheet data with ALL routes and ALL pricing
     * Extract actual rates, ports, container types, transit times from this section
     * Example: If you see "Route 1: PORT KLANG to SINGAPORE\n  Pricing:\n    - 20': USD 200\n    - 40': USD 400", quote these exact rates
   - **VALIDATION**: Cross-check with "EXACT RATES (PostgreSQL)" section if available
   - **SUPPLEMENTARY**: Use "ALTERNATIVE ROUTES" for routing options
   
   **The ChromaDB semantic search results contain EVERYTHING - prioritize them!**

2. **Route Matching - CRITICAL**:
   - **IF ORIGIN PORT MISMATCH WARNING IS SHOWN ABOVE**:
     * DO NOT show routes from different origin ports as if they match the request
     * Clearly state: "We do not currently have rates FROM [requested origin] in our database"
     * If you see routes from other origins (e.g., PORT KLANG, LAEM CHABANG), DO NOT present them as matching the request
     * Instead, state: "Our current rate sheets contain routes FROM [available origins] TO [destinations], but not FROM [requested origin]"
     * Offer to provide a custom quote: "We would be happy to provide a custom quote for your specific route. Please provide cargo details and preferred shipping dates"
   
   - If exact route not found but origin matches:
     * Mention available routes from the same origin
     * Quote actual rates clearly
     * Explain any differences (e.g., different destination, different routing)

3. **Rate Details to Include**:
   - Base ocean freight rates (with currency: USD, EUR, etc.)
   - Container types (20', 40', 40HC)
   - Carrier name
   - Validity period (valid_from to valid_to)
   - Transit time (if mentioned)
   - Routing (Direct or via transshipment ports)
   - Free detention period (if mentioned)

4. **Formatting**:
   - Use clear sections: "ROUTE 1:", "ROUTE 2:", etc.
   - Use bullet points for rates
   - Include all requested information (BAF, CAF, EBS, PSS if mentioned in context)

5. **If rates are found but route doesn't match exactly**:
   - Quote the available rates clearly
   - Explain the route difference
   - Offer to provide a custom quote for the exact route

6. **Be professional, helpful, and comprehensive**
7. **Address ALL points raised in the customer's email**
8. **If confidence is low ({confidence_score:.0%}), mention that rates are subject to confirmation**
9. **Sign off professionally**

Return a JSON object with:
{{
    "subject": "Re: {subject or 'Freight Rate Inquiry'} - Detailed Quote",
    "body": "Full professional email body with actual rates and details",
    "to": "{from_email or ''}",
    "cc": [],
    "bcc": []
}}

IMPORTANT: The body MUST include specific rates from the data provided. Do NOT give generic responses."""

        # Ensure prompt was created successfully
        if not prompt or len(prompt) == 0:
            error_msg = "CRITICAL ERROR: Prompt variable is empty!"
            logger.error(error_msg)
            raise RuntimeError(error_msg)
        
        # Log prompt details after it's created
        print(f"\n🤖 [DRAFT GENERATION] AI prompt created successfully")
        print(f"   - Prompt length: {len(prompt)} characters")
        print(f"   - Prompt preview (first 1500 chars):\n{prompt[:1500]}...")
        logger.info(f"🤖 [DRAFT GENERATION] AI prompt created: {len(prompt)} characters")
        logger.debug(f"🤖 [DRAFT GENERATION] Prompt preview: {prompt[:1500]}...")

        # Call AI service
        print(f"\n🚀 [DRAFT GENERATION] Calling AI service to generate draft...")
        print(f"   - AI Service URL: {self.ai_service_url}/api/ai/chat")
        print(f"   - Temperature: 0.5")
        print(f"   - Prompt length: {len(prompt)} characters")
        logger.info(f"🚀 [DRAFT GENERATION] Calling AI service: {self.ai_service_url}/api/ai/chat, prompt_length={len(prompt)}")
        try:
            async with httpx.AsyncClient(timeout=90.0) as client:
                response = await client.post(
                    f"{self.ai_service_url}/api/ai/chat",
                    json={
                        "message": prompt,
                        "conversation_history": [],
                        "temperature": 0.5  # Lower temperature for more consistent output
                    },
                    timeout=90.0
                )
                response.raise_for_status()
                result = response.json()
                
                print(f"   ✅ AI service responded successfully")
                print(f"   - Response keys: {list(result.keys())}")
                logger.info(f"   ✅ AI service responded: response_keys={list(result.keys())}")
                
                # Extract JSON from response
                content = result.get("response", "")
                print(f"   - Response content length: {len(content)} characters")
                print(f"   - Response content preview (first 1000 chars):\n{content[:1000]}...")
                logger.info(f"   - Response content length: {len(content)}")
                logger.debug(f"   - Response content preview: {content[:1000]}...")
                
                # Try to parse JSON
                print(f"\n   🔍 [DRAFT GENERATION] Parsing AI response...")
                logger.info(f"   🔍 [DRAFT GENERATION] Parsing AI response")
                try:
                    json_start = content.find("{")
                    json_end = content.rfind("}") + 1
                    print(f"      - JSON start position: {json_start}")
                    print(f"      - JSON end position: {json_end}")
                    if json_start >= 0 and json_end > json_start:
                        json_str = content[json_start:json_end]
                        print(f"      - Extracted JSON string length: {len(json_str)}")
                        draft = json.loads(json_str)
                        print(f"      ✅ Successfully parsed JSON")
                        print(f"      - Draft keys: {list(draft.keys())}")
                        print(f"      - Draft subject: {draft.get('subject', 'N/A')}")
                        print(f"      - Draft body length: {len(draft.get('body', ''))}")
                        logger.info(f"      ✅ Successfully parsed JSON: keys={list(draft.keys())}, body_length={len(draft.get('body', ''))}")
                    else:
                        print(f"      ⚠️  No JSON found in response - using fallback")
                        logger.warning(f"      ⚠️  No JSON found in response - using fallback")
                        # Fallback: create draft from text
                        draft = {
                            "subject": f"Re: {subject or 'Freight Rate Inquiry'}",
                            "body": content,
                            "to": from_email or "",
                            "cc": [],
                            "bcc": []
                        }
                except json.JSONDecodeError as e:
                    print(f"      ❌ JSON decode error: {e}")
                    logger.error(f"      ❌ JSON decode error: {e}")
                    draft = {
                        "subject": f"Re: {subject or 'Freight Rate Inquiry'}",
                        "body": content,
                        "to": from_email or "",
                        "cc": [],
                        "bcc": []
                    }
                
                draft_body = draft.get("body", "")
                draft_subject = draft.get("subject", f"Re: {subject or 'Freight Rate Inquiry'}")
                
                if space_insufficient and space_alert_lines:
                    alert_block = (
                        "**ALERT – Vessel space is not sufficient for the requested quantity.**\n"
                        + " ".join(space_alert_lines) + "\n\n"
                    )
                    draft_body = alert_block + draft_body
                    draft["body"] = draft_body
                
                draft["space_insufficient"] = space_insufficient
                
                print(f"\n✅ [DRAFT GENERATION] Draft generation completed successfully")
                print(f"   - Final draft subject: {draft_subject}")
                print(f"   - Final draft body length: {len(draft_body)} characters")
                print(f"   - Final draft body preview (first 1500 chars):\n{draft_body[:1500]}...")
                print(f"   - Final draft to: {from_email or ''}")
                logger.info(f"✅ [DRAFT GENERATION] Draft generation completed: subject='{draft_subject}', body_length={len(draft_body)}")
                logger.debug(f"✅ [DRAFT GENERATION] Draft body preview: {draft_body[:1500]}...")
                print("=" * 100)
                logger.info("=" * 100)
                
                return draft
                
        except Exception as e:
            print(f"\n❌ [DRAFT GENERATION] Error calling AI service: {e}")
            logger.error(f"❌ [DRAFT GENERATION] Error calling AI service: {e}")
            import traceback
            logger.error(f"❌ [DRAFT GENERATION] Traceback: {traceback.format_exc()}")
            # Return a fallback draft
            return {
                "subject": f"Re: {subject or 'Freight Rate Inquiry'}",
                "body": f"Thank you for your inquiry. We are processing your request and will provide a detailed quote shortly. Our team is reviewing the available rate sheets for your requested routes.",
                "to": from_email or "",
                "cc": [],
                "bcc": []
            }
    
    def _generate_clarification_draft(
        self,
        email_content: str,
        subject: Optional[str],
        from_email: Optional[str],
        intent_result: Dict[str, Any],
        decision_result: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Generate a clarification draft when no exact rates are found.
        
        NO GUESSING CONTRACT:
        - This ensures zero hallucinated prices
        - This ensures zero accidental commitments
        - Human review is REQUIRED for this draft
        """
        entities = intent_result.get("entities", {})
        # Fix: Use proper fallback for None values
        origin = entities.get("origin_port") or "your origin location"
        destination = entities.get("destination_port") or "your destination"
        container_type = entities.get("container_type")
        
        # Build bullet points for what we need
        clarifications = []
        if not entities.get("origin_port"):
            clarifications.append("Exact origin port/location")
        if not entities.get("destination_port"):
            clarifications.append("Exact destination port/location")
        if not container_type:
            clarifications.append("Container type and size required (20ft, 40ft, 40HC, etc.)")
        clarifications.append("Cargo description and weight")
        clarifications.append("Preferred shipping dates")
        
        bullet_points = "\n".join(f"- {c}" for c in clarifications)
        
        body = f"""Thank you for your inquiry regarding shipping from {origin} to {destination}.

To provide you with accurate pricing, we need to confirm a few details:

{bullet_points}

Once we have these details, we'll send you a formal quotation with our best available rates.

Please reply with the information above, and we'll respond promptly with competitive pricing options.

Best regards"""
        
        return {
            "subject": f"Re: {subject or 'Freight Rate Inquiry'} - Information Needed",
            "body": body,
            "to": from_email or "",
            "cc": [],
            "bcc": [],
            "requires_human_review": True,
            "reason": "No exact rates found in database - clarification needed"
        }
    
    @staticmethod
    def _parse_quantity(quantity_val: Any) -> Optional[int]:
        """Parse quantity from intent entities (e.g. '60', '60 TEUs', '50 tons') -> int or None."""
        if quantity_val is None:
            return None
        if isinstance(quantity_val, int) and quantity_val > 0:
            return quantity_val
        if isinstance(quantity_val, str):
            s = quantity_val.strip()
            num_part = ""
            for c in s:
                if c.isdigit():
                    num_part += c
                elif num_part:
                    break
            if num_part:
                try:
                    return int(num_part)
                except ValueError:
                    pass
        return None
    
    def _format_exact_rates(self, exact_rates: List[Dict[str, Any]]) -> str:
        """Format exact rates from SQL tool for the prompt"""
        if not exact_rates:
            return "No exact rates found in database."
        
        lines = []
        for rate in exact_rates[:10]:  # Limit to 10 rates
            # Handle nested route structure from query-routes endpoint
            route_data = rate.get("route", rate)  # Use nested route if present, else rate itself
            
            carrier = rate.get("carrier_name") or route_data.get("carrier_name") or "Unknown Carrier"
            origin = route_data.get("origin_port") or route_data.get("origin_port_name") or "N/A"
            destination = route_data.get("destination_port") or route_data.get("destination_port_name") or "N/A"
            container = route_data.get("container_type", "N/A")
            base_rate = route_data.get("base_rate", "N/A")
            currency = route_data.get("currency", "USD")
            transit = route_data.get("transit_time_days") or route_data.get("transit_time_text") or "N/A"
            valid_from = rate.get("valid_from") or route_data.get("valid_from") or "N/A"
            valid_to = rate.get("valid_to") or route_data.get("valid_to") or "N/A"
            
            # Get extra details
            extra_data = route_data.get("extra_data", {})
            routing = extra_data.get("routing") or "N/A"
            free_detention = extra_data.get("free_detention_days") or extra_data.get("free_detention_text") or "N/A"
            
            line = f"- {carrier}: {origin} → {destination} | {container} @ {currency} {base_rate}"
            if transit != "N/A":
                line += f" | Transit: {transit}"
            if routing != "N/A":
                line += f" | Routing: {routing}"
            if free_detention != "N/A":
                line += f" | Free Detention: {free_detention}"
            if valid_from != "N/A" or valid_to != "N/A":
                line += f" | Valid: {valid_from} to {valid_to}"
            space_avail = route_data.get("space_available")
            if space_avail is not None:
                unit = route_data.get("space_unit") or "TEU"
                line += f" | Space available: {space_avail} {unit}"
            
            lines.append(line)
        
        return "\n".join(lines)
    
    def _format_route_alternatives(self, alternatives: List[Dict[str, Any]]) -> str:
        """Format route alternatives from Graph tool for the prompt"""
        if not alternatives:
            return "No alternative routes found."
        
        lines = []
        for alt in alternatives[:5]:  # Limit to 5 alternatives
            if isinstance(alt, dict):
                if alt.get("type") == "alternatives":
                    for sub_alt in alt.get("alternatives", [])[:3]:
                        via = sub_alt.get("via_port", "transshipment")
                        hops = sub_alt.get("hop_count", "N/A")
                        lines.append(f"- Via {via} ({hops} hops)")
                else:
                    origin = alt.get("origin_port", "N/A")
                    destination = alt.get("destination_port", "N/A")
                    via = alt.get("routing", "Direct")
                    lines.append(f"- {origin} → {destination} ({via})")
        
        return "\n".join(lines) if lines else "No alternative routes found."
    
    def _format_semantic_context(self, semantic_context: List[Any], requested_origin: Optional[str] = None) -> str:
        """
        Format semantic context from Vector tool (ChromaDB) for the prompt.
        
        THIS IS THE PRIMARY SOURCE - ChromaDB contains COMPLETE rate sheet data:
        - ALL routes with ALL pricing tiers
        - Complete raw Excel data
        - Carrier information, validity dates
        - Transit times, free detention, remarks
        
        IMPORTANT: Extract ALL pricing data from these documents.
        The semantic context contains EVERYTHING from the rate sheets.
        
        Args:
            semantic_context: List of documents from ChromaDB vector search (PRIMARY SOURCE)
            requested_origin: Origin port from customer query (for mismatch detection)
        """
        print(f"\n🔵 [SEMANTIC CONTEXT FORMATTING] Starting to format semantic_context")
        print(f"   - Input semantic_context count: {len(semantic_context)}")
        print(f"   - Requested origin: {requested_origin}")
        logger.info(f"🔵 [SEMANTIC CONTEXT FORMATTING] Starting: count={len(semantic_context)}, requested_origin={requested_origin}")
        
        if not semantic_context:
            print(f"   ⚠️  No semantic_context provided - returning empty message")
            logger.warning("⚠️  [SEMANTIC CONTEXT FORMATTING] No semantic_context provided")
            return "No rate sheet data found in ChromaDB."
        
        # semantic_context is typically a list of document strings or dicts
        context_parts = []
        extracted_origins = set()
        
        # Process ALL semantic results (increased from 5 to 10 for better coverage)
        print(f"   Processing up to 10 items from semantic_context")
        logger.info(f"   Processing up to 10 items from semantic_context")
        for i, item in enumerate(semantic_context[:10], 1):  # Increased limit for comprehensive coverage
            print(f"\n   📄 [SEMANTIC CONTEXT FORMATTING] Processing item {i}/{min(10, len(semantic_context))}")
            logger.debug(f"   📄 [SEMANTIC CONTEXT FORMATTING] Processing item {i}/{min(10, len(semantic_context))}")
            
            if isinstance(item, str):
                doc_text = item
                print(f"      Item type: str, length: {len(doc_text)}")
            elif isinstance(item, dict):
                doc_text = item.get("content", item.get("document", str(item)))
                print(f"      Item type: dict, keys: {list(item.keys())}, content length: {len(doc_text) if isinstance(doc_text, str) else 'N/A'}")
                logger.debug(f"      Item type: dict, keys: {list(item.keys())}")
            else:
                doc_text = str(item)
                print(f"      Item type: {type(item)}, converted to str, length: {len(doc_text)}")
            
            print(f"      Doc text preview (first 300 chars): {doc_text[:300]}...")
            logger.debug(f"      Doc text preview: {doc_text[:300]}...")
            
            # Parse and extract ALL pricing information from ChromaDB documents
            # ChromaDB contains COMPLETE data - extract EVERYTHING (PRIMARY SOURCE)
            lines = doc_text.split('\n')
            print(f"      Total lines in doc: {len(lines)}")
            logger.debug(f"      Total lines in doc: {len(lines)}")
            
            # Extract ALL structured pricing data for comprehensive presentation
            parsed_data = []
            current_route = None
            pricing_lines_found = 0
            route_lines_found = 0
            
            print(f"      Extracting pricing and route data from lines...")
            for line_num, line in enumerate(lines):
                line = line.strip()
                
                # Look for route lines - multiple formats
                # "Route 1: LAEM CHABANG to NHAVA SHEVA" or "PORT KLANG → SINGAPORE"
                if (line.startswith("Route") and " to " in line) or ("→" in line and len(line) < 150):
                    current_route = line
                    parsed_data.append(f"\n{line}")
                    route_lines_found += 1
                    print(f"         Line {line_num}: Found route line: {line[:100]}")
                    logger.debug(f"         Line {line_num}: Found route line: {line[:100]}")
                    # Extract origin port from route line for mismatch detection
                    if " to " in line:
                        parts = line.split(" to ")
                        if len(parts) >= 2:
                            origin_part = parts[0]
                            if ":" in origin_part:
                                origin_part = origin_part.split(":")[-1]
                            origin = origin_part.strip().upper()
                            if origin and origin not in ["ROUTE", "FROM", "ORIGIN", "POL"]:
                                extracted_origins.add(origin)
                                print(f"            Extracted origin: {origin}")
                    elif "→" in line:
                        parts = line.split("→")
                        if len(parts) >= 2:
                            origin = parts[0].strip().upper()
                            if origin and origin not in ["ROUTE", "FROM", "ORIGIN", "POL"]:
                                extracted_origins.add(origin)
                                print(f"            Extracted origin: {origin}")
                    continue
                
                # Look for ALL pricing lines - multiple formats (PRIMARY DATA)
                # "    - 20': USD 850" or "20': $200" or "Pricing: 20': USD 200"
                if (" USD " in line or " $ " in line or 
                    ("USD" in line and any(char.isdigit() for char in line)) or
                    ("Pricing:" in line and ("USD" in line or "$" in line))):
                    # This is a pricing line - keep it (PRIMARY DATA from ChromaDB)
                    parsed_data.append(line)
                    pricing_lines_found += 1
                    print(f"         Line {line_num}: Found pricing line: {line[:150]}")
                    logger.debug(f"         Line {line_num}: Found pricing line: {line[:150]}")
                    continue
                
                # Look for ALL service/routing/transit information
                if any(keyword in line for keyword in [
                    "Service:", "Routing:", "Transit Time:", "Free Detention:", 
                    "Carrier:", "Valid From:", "Valid To:", "File:", 
                    "Origin Ports:", "Destination Ports:", "Container Types:",
                    "Total Routes:", "Rate Sheet:", "COMPLETE RAW", "AI-EXTRACTED"
                ]):
                    parsed_data.append(line)
                    continue
                
                # Keep ALL metadata and validity information
                if any(keyword in line for keyword in [
                    "Validity:", "Rate Sheet:", "File:", "Carrier:", 
                    "COMPLETE RAW", "AI-EXTRACTED", "Route Summary"
                ]):
                    parsed_data.append(line)
            
            # If we extracted structured data, use it; otherwise use more of the original
            # ChromaDB contains COMPLETE data, so show more content
            print(f"      Extraction summary:")
            print(f"         - Route lines found: {route_lines_found}")
            print(f"         - Pricing lines found: {pricing_lines_found}")
            print(f"         - Parsed data lines: {len(parsed_data)}")
            logger.info(f"      Extraction summary: routes={route_lines_found}, pricing={pricing_lines_found}, parsed_lines={len(parsed_data)}")
            
            if parsed_data:
                formatted_doc = "\n".join(parsed_data)
                print(f"      ✅ Using extracted structured data (length: {len(formatted_doc)} chars)")
                print(f"      ✅ Formatted doc preview (first 500 chars):\n{formatted_doc[:500]}...")
                logger.debug(f"      ✅ Formatted doc preview: {formatted_doc[:500]}...")
                context_parts.append(f"--- Rate Sheet {i} (ChromaDB - Complete Data) ---\n{formatted_doc}")
            else:
                # Fallback: use more of the original text (increased from 2000 to 4000 chars)
                # ChromaDB has everything, so show more
                truncated = doc_text[:4000] + "..." if len(doc_text) > 4000 else doc_text
                print(f"      ⚠️  No structured data extracted - using truncated original (length: {len(truncated)} chars)")
                logger.warning(f"      ⚠️  No structured data extracted - using truncated original")
                context_parts.append(f"--- Rate Sheet {i} (ChromaDB - Full Content) ---\n{truncated}")
        
        # Add origin mismatch warning if detected
        print(f"\n   🔍 [SEMANTIC CONTEXT FORMATTING] Origin analysis:")
        print(f"      - Extracted origins: {sorted(extracted_origins)}")
        print(f"      - Requested origin: {requested_origin}")
        logger.info(f"   🔍 [SEMANTIC CONTEXT FORMATTING] Extracted origins: {sorted(extracted_origins)}, requested: {requested_origin}")
        
        if requested_origin and extracted_origins:
            requested_upper = requested_origin.upper()
            origin_matches = any(
                requested_upper in origin or origin in requested_upper 
                for origin in extracted_origins
            )
            print(f"      - Origin match: {origin_matches}")
            logger.info(f"      - Origin match: {origin_matches}")
            if not origin_matches:
                warning_msg = f"⚠️  WARNING: Routes found are from different origin ports ({', '.join(sorted(extracted_origins))}), not from requested origin ({requested_origin}).\n"
                context_parts.insert(0, warning_msg)
                print(f"      ⚠️  Added origin mismatch warning to context")
                logger.warning(f"      ⚠️  Origin mismatch detected - added warning")
        
        final_result = "\n\n".join(context_parts) if context_parts else "No additional context available."
        print(f"\n   ✅ [SEMANTIC CONTEXT FORMATTING] Formatting completed")
        print(f"      - Final result length: {len(final_result)} characters")
        print(f"      - Context parts count: {len(context_parts)}")
        logger.info(f"   ✅ [SEMANTIC CONTEXT FORMATTING] Completed: result_length={len(final_result)}, parts={len(context_parts)}")
        
        return final_result

    async def process_inbound_reply(
        self,
        user_id: int,
        organization_id: int,
        email_content: str,
        subject: Optional[str] = None,
        from_email: Optional[str] = None,
        thread_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Process an inbound email reply: classify intent; if quote_acceptance, resolve customer and create order.
        Called by Email Service after storing a reply.
        """
        import time
        intent_classifier_url = settings.INTENT_CLASSIFIER_SERVICE_URL
        order_service_url = settings.ORDER_SERVICE_URL
        customer_service_url = settings.CUSTOMER_SERVICE_URL
        internal_api_key = settings.INTERNAL_API_KEY

        # 1. Classify intent (with is_reply=True)
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    f"{intent_classifier_url}/api/intent/classify",
                    json={
                        "email_content": email_content,
                        "subject": subject,
                        "from_email": from_email,
                        "is_reply": True,
                    },
                    timeout=30.0,
                )
                resp.raise_for_status()
                classification = resp.json()
        except Exception as e:
            logger.warning(f"Intent classifier call failed: {e}")
            return {"processed": False, "error": str(e), "intent": None}

        intent = (classification.get("intent") or "").lower()
        if intent != "quote_acceptance":
            return {"processed": False, "intent": intent, "order_id": None}

        # 2. Resolve customer by email (optional)
        customer_id = None
        if customer_service_url and internal_api_key and from_email:
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    r = await client.get(
                        f"{customer_service_url}/api/customers/internal/by-email",
                        params={"user_id": user_id, "email": from_email.strip().lower()},
                        headers={"X-Internal-Api-Key": internal_api_key},
                        timeout=10.0,
                    )
                    if r.status_code == 200:
                        data = r.json()
                        if data.get("found"):
                            customer_id = data.get("customer_id")
            except Exception as e:
                logger.warning(f"Customer lookup failed: {e}")

        # 3. Build reference number (unique per reply)
        ref = f"QUOTE-{thread_id or 'email'}-{int(time.time())}"

        # 4. Create order via Order Service internal API
        if not order_service_url or not internal_api_key:
            logger.warning("ORDER_SERVICE_URL or INTERNAL_API_KEY not set; skipping order creation")
            return {"processed": True, "intent": intent, "order_id": None, "customer_id": customer_id, "skipped": "config"}

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                r = await client.post(
                    f"{order_service_url}/api/orders/internal/create-for-user",
                    json={
                        "user_id": user_id,
                        "reference_number": ref,
                        "status": "booked",
                        "origin_port": None,
                        "destination_port": None,
                        "carrier": None,
                        "customer_id": customer_id,
                    },
                    headers={"X-Internal-Api-Key": internal_api_key},
                    timeout=15.0,
                )
                r.raise_for_status()
                order = r.json()
                order_id = order.get("id")
                logger.info(f"Created order {order_id} from quote acceptance (user_id={user_id}, customer_id={customer_id})")
                return {"processed": True, "intent": intent, "order_id": order_id, "customer_id": customer_id}
        except Exception as e:
            logger.error(f"Order creation failed: {e}", exc_info=True)
            return {"processed": True, "intent": intent, "order_id": None, "customer_id": customer_id, "error": str(e)}
