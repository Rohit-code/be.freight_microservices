import httpx
import json
import logging
from typing import Dict, List, Any, Optional
from app.core.config import settings

logger = logging.getLogger(__name__)


class AIAnalyzer:
    """AI-powered analyzer for understanding rate sheet structure and relationships"""
    
    def __init__(self):
        self.ai_service_url = settings.AI_SERVICE_URL
        self.anthropic_api_key = settings.ANTHROPIC_API_KEY
        self.openai_api_key = settings.OPENAI_API_KEY
    
    async def analyze_rate_sheet(
        self,
        parsed_data: Dict[str, Any],
        file_name: str,
        existing_rate_sheets: Optional[List[Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        """
        Use AI to analyze rate sheet structure and extract structured data
        
        Args:
            parsed_data: Parsed Excel data from ExcelParser
            file_name: Name of the uploaded file
            existing_rate_sheets: List of existing rate sheets for relationship detection
        
        Returns:
            Dictionary with extracted structured data and analysis
        """
        # Prepare prompt for AI analysis
        prompt = self._build_analysis_prompt(parsed_data, file_name, existing_rate_sheets)
        
        try:
            # Call AI service
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    f"{self.ai_service_url}/api/ai/analyze-rate-sheet",
                    json={
                        "parsed_data": parsed_data,
                        "file_name": file_name,
                        "existing_rate_sheets": existing_rate_sheets or [],
                        "prompt": prompt
                    },
                    headers={
                        "Content-Type": "application/json"
                    }
                )
                response.raise_for_status()
                result = response.json()
                return result.get("analysis", {})
        
        except Exception as e:
            logger.error(f"Error calling AI service: {e}")
            # Fallback to basic extraction
            return self._fallback_analysis(parsed_data, file_name)
    
    def _build_analysis_prompt(
        self,
        parsed_data: Dict[str, Any],
        file_name: str,
        existing_rate_sheets: Optional[List[Dict[str, Any]]]
    ) -> str:
        """Build comprehensive prompt for AI analysis"""
        
        prompt = f"""You are an expert freight forwarding rate sheet analyzer. Analyze the following rate sheet file and extract structured data.

FILE NAME: {file_name}

PARSED DATA STRUCTURE:
{json.dumps(parsed_data, indent=2, default=str)}

TASK:
1. Identify the rate sheet type (ocean_freight, air_freight, land_freight, multimodal, unknown)
2. Extract carrier/shipping line name
3. Identify validity period (valid_from, valid_to, effective_date)
4. Extract all routes with:
   - Origin port/city/country/code
   - Destination port/city/country/code
   - Routing information (Direct, via ports, etc.)
   - Transit time
   - Free detention information
5. Extract pricing tiers for each route:
   - Container types (20', 40', 40HC, LCL, etc.)
   - Base rates
   - Currency
   - Weight-based pricing (if applicable)
   - VGM (Verified Gross Mass) pricing tiers
6. Extract surcharges (BAF, CAF, EBS, PSS, etc.)
7. Extract additional charges (documentation, handling, etc.)
8. Extract remarks and special conditions

IMPORTANT:
- Some rate sheets are "hand in hand" (related/linked together) - detect if this file relates to others
- Some rate sheets are completely independent
- Handle merged cells and complex layouts intelligently
- Extract data accurately even if format is non-standard
- Identify relationships with existing rate sheets if provided

EXISTING RATE SHEETS (for relationship detection):
{json.dumps(existing_rate_sheets or [], indent=2, default=str) if existing_rate_sheets else "None"}

Return a JSON object with this structure:
{{
    "rate_sheet_type": "ocean_freight|air_freight|land_freight|multimodal|unknown",
    "carrier_name": "string or null",
    "title": "extracted title",
    "validity": {{
        "valid_from": "ISO datetime or null",
        "valid_to": "ISO datetime or null",
        "effective_date": "ISO datetime or null"
    }},
    "routes": [
        {{
            "origin_port": "string",
            "origin_country": "string",
            "origin_city": "string",
            "origin_code": "string (port code)",
            "destination_port": "string",
            "destination_country": "string",
            "destination_city": "string",
            "destination_code": "string",
            "routing": "string (e.g., Direct, via SIN)",
            "transit_time_days": "integer or null",
            "transit_time_text": "string (e.g., 7 days)",
            "service_type": "FCL|LCL|etc",
            "is_direct": "boolean",
            "free_detention_days": "integer or null",
            "free_detention_text": "string",
            "remarks": "string",
            "pricing_tiers": [
                {{
                    "container_type": "20'|40'|40HC|LCL|etc",
                    "container_size": "20|40|45",
                    "container_height": "HC|Standard",
                    "base_rate": "decimal",
                    "currency": "USD|INR|etc",
                    "min_weight_kg": "decimal or null",
                    "max_weight_kg": "decimal or null",
                    "vgm_min_weight_mt": "decimal or null",
                    "vgm_max_weight_mt": "decimal or null",
                    "minimum_charge": "decimal or null",
                    "remarks": "string",
                    "surcharges": [
                        {{
                            "surcharge_type": "BAF|CAF|EBS|PSS|etc",
                            "surcharge_name": "string",
                            "amount": "decimal or null",
                            "currency": "string",
                            "is_percentage": "boolean",
                            "percentage_value": "decimal or null",
                            "description": "string"
                        }}
                    ],
                    "charges": [
                        {{
                            "charge_type": "Documentation|Handling|etc",
                            "charge_name": "string",
                            "amount": "decimal",
                            "currency": "string",
                            "is_per_unit": "boolean",
                            "unit_type": "container|shipment|etc",
                            "description": "string"
                        }}
                    ]
                }}
            ]
        }}
    ],
    "relationships": {{
        "is_related": "boolean",
        "relationship_type": "hand_in_hand|independent|version|supplement",
        "related_to_rate_sheets": ["list of rate sheet IDs or file names"],
        "confidence_score": "integer 0-100",
        "reasoning": "explanation of relationship"
    }},
    "detected_format": "description of format type",
    "confidence_score": "integer 0-100",
    "extraction_notes": "any important notes about extraction"
}}
"""
        return prompt
    
    def _fallback_analysis(self, parsed_data: Dict[str, Any], file_name: str) -> Dict[str, Any]:
        """Fallback analysis when AI service is unavailable"""
        logger.warning("Using fallback analysis - AI service unavailable")
        
        return {
            "rate_sheet_type": "unknown",
            "carrier_name": None,
            "title": file_name,
            "validity": {
                "valid_from": None,
                "valid_to": None,
                "effective_date": None
            },
            "routes": [],
            "relationships": {
                "is_related": False,
                "relationship_type": "independent",
                "related_to_rate_sheets": [],
                "confidence_score": 0,
                "reasoning": "Fallback analysis - AI service unavailable"
            },
            "detected_format": "unknown",
            "confidence_score": 0,
            "extraction_notes": "Fallback analysis used - manual review required"
        }
    
    async def detect_relationships(
        self,
        new_rate_sheet: Dict[str, Any],
        existing_rate_sheets: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Detect relationships between new rate sheet and existing ones
        
        Returns:
            Dictionary with relationship information
        """
        if not existing_rate_sheets:
            return {
                "is_related": False,
                "relationship_type": "independent",
                "related_to_rate_sheets": [],
                "confidence_score": 100,
                "reasoning": "No existing rate sheets to compare"
            }
        
        # Use AI to detect relationships
        prompt = f"""Analyze if this new rate sheet is related to any existing rate sheets.

NEW RATE SHEET:
{json.dumps(new_rate_sheet, indent=2, default=str)}

EXISTING RATE SHEETS:
{json.dumps(existing_rate_sheets, indent=2, default=str)}

Determine if the new rate sheet:
1. Is "hand in hand" (related/linked) with any existing rate sheets
2. Is a new version of an existing rate sheet
3. Supplements an existing rate sheet
4. Is completely independent

Return JSON:
{{
    "is_related": "boolean",
    "relationship_type": "hand_in_hand|independent|version|supplement",
    "related_to_rate_sheets": ["list of IDs"],
    "confidence_score": "integer 0-100",
    "reasoning": "explanation"
}}
"""
        
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{self.ai_service_url}/api/ai/detect-relationships",
                    json={
                        "new_rate_sheet": new_rate_sheet,
                        "existing_rate_sheets": existing_rate_sheets,
                        "prompt": prompt
                    }
                )
                response.raise_for_status()
                return response.json().get("relationships", {})
        except Exception as e:
            logger.error(f"Error detecting relationships: {e}")
            return {
                "is_related": False,
                "relationship_type": "independent",
                "related_to_rate_sheets": [],
                "confidence_score": 0,
                "reasoning": f"Error detecting relationships: {str(e)}"
            }
