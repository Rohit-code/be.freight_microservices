"""Email Response Service - Drafts and sends email responses based on rate sheet queries"""
import httpx
import json
import logging
from typing import Dict, List, Any, Optional
from app.core.config import settings
from app.services.rate_sheet_service import RateSheetService

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
            # Search rate sheets using email query
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
            
            # Calculate overall confidence score (average of top results)
            confidence_scores = [rs.get("similarity", 0) for rs in rate_sheets]
            avg_confidence = sum(confidence_scores) / len(confidence_scores) if confidence_scores else 0.0
            
            # Build context from rate sheets
            rate_sheet_context = self._build_rate_sheet_context(rate_sheets)
            
            # Draft email using AI service
            drafted_email = await self._draft_email_with_ai(
                email_query=email_query,
                rate_sheet_context=rate_sheet_context,
                original_subject=original_email_subject,
                original_from=original_email_from,
                confidence_score=avg_confidence
            )
            
            return {
                "drafted_email": drafted_email,
                "rate_sheets_found": len(rate_sheets),
                "confidence_score": round(avg_confidence, 2),
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
        confidence_score: float
    ) -> Dict[str, Any]:
        """Use AI service to draft email response"""
        
        prompt = f"""You are a freight forwarding rate sheet expert. Draft a professional email response based on the customer's query and the rate sheet information provided.

CUSTOMER QUERY:
{email_query}

ORIGINAL EMAIL SUBJECT: {original_subject or "Not provided"}
ORIGINAL EMAIL FROM: {original_from or "Not provided"}

RATE SHEET INFORMATION:
{rate_sheet_context}

CONFIDENCE SCORE: {confidence_score:.2%}

CRITICAL INSTRUCTIONS - READ CAREFULLY:

1. **EXTRACT AND USE SPECIFIC RATES**: The rate sheet information above contains ACTUAL PRICING DATA. You MUST extract and include:
   - Specific freight rates (e.g., "650 USD", "700-850 USD", "1100 USD")
   - Container types (20', 40', etc.)
   - VGM weight categories (18MT, 26MT, etc.)
   - Port names (NHAVA SHEVA, LAEM CHABANG, etc.)
   - Transit times (e.g., "7 days", "5-10 days")
   - Free detention periods (e.g., "14 days")
   - Routing information (Direct, via PKG/SIN, etc.)
   - Validity dates (e.g., "January 2026", "1-1-2026 to 31-1-2026")

2. **NEVER SAY RATES ARE NOT AVAILABLE**: If you see rate data in the rate sheet information above, you MUST include it. Do NOT say "rates are not detailed" or "rates are not available" - extract them from the content.

3. **BE SPECIFIC AND DETAILED**: 
   - Quote exact numbers: "20' container VGM up to 18MT: 650 USD"
   - Include all relevant routes and pricing tiers
   - Mention transit times, free detention, routing options
   - Reference specific ports and carriers

4. **PROFESSIONAL TONE**: Write as a freight forwarding professional responding to a customer inquiry

5. **ADDRESS ALL QUERY POINTS**: Make sure you answer all questions asked in the customer query

6. **CONFIDENCE SCORE**: Include the confidence score naturally in the email (e.g., "Based on our rate sheets, I found this information with {confidence_score:.1%} confidence")

7. **MULTIPLE RATE SHEETS**: If multiple rate sheets are provided, compare and summarize the best options

8. **FORMAT**: Use clear sections, bullet points for rates, and professional business email formatting

EXAMPLE OF GOOD RATE EXTRACTION:
- "For NHAVA SHEVA to LAEM CHABANG route, we have the following rates:
  * 20' container (VGM up to 18MT): 650 USD
  * 20' container (VGM up to 26MT): 700 USD  
  * 40' container (VGM up to 26MT): 1100 USD
  * Routing: via Port Klang/Singapore
  * Transit Time: 7 days
  * Free Detention: 14 days at destination"

Return a JSON object with:
{{
    "subject": "Re: [original subject or appropriate subject]",
    "body": "Full email body text with specific rates and details extracted from rate sheets",
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
            logger.error(f"Error calling AI service: {e}")
            # Fallback email
            return {
                "subject": f"Re: {original_subject or 'Rate Sheet Inquiry'}",
                "body": f"Thank you for your inquiry.\n\n{email_query}\n\nI found relevant rate sheet information. Please let me know if you need more details.",
                "confidence_note": f"Confidence: {confidence_score:.1%}"
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
