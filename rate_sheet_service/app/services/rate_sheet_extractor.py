"""
Rate Sheet Extractor

Extracts structured data from parsed rate sheets using AI.

FLOW:
1. Pandas extracts CLEAN TABLE from Excel → Clear column headers
2. Clean table given to AI → Accurate extraction
3. Structured data → PostgreSQL (for exact queries)
4. ENTIRE sheet → ChromaDB (for semantic search)

NOTE: This is extraction, not reasoning. The AI identifies and extracts
existing data (routes, prices, dates) - it does NOT make pricing decisions.
"""
import httpx
import json
import logging
from typing import Dict, List, Any, Optional
from app.core.config import settings
from app.services.pandas_table_extractor import PandasTableExtractor, format_for_ai_extraction

logger = logging.getLogger(__name__)


class RateSheetExtractor:
    """
    Extracts structured data from parsed rate sheets using AI.
    
    NOTE: This is extraction, not reasoning. The AI identifies and extracts
    existing data (routes, prices, dates) - it does NOT make pricing decisions.
    
    Responsibilities:
    - Extract carrier name, validity dates
    - Extract routes with origin/destination
    - Extract pricing tiers, container types
    - Extract surcharges and additional charges
    - Detect relationships with existing rate sheets
    
    NOT responsible for:
    - Making pricing decisions
    - Determining quotes
    - Business logic
    """
    
    def __init__(self):
        self.ai_service_url = settings.AI_SERVICE_URL
        self.anthropic_api_key = settings.ANTHROPIC_API_KEY
        self.openai_api_key = settings.OPENAI_API_KEY
        self.pandas_extractor = PandasTableExtractor()
    
    async def extract_structured_data(
        self,
        parsed_data: Dict[str, Any],
        file_name: str,
        existing_rate_sheets: Optional[List[Dict[str, Any]]] = None,
        file_path: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Extract structured data from rate sheet using PANDAS + AI.
        
        NEW FLOW:
        1. Pandas extracts CLEAN TABLE from Excel with clear column headers
        2. Clean table formatted and given to AI
        3. AI extracts structured data with full context
        4. Structured data returned for PostgreSQL storage
        
        This is EXTRACTION, not reasoning. The AI identifies and extracts
        existing data from the document.
        
        Args:
            parsed_data: Parsed Excel data from ExcelParser (backup)
            file_name: Name of the uploaded file
            existing_rate_sheets: List of existing rate sheets for relationship detection
            file_path: Path to the Excel file for pandas extraction
        
        Returns:
            Dictionary with extracted structured data
        """
        logger.info(f"🚀 [EXTRACTOR] Starting extraction for: {file_name}")
        
        # STEP 1: Use Pandas to create CLEAN TABLE
        clean_table = None
        full_sheet_text = None
        pandas_metadata = {}
        
        if file_path:
            try:
                logger.info(f"🐼 [EXTRACTOR] Using Pandas to extract clean table from: {file_path}")
                clean_table, full_sheet_text, pandas_metadata = await self.pandas_extractor.extract_from_file(file_path)
                logger.info(f"🐼 [EXTRACTOR] Pandas extracted: {len(clean_table)} chars table, metadata={pandas_metadata}")
            except Exception as e:
                logger.warning(f"⚠️ [EXTRACTOR] Pandas extraction failed, falling back to old method: {e}")
                clean_table = None
        
        # STEP 2: Build prompt with clean pandas data OR old method
        if clean_table and len(clean_table) > 100:
            # Use the clean pandas data for AI extraction
            prompt = format_for_ai_extraction(clean_table, full_sheet_text, pandas_metadata, file_name)
            logger.info(f"📊 [EXTRACTOR] Using PANDAS + AI extraction (clean_text={len(clean_table)} chars)")
        else:
            # Fallback to old method
            prompt = self._build_extraction_prompt(parsed_data, file_name, existing_rate_sheets)
            logger.info(f"📊 [EXTRACTOR] Using legacy extraction method")
        
        # STEP 3: Call AI to extract structured data
        try:
            async with httpx.AsyncClient(timeout=300.0) as client:  # 5 minute timeout for large files
                response = await client.post(
                    f"{self.ai_service_url}/api/ai/chat",
                    json={
                        "message": prompt,
                        "conversation_history": [],
                        "temperature": 0.1  # Low temperature for consistent extraction
                    },
                    headers={
                        "Content-Type": "application/json"
                    }
                )
                response.raise_for_status()
                result = response.json()
                
                # Parse JSON from AI response
                content = result.get("response", "")
                
                # Extract JSON from the response
                try:
                    json_start = content.find("{")
                    json_end = content.rfind("}") + 1
                    if json_start >= 0 and json_end > json_start:
                        json_str = content[json_start:json_end]
                        extracted_data = json.loads(json_str)
                        
                        # Add pandas metadata and full sheet text for ChromaDB
                        if pandas_metadata:
                            if not extracted_data.get("carrier_name") and pandas_metadata.get("carrier_name"):
                                extracted_data["carrier_name"] = pandas_metadata["carrier_name"]
                            if not extracted_data.get("validity") and pandas_metadata.get("validity"):
                                extracted_data["validity"] = pandas_metadata["validity"]
                        
                        # Store full sheet text for ChromaDB embeddings
                        if full_sheet_text:
                            extracted_data["_full_sheet_text"] = full_sheet_text
                        
                        logger.info(f"✅ [EXTRACTOR] AI extraction successful: {len(extracted_data.get('routes', []))} routes extracted")
                        return extracted_data
                    else:
                        logger.warning("No JSON found in AI response, using fallback")
                        return self._fallback_extraction(parsed_data, file_name)
                except json.JSONDecodeError as e:
                    logger.warning(f"Failed to parse AI response as JSON: {e}")
                    return self._fallback_extraction(parsed_data, file_name)
        
        except httpx.ConnectError as e:
            logger.error(f"Error calling AI service: Cannot connect to {self.ai_service_url} - {str(e) or 'Connection refused'}")
            return self._fallback_extraction(parsed_data, file_name)
        except httpx.TimeoutException as e:
            logger.error(f"Error calling AI service: Request timeout after 60s - {str(e) or 'Request timed out'}")
            return self._fallback_extraction(parsed_data, file_name)
        except httpx.HTTPStatusError as e:
            error_text = ""
            try:
                error_text = e.response.text[:200] if e.response else "No response"
            except:
                pass
            logger.error(f"Error calling AI service: HTTP {e.response.status_code if e.response else 'Unknown'} - {error_text}")
            return self._fallback_extraction(parsed_data, file_name)
        except Exception as e:
            error_msg = str(e) if str(e) else f"{type(e).__name__} (no message)"
            logger.error(f"Error calling AI service: {error_msg}", exc_info=True)
            return self._fallback_extraction(parsed_data, file_name)
    
    # Backward compatibility alias
    async def analyze_rate_sheet(
        self,
        parsed_data: Dict[str, Any],
        file_name: str,
        existing_rate_sheets: Optional[List[Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        """Backward compatibility alias for extract_structured_data"""
        return await self.extract_structured_data(parsed_data, file_name, existing_rate_sheets)
    
    def _filter_relevant_data(self, parsed_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Filter parsed data to only include relevant rows for AI extraction.
        This reduces prompt size significantly.
        
        Only keeps:
        - First 40 rows with actual data (usually enough for all routes)
        - Rows with multiple non-null values (actual data rows)
        - Skip notes, footers, contact info
        """
        filtered = {
            "file_type": parsed_data.get("file_type", ""),
            "sheets": []
        }
        
        for sheet in parsed_data.get("sheets", []):
            filtered_sheet = {
                "name": sheet.get("name", ""),
                "columns": sheet.get("columns", [])[:12],  # Limit columns
                "rows": sheet.get("rows", 0),
                "data": []
            }
            
            data = sheet.get("data", [])
            included_rows = 0
            max_rows = 40  # Limit to 40 most relevant rows
            
            for row in data:
                if included_rows >= max_rows:
                    break
                    
                if not isinstance(row, dict):
                    continue
                
                # Get non-null values
                values = [v for v in row.values() if v is not None and str(v).strip()]
                
                # Skip empty rows
                if not values:
                    continue
                
                # Skip rows that are clearly notes/footers (single cell with long text)
                if len(values) == 1:
                    val = str(values[0])
                    # Skip contact info, notes, department info
                    if any(skip in val.lower() for skip in ['@', 'tel', 'note', 'ms.', 'mr.', 'department', 'customer service', 'documentation', 'operations', 'subject to']):
                        continue
                    # Skip very long single values (probably notes)
                    if len(val) > 80:
                        continue
                
                # Create a simplified row with only first 10 key-value pairs
                simplified_row = {}
                for i, (k, v) in enumerate(row.items()):
                    if i >= 10:  # Limit columns per row
                        break
                    if v is not None:
                        simplified_row[k] = v
                
                if simplified_row:
                    filtered_sheet["data"].append(simplified_row)
                    included_rows += 1
            
            # Only include sheets with data
            if filtered_sheet["data"]:
                filtered["sheets"].append(filtered_sheet)
        
        return filtered
    
    def _build_extraction_prompt(
        self,
        parsed_data: Dict[str, Any],
        file_name: str,
        existing_rate_sheets: Optional[List[Dict[str, Any]]]
    ) -> str:
        """Build comprehensive prompt for AI extraction with format-specific guidance"""
        
        # Detect format hints from the data
        format_hints = self._detect_format_hints(parsed_data, file_name)
        
        # Filter data to reduce prompt size
        filtered_data = self._filter_relevant_data(parsed_data)
        
        prompt = f"""You are an expert freight forwarding rate sheet data extractor. Your task is to ACCURATELY extract ALL pricing data from this rate sheet.

FILE NAME: {file_name}

DETECTED FORMAT HINTS:
{json.dumps(format_hints, indent=2, default=str)}

PARSED DATA (filtered to show only relevant rows):
{json.dumps(filtered_data, indent=2, default=str)}

=== CRITICAL EXTRACTION RULES ===

1. **DIRECTION DETECTION** - This is the MOST IMPORTANT step:
   - Look for the ORIGIN port/city in the HEADER row or sheet title (e.g., "LAEM CHABANG" or "PORT KLANG")
   - The ports listed in the DATA ROWS are typically the DESTINATIONS
   - Example: If header says "LAEM CHABANG" and rows list "NHAVA SHEVA", "MUNDRA", etc., then:
     * Origin = LAEM CHABANG (Thailand)
     * Destinations = NHAVA SHEVA, MUNDRA, etc. (India)
   - For "POL/POD" format: POL = Port of Loading (Origin), POD = Port of Discharge (Destination)

2. **EXTRACT ALL PRICING COLUMNS** - Create SEPARATE pricing_tiers for EACH price column:
   - If there are columns for "20'" and "40'" → extract BOTH as separate pricing_tiers
   - If there are VGM tiers like "VGM UPTO 18MT 20'" and "VGM UPTO 26MT 20'" → extract EACH as separate pricing_tiers
   - If rate shows range like "$850 - $900", use the LOWER value (850) as base_rate
   - NEVER skip a pricing column - every price column must become a pricing_tier

3. **HANDLE DIFFERENT FORMATS**:
   
   FORMAT A - "POL/POD" Style (e.g., MAXICON):
   - IMPORTANT: The Excel headers may be in a DATA ROW, not the column names!
   - If column names are "MAXICON CONTAINER LINE", "Unnamed: 1", etc., look at the FIRST DATA ROW
   - The first data row often contains: POL | POD | ROUTING | 20' | 40' | TRANSIT TIME | FREE DETENTION | REMARKS
   - Data rows starting after the header row have actual port data:
     * First column (POL): Origin port like "PORT KLANG"
     * Second column (POD): Destination port like "NHAVA SHEVA", "CHENNAI", "SINGAPORE"
     * Third column (ROUTING): "Direct" or "via XXX"
     * Fourth/Fifth columns: 20' and 40' prices
   - SKIP section header rows like "INDIAN SECTORS", "MIDDLE EAST SECTORS", "FAR EAST SECTORS", "ISC"
   - Look for validity date in format "1-1-2026 to 31-1-2026"
   - POL is origin (e.g., PORT KLANG), POD is destination
   
   FORMAT B - "Origin Header" Style (e.g., Thailand rate sheets):
   - First row has origin port name (e.g., "LAEM CHABANG")
   - Column 1 lists destination ports (NHAVA SHEVA, MUNDRA, CHENNAI, etc.)
   - Subsequent columns have pricing by container type
   - May have VGM-based pricing: "VGM UPTO 18MT 20'" means 20' container with max 18 metric tons
   
   FORMAT C - "Projection" Style:
   - Similar to Format B but includes volume targets
   - Columns: PORT OF DISCHARGE | 20' (target) | 40' (target) | TOTAL TEUS | FREIGHT 20' | FREIGHT 40'
   - FREIGHT columns contain the actual rates

4. **PORT NAME STANDARDIZATION**:
   - Use FULL port names: "NHAVA SHEVA" not "NHV", "LAEM CHABANG" not "LCB"
   - Common Indian ports: NHAVA SHEVA (Mumbai), MUNDRA, CHENNAI, KOLKATA/KOLKATTA, PIPAVAV, KATTUPALLI, VIZAG/VISAKHAPATNAM
   - Common Thai ports: LAEM CHABANG, BANGKOK
   - Common Malaysian ports: PORT KLANG

5. **DATA QUALITY**:
   - Skip rows that are section headers (e.g., "INDIAN SECTORS", "ISC", "ICD")
   - Skip rows with no pricing data
   - Extract transit time as integer days when possible (e.g., "7 days" → 7)
   - Extract free detention as integer days (e.g., "14 days" → 14)
   - Identify routing: "Direct" vs "via SIN" vs "via PKG/SIN"

=== REQUIRED OUTPUT FORMAT ===

Return ONLY a valid JSON object (no markdown, no explanation):
{{
    "rate_sheet_type": "ocean_freight",
    "carrier_name": "string or null",
    "title": "extracted title from file",
    "validity": {{
        "valid_from": "YYYY-MM-DD or null",
        "valid_to": "YYYY-MM-DD or null",
        "effective_date": "YYYY-MM-DD or null"
    }},
    "routes": [
        {{
            "origin_port": "FULL PORT NAME (e.g., LAEM CHABANG)",
            "origin_country": "country name",
            "origin_city": "city name",
            "origin_code": "3-letter code or null",
            "destination_port": "FULL PORT NAME (e.g., NHAVA SHEVA)",
            "destination_country": "country name", 
            "destination_city": "city name",
            "destination_code": "3-letter code or null",
            "routing": "Direct or via XXX",
            "transit_time_days": integer_or_null,
            "transit_time_text": "string or null",
            "service_type": "FCL",
            "is_direct": true_or_false,
            "free_detention_days": integer_or_null,
            "free_detention_text": "string or null",
            "remarks": "any remarks",
            "pricing_tiers": [
                {{
                    "container_type": "20'",
                    "container_size": 20,
                    "container_height": "Standard",
                    "base_rate": numeric_value,
                    "currency": "USD",
                    "vgm_min_weight_mt": null,
                    "vgm_max_weight_mt": 18,
                    "remarks": null,
                    "surcharges": [],
                    "charges": []
                }},
                {{
                    "container_type": "40'",
                    "container_size": 40,
                    "container_height": "Standard",
                    "base_rate": numeric_value,
                    "currency": "USD",
                    "vgm_min_weight_mt": null,
                    "vgm_max_weight_mt": 26,
                    "remarks": null,
                    "surcharges": [],
                    "charges": []
                }}
            ]
        }}
    ],
    "relationships": {{
        "is_related": false,
        "relationship_type": "independent",
        "related_to_rate_sheets": [],
        "confidence_score": 90,
        "reasoning": "explanation"
    }},
    "detected_format": "Format A/B/C description",
    "confidence_score": 90,
    "extraction_notes": "any issues or notes"
}}

REMEMBER:
- Extract EVERY route with pricing
- Extract EVERY pricing column as a separate pricing_tier
- Use FULL port names (NHAVA SHEVA, not NHV)
- Get the direction right (origin vs destination)
- Return ONLY valid JSON, no other text
"""
        return prompt
    
    def _detect_format_hints(self, parsed_data: Dict[str, Any], file_name: str) -> Dict[str, Any]:
        """Detect format hints to help AI understand the structure"""
        hints = {
            "file_name_hints": [],
            "detected_format": "unknown",
            "likely_origin": None,
            "has_pol_pod_columns": False,
            "has_vgm_pricing": False,
            "pricing_columns": [],
            "column_structure": [],
            "actual_headers_in_data": [],
            "sample_data_rows": []
        }
        
        file_lower = file_name.lower()
        
        # File name hints
        if "thailand" in file_lower:
            hints["file_name_hints"].append("Thailand route - likely LAEM CHABANG as origin or destination")
        if "maxicon" in file_lower:
            hints["file_name_hints"].append("MAXICON shipping line - likely POL/POD format with PORT KLANG as origin")
            hints["detected_format"] = "MAXICON POL/POD format"
        if "projection" in file_lower:
            hints["file_name_hints"].append("Projection format with volume targets")
        if "jan" in file_lower or "2026" in file_lower:
            hints["file_name_hints"].append("January 2026 rates")
        if "sept" in file_lower:
            hints["file_name_hints"].append("September rates")
        
        # Analyze columns from first sheet
        if parsed_data.get("sheets"):
            first_sheet = parsed_data["sheets"][0]
            columns = first_sheet.get("columns", [])
            data = first_sheet.get("data", [])
            
            hints["column_structure"] = columns[:15]  # First 15 columns
            
            # Check for POL/POD format in column names
            col_str = " ".join(str(c).upper() for c in columns)
            if "POL" in col_str or "POD" in col_str:
                hints["has_pol_pod_columns"] = True
                hints["detected_format"] = "POL/POD format"
            
            # IMPORTANT: Also check first data rows for POL/POD headers
            # Sometimes the actual headers are in the data rows, not column names
            if data:
                first_rows = data[:5]
                hints["sample_data_rows"] = first_rows[:3]  # Send first 3 data rows as hints
                
                for row_idx, row in enumerate(first_rows):
                    if isinstance(row, dict):
                        row_values = [str(v).upper() if v else "" for v in row.values()]
                        row_str = " ".join(row_values)
                        
                        # Check if this row looks like headers (contains POL, POD, etc.)
                        if "POL" in row_str and "POD" in row_str:
                            hints["has_pol_pod_columns"] = True
                            hints["detected_format"] = "POL/POD format (headers in data row)"
                            # Extract the actual headers from this row
                            actual_headers = list(row.values())
                            hints["actual_headers_in_data"] = [str(h) for h in actual_headers if h]
                        
                        # Check for VGM in data rows
                        if "VGM" in row_str:
                            hints["has_vgm_pricing"] = True
                        
                        # Detect pricing columns from data
                        for val in row_values:
                            if any(x in val for x in ["20'", "40'", "FREIGHT", "RATE"]):
                                if val not in hints["pricing_columns"]:
                                    hints["pricing_columns"].append(val)
                        
                        # Try to detect origin from data
                        for key, value in row.items():
                            val_str = str(value).upper() if value else ""
                            if any(port in val_str for port in ["LAEM CHABANG", "PORT KLANG", "BANGKOK", "SINGAPORE"]):
                                if not hints["likely_origin"]:
                                    hints["likely_origin"] = val_str
            
            # Check for VGM pricing in column names
            if "VGM" in col_str:
                hints["has_vgm_pricing"] = True
            
            # Detect pricing columns from column names
            for col in columns:
                col_upper = str(col).upper()
                if any(x in col_upper for x in ["20'", "40'", "FREIGHT", "RATE"]):
                    if str(col) not in hints["pricing_columns"]:
                        hints["pricing_columns"].append(str(col))
        
        return hints
    
    def _fallback_extraction(self, parsed_data: Dict[str, Any], file_name: str) -> Dict[str, Any]:
        """Fallback extraction when AI service is unavailable"""
        logger.warning("Using fallback extraction - AI service unavailable")
        
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
                "reasoning": "Fallback extraction - AI service unavailable"
            },
            "detected_format": "unknown",
            "confidence_score": 0,
            "extraction_notes": "Fallback extraction used - manual review required"
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
        except httpx.ConnectError as e:
            logger.error(f"Error detecting relationships: Cannot connect to {self.ai_service_url} - {str(e) or 'Connection refused'}")
            return {
                "is_related": False,
                "relationship_type": "independent",
                "related_to_rate_sheets": [],
                "confidence_score": 0,
                "reasoning": f"AI service unavailable: Connection error"
            }
        except httpx.TimeoutException as e:
            logger.error(f"Error detecting relationships: Request timeout - {str(e) or 'Request timed out'}")
            return {
                "is_related": False,
                "relationship_type": "independent",
                "related_to_rate_sheets": [],
                "confidence_score": 0,
                "reasoning": f"AI service unavailable: Request timeout"
            }
        except Exception as e:
            error_msg = str(e) if str(e) else f"{type(e).__name__} (no message)"
            logger.error(f"Error detecting relationships: {error_msg}", exc_info=True)
            return {
                "is_related": False,
                "relationship_type": "independent",
                "related_to_rate_sheets": [],
                "confidence_score": 0,
                "reasoning": f"Error detecting relationships: {error_msg}"
            }


# Backward compatibility alias
AIAnalyzer = RateSheetExtractor
