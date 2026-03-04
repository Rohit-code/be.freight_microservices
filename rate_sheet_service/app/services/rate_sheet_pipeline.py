"""
Rate Sheet Processing Pipeline

FLOW:
1. PANDAS NORMALIZATION (NO AI) - Convert Excel to clean grid + metadata
2. AI SEMANTIC EXTRACTION - Map normalized data to structured schema
3. VALIDATION + GUARDRAILS - Deterministic checks before saving
4. STORAGE - SQL + Graph + ChromaDB

This is the single source of truth for rate sheet processing.
"""

import pandas as pd
import numpy as np
import re
import json
import httpx
import logging
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass, asdict
from enum import Enum

logger = logging.getLogger(__name__)


# =============================================================================
# SCHEMA DEFINITIONS
# =============================================================================

class ContainerType(Enum):
    """Standard container types"""
    TWENTY_FT = "20'"
    FORTY_FT = "40'"
    FORTY_HC = "40'HC"
    FORTY_FIVE_FT = "45'"


@dataclass
class PricingTier:
    """Single pricing tier for a container type"""
    container_type: str  # "20'", "40'", "40'HC"
    container_size: int  # 20, 40, 45
    base_rate: float  # e.g., 650.0
    currency: str  # "USD", "EUR"
    vgm_min_weight_mt: Optional[float] = None  # Minimum VGM weight
    vgm_max_weight_mt: Optional[float] = None  # Maximum VGM weight (e.g., 18, 26)
    surcharges: Optional[List[Dict]] = None  # BAF, CAF, PSS, etc.
    remarks: Optional[str] = None


@dataclass
class Route:
    """Single route with all pricing"""
    origin_port: str  # "LAEM CHABANG"
    origin_country: str  # "Thailand"
    origin_code: Optional[str]  # "LCB"
    destination_port: str  # "NHAVA SHEVA"
    destination_country: str  # "India"
    destination_code: Optional[str]  # "NSA"
    routing: str  # "Direct" or "via SIN"
    transit_time_days: Optional[int]  # 7
    service_type: str  # "FCL"
    free_detention_days: Optional[int]  # 14
    remarks: Optional[str]
    pricing_tiers: List[PricingTier]


@dataclass
class RateSheet:
    """Complete rate sheet structure"""
    # Metadata
    rate_sheet_type: str  # "ocean_freight"
    carrier_name: Optional[str]  # "MAXICON"
    title: Optional[str]
    file_name: str
    
    # Validity
    valid_from: Optional[str]  # "2026-01-01"
    valid_to: Optional[str]  # "2026-01-31"
    
    # Routes
    routes: List[Route]
    
    # Extraction info
    extraction_method: str  # "pandas_ai_pipeline"
    confidence_score: float  # 0-100
    extraction_notes: Optional[str]


# =============================================================================
# STAGE 1: PANDAS NORMALIZATION (NO AI)
# =============================================================================

class PandasNormalizer:
    """
    Stage 1: Deterministic Excel Normalization
    
    NO AI INVOLVED - Pure pandas/openpyxl processing
    
    Goal: Convert any messy Excel into a machine-readable grid + metadata
    """
    
    def __init__(self):
        pass
    
    def normalize(self, file_path: str) -> Dict[str, Any]:
        """
        Normalize an Excel file into clean grid + metadata.
        
        Returns:
            {
                "file_name": str,
                "file_type": str,
                "sheets": [
                    {
                        "name": str,
                        "grid": [[cell, cell, ...], ...],  # 2D array
                        "dimensions": {"rows": int, "cols": int},
                        "detected_header_row": int,
                        "metadata": {...}
                    }
                ],
                "detected_metadata": {
                    "potential_carriers": [],
                    "potential_origins": [],
                    "potential_destinations": [],
                    "potential_validity": {}
                }
            }
        """
        logger.info(f"📊 [STAGE 1: PANDAS] Starting normalization for: {file_path}")
        
        file_name = Path(file_path).name
        file_type = Path(file_path).suffix.lower()
        
        result = {
            "file_name": file_name,
            "file_type": file_type,
            "sheets": [],
            "detected_metadata": {
                "potential_carriers": set(),
                "potential_origins": set(),
                "potential_destinations": set(),
                "potential_validity": {},
                "potential_volume_data": False
            }
        }
        
        try:
            # Read Excel file
            if file_type == '.xlsx':
                excel_file = pd.ExcelFile(file_path, engine='openpyxl')
            elif file_type == '.xls':
                excel_file = pd.ExcelFile(file_path, engine='xlrd')
            elif file_type == '.csv':
                df = pd.read_csv(file_path, header=None)
                sheet_data = self._normalize_sheet(df, "Sheet1")
                result["sheets"].append(sheet_data)
                self._update_metadata(result, sheet_data)
                return self._finalize_result(result)
            else:
                raise ValueError(f"Unsupported file type: {file_type}")
            
            # Process each sheet
            for sheet_name in excel_file.sheet_names:
                df = pd.read_excel(excel_file, sheet_name=sheet_name, header=None)
                
                if df.empty or df.shape[0] < 2:
                    logger.info(f"   Skipping empty sheet: {sheet_name}")
                    continue
                
                sheet_data = self._normalize_sheet(df, sheet_name)
                result["sheets"].append(sheet_data)
                self._update_metadata(result, sheet_data)
            
            return self._finalize_result(result)
            
        except Exception as e:
            logger.error(f"❌ [STAGE 1] Normalization failed: {e}", exc_info=True)
            raise
    
    def _normalize_sheet(self, df: pd.DataFrame, sheet_name: str) -> Dict[str, Any]:
        """Normalize a single sheet into clean grid format"""
        
        # Clean the dataframe
        df = df.fillna('')
        df = df.astype(str)
        
        # Remove completely empty rows and columns
        df = df.loc[~(df == '').all(axis=1)]
        df = df.loc[:, ~(df == '').all(axis=0)]
        
        if df.empty:
            return {"name": sheet_name, "grid": [], "dimensions": {"rows": 0, "cols": 0}}
        
        # Convert to 2D grid (list of lists)
        grid = df.values.tolist()
        
        # Detect header row
        header_row = self._detect_header_row(grid)
        
        # Extract metadata from sheet
        metadata = self._extract_sheet_metadata(grid)
        
        return {
            "name": sheet_name,
            "grid": grid,
            "dimensions": {"rows": len(grid), "cols": len(grid[0]) if grid else 0},
            "detected_header_row": header_row,
            "metadata": metadata
        }
    
    def _detect_header_row(self, grid: List[List[str]]) -> int:
        """Detect which row is likely the header row"""
        
        header_keywords = [
            'pol', 'pod', 'origin', 'destination', 'port', 'discharge', 'loading',
            '20', '40', 'rate', 'price', 'freight', 'usd', 'cost',
            'transit', 'detention', 'remarks', 'routing', 'service',
            'vgm', 'container', 'teu'
        ]
        
        best_row = 0
        best_score = 0
        
        for row_idx, row in enumerate(grid[:15]):
            row_text = " ".join([str(cell).lower() for cell in row])
            score = sum(1 for kw in header_keywords if kw in row_text)
            
            if score > best_score:
                best_score = score
                best_row = row_idx
        
        return best_row
    
    def _extract_sheet_metadata(self, grid: List[List[str]]) -> Dict[str, Any]:
        """Extract metadata from sheet using pattern matching (NO AI)"""
        
        metadata = {
            "carriers": [],
            "origins": [],
            "destinations": [],
            "validity": {},
            "has_vgm_pricing": False,
            "has_pol_pod": False
        }
        
        # Flatten grid to text for pattern matching
        full_text = " ".join([" ".join([str(cell) for cell in row]) for row in grid])
        full_text_upper = full_text.upper()
        
        # Detect carriers
        carriers = ['MAXICON', 'MSC', 'MAERSK', 'CMA CGM', 'HAPAG', 'ONE', 'EVERGREEN', 'COSCO', 'PIL']
        for carrier in carriers:
            if carrier in full_text_upper:
                metadata["carriers"].append(carrier)
        
        # Detect ports
        known_origins = ["LAEM CHABANG", "PORT KLANG", "BANGKOK", "SINGAPORE", "TANJUNG PELEPAS", "PENANG"]
        known_destinations = [
            "NHAVA SHEVA", "MUNDRA", "CHENNAI", "KOLKATA", "KOLKATTA", "PIPAVAV", 
            "KATTUPALLI", "VIZAG", "VISAKHAPATNAM", "HALDIA", "JEBEL ALI", "JEDDAH",
            "KARACHI", "CHITTAGONG", "YANGON", "JAKARTA", "AQABA"
        ]
        
        for port in known_origins:
            if port in full_text_upper:
                metadata["origins"].append(port)
        
        for port in known_destinations:
            if port in full_text_upper:
                metadata["destinations"].append(port)
        
        # Detect validity dates
        date_pattern = r'(\d{1,2}[-/]\d{1,2}[-/]\d{4})\s*(?:to|TO|-)\s*(\d{1,2}[-/]\d{1,2}[-/]\d{4})'
        date_match = re.search(date_pattern, full_text)
        if date_match:
            metadata["validity"] = {
                "raw_from": date_match.group(1),
                "raw_to": date_match.group(2)
            }
        
        # Detect format hints
        if "VGM" in full_text_upper:
            metadata["has_vgm_pricing"] = True
        if "POL" in full_text_upper and "POD" in full_text_upper:
            metadata["has_pol_pod"] = True
        
        # Detect volume/projection data (like Cursor: understand what kind of data the sheet has)
        volume_keywords = ["TOTAL TEUS", "LOCATION TARGET", "TOTAL TEU", "PORT OF DISCHARGE", "TARGET"]
        metadata["has_volume_or_projection_data"] = any(kw in full_text_upper for kw in volume_keywords)
        
        return metadata
    
    def _update_metadata(self, result: Dict, sheet_data: Dict):
        """Update overall metadata from sheet data"""
        meta = sheet_data.get("metadata", {})
        result["detected_metadata"]["potential_carriers"].update(meta.get("carriers", []))
        result["detected_metadata"]["potential_origins"].update(meta.get("origins", []))
        result["detected_metadata"]["potential_destinations"].update(meta.get("destinations", []))
        if meta.get("validity") and not result["detected_metadata"]["potential_validity"]:
            result["detected_metadata"]["potential_validity"] = meta["validity"]
        if meta.get("has_volume_or_projection_data"):
            result["detected_metadata"]["potential_volume_data"] = True
    
    def _finalize_result(self, result: Dict) -> Dict:
        """Convert sets to lists for JSON serialization"""
        result["detected_metadata"]["potential_carriers"] = list(result["detected_metadata"]["potential_carriers"])
        result["detected_metadata"]["potential_origins"] = list(result["detected_metadata"]["potential_origins"])
        result["detected_metadata"]["potential_destinations"] = list(result["detected_metadata"]["potential_destinations"])
        
        logger.info(f"✅ [STAGE 1] Normalization complete: {len(result['sheets'])} sheets processed")
        logger.info(f"   Detected: carriers={result['detected_metadata']['potential_carriers']}")
        logger.info(f"   Detected: origins={result['detected_metadata']['potential_origins']}")
        logger.info(f"   Detected: destinations={result['detected_metadata']['potential_destinations']}")
        logger.info(f"   Detected: potential_volume_data={result['detected_metadata'].get('potential_volume_data', False)}")
        
        return result


# =============================================================================
# STAGE 2: AI SEMANTIC EXTRACTION
# =============================================================================

class AISemanticExtractor:
    """
    Stage 2: AI-Assisted Semantic Extraction
    
    THIS IS WHERE AI SHINES
    
    Goal: Map normalized grid to structured schema with:
    - Ports (origin, destination)
    - Costs (20', 40', with VGM tiers)
    - Routes
    - Transit times
    - Validity/expiration
    - Remarks
    """
    
    # Define the exact schema AI must return
    REQUIRED_SCHEMA = {
        "rate_sheet_type": "string - 'ocean_freight', 'air_freight', etc.",
        "carrier_name": "string or null - carrier/shipping line name",
        "title": "string - rate sheet title",
        "valid_from": "string - ISO date YYYY-MM-DD or null",
        "valid_to": "string - ISO date YYYY-MM-DD or null",
        "routes": [
            {
                "origin_port": "string - FULL port name (e.g., 'LAEM CHABANG')",
                "origin_country": "string - country name",
                "origin_code": "string or null - port code",
                "destination_port": "string - FULL port name (e.g., 'NHAVA SHEVA')",
                "destination_country": "string - country name",
                "destination_code": "string or null - port code",
                "routing": "string - 'Direct' or 'via PORTNAME'",
                "transit_time_days": "integer or null - number of days",
                "service_type": "string - 'FCL', 'LCL', etc.",
                "free_detention_days": "integer or null",
                "remarks": "string or null",
                "pricing_tiers": [
                    {
                        "container_type": "string - '20\\'', '40\\'', '40\\'HC'",
                        "container_size": "integer - 20, 40, 45",
                        "base_rate": "number - the price (e.g., 650)",
                        "currency": "string - 'USD', 'EUR'",
                        "vgm_max_weight_mt": "number or null - max weight in metric tons",
                        "surcharges": "array or null - list of surcharges",
                        "remarks": "string or null - e.g., 'VGM up to 18MT'"
                    }
                ]
            }
        ],
        "confidence_score": "integer 0-100",
        "extraction_notes": "string - any issues or notes"
    }
    
    def __init__(self, ai_service_url: str):
        self.ai_service_url = ai_service_url
    
    async def extract(self, normalized_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Extract structured data from normalized grid using AI.
        
        Returns the structured rate sheet data.
        """
        logger.info("🤖 [STAGE 2: AI] Starting semantic extraction")
        
        # Build the prompt
        prompt = self._build_extraction_prompt(normalized_data)
        
        # Call AI service
        try:
            async with httpx.AsyncClient(timeout=300.0) as client:
                response = await client.post(
                    f"{self.ai_service_url}/api/ai/chat",
                    json={
                        "message": prompt,
                        "conversation_history": [],
                        "temperature": 0.1
                    }
                )
                response.raise_for_status()
                result = response.json()
                
                content = result.get("response", "")
                
                # Parse JSON from response
                extracted = self._parse_ai_response(content)
                
                # Print what AI gave us
                self._log_extraction_result(extracted)
                
                return extracted
                
        except Exception as e:
            logger.error(f"❌ [STAGE 2] AI extraction failed: {e}", exc_info=True)
            raise
    
    def _build_extraction_prompt(self, normalized_data: Dict[str, Any]) -> str:
        """Build the AI extraction prompt"""
        
        # Format grid data for AI
        grid_text = self._format_grid_for_ai(normalized_data)
        
        prompt = f"""You are an expert freight forwarding rate sheet data extractor.

## TASK
Extract ALL shipping rate data from the normalized Excel grid below.

## FILE INFO
- File: {normalized_data.get('file_name', 'Unknown')}
- Detected Carriers: {normalized_data['detected_metadata'].get('potential_carriers', [])}
- Detected Origins: {normalized_data['detected_metadata'].get('potential_origins', [])}
- Detected Destinations: {normalized_data['detected_metadata'].get('potential_destinations', [])}
- Detected Validity: {normalized_data['detected_metadata'].get('potential_validity', {})}
- Potential volume/projection data (TOTAL TEUS, LOCATION TARGET): {normalized_data['detected_metadata'].get('potential_volume_data', False)}

## NORMALIZED GRID DATA

{grid_text}

## EXTRACTION RULES

### 1. PORTS
- **Origin Port (POL)**: Where cargo STARTS. Usually in header or first column.
  - Common origins: LAEM CHABANG, PORT KLANG, BANGKOK, SINGAPORE
- **Destination Port (POD)**: Where cargo ENDS. Usually in data rows.
  - Common destinations: NHAVA SHEVA, MUNDRA, CHENNAI, KOLKATA, JEBEL ALI

### 2. PRICING - CRITICAL!
Extract ALL pricing columns. Each rate sheet may have:
- **20' container rate** - Price for 20-foot container
- **40' container rate** - Price for 40-foot container (DIFFERENT from 20'!)
- **VGM tiers** - Different prices based on cargo weight:
  - "VGM up to 18MT" = Max 18 metric tons
  - "VGM up to 26MT" = Max 26 metric tons

**IMPORTANT**: 
- 20' and 40' are SEPARATE prices - never use 20' price for 40'!
- If you see columns like "VGM UPTO 18MT 20'" and "VGM UPTO 26MT 40'" - these are DIFFERENT!
- If rate shows range (e.g., "525-550"), use the LOWER value (525)

### 3. VESSEL SPACE / CAPACITY
- **space_available**: Integer - slots or TEUs left on the vessel for this route (e.g. "20 TEUs left", "slots: 15" → 20 or 15). Look for: "TOTAL TEUS", "space left", "slots", "available", "remaining", "capacity".
- **space_unit**: "TEU" or "container" - unit for space_available. Default "TEU" if not stated.
- **vessel_name**: Name of vessel if present in the sheet.

### 4. OTHER FIELDS
- **Routing**: "Direct" or "via PORTNAME" (e.g., "via SIN", "via PKG")
- **Transit Time**: Number of days (e.g., "7 days" → 7)
- **Free Detention**: Days at destination (e.g., "14 days" → 14)
- **Remarks**: Any notes (e.g., "Loading on CCS", "Subject to slot availability")
- **Validity**: Date range (e.g., "1-1-2026 to 31-1-2026")

### 5. SKIP THESE ROWS
- Section headers: "INDIAN SECTORS", "MIDDLE EAST", "FAR EAST"
- Totals: "TOTAL", sum rows
- Empty rows

<<<<<<< HEAD
### 6. DATA UNDERSTANDING (like Cursor: understand what kind of data this sheet has)
=======
### 5. DATA UNDERSTANDING (like Cursor: understand what kind of data this sheet has)
>>>>>>> 01adec3f107df1e8b1d96d91d37e75674eea59bb
- **Rates-only sheet**: Contains only POL/POD, 20'/40' prices, transit, validity. No volume or container-count columns.
- **Rates + volume/projection sheet**: Has columns like "TOTAL TEUS", "LOCATION TARGET", "20'" and "40'" as TARGET quantities (not prices), or "PORT OF DISCHARGE" with numeric targets. May have a row "TOTAL" with TEU counts.
- If you see TOTAL TEUS, LOCATION TARGET, or numeric targets by location/period, set **contains_volume_or_projection_data** true and fill **volume_summary** with a short line (e.g. "Laem Chabang Jan 2026: 200 TEUs; Bangkok Jan 2026: 55 TEUs"). Otherwise set contains_volume_or_projection_data false and volume_summary null.

## REQUIRED OUTPUT FORMAT

Return ONLY valid JSON (no markdown, no explanation):

```json
{{
    "rate_sheet_type": "ocean_freight",
    "carrier_name": "CARRIER NAME or null",
    "title": "Rate sheet title",
    "valid_from": "2026-01-01 or null",
    "valid_to": "2026-01-31 or null",
    "routes": [
        {{
            "origin_port": "LAEM CHABANG",
            "origin_country": "Thailand",
            "origin_code": "LCB",
            "destination_port": "NHAVA SHEVA",
            "destination_country": "India",
            "destination_code": "NSA",
            "routing": "Direct",
            "transit_time_days": 7,
            "service_type": "FCL",
            "free_detention_days": 14,
            "remarks": "via PKG/SIN",
<<<<<<< HEAD
            "vessel_name": null,
            "space_available": 20,
            "space_unit": "TEU",
=======
>>>>>>> 01adec3f107df1e8b1d96d91d37e75674eea59bb
            "pricing_tiers": [
                {{
                    "container_type": "20'",
                    "container_size": 20,
                    "base_rate": 650,
                    "currency": "USD",
                    "vgm_max_weight_mt": 18,
                    "surcharges": null,
                    "remarks": "VGM up to 18MT"
                }},
                {{
                    "container_type": "20'",
                    "container_size": 20,
                    "base_rate": 700,
                    "currency": "USD",
                    "vgm_max_weight_mt": 26,
                    "surcharges": null,
                    "remarks": "VGM up to 26MT"
                }},
                {{
                    "container_type": "40'",
                    "container_size": 40,
                    "base_rate": 1100,
                    "currency": "USD",
                    "vgm_max_weight_mt": 26,
                    "surcharges": null,
                    "remarks": "VGM up to 26MT"
                }}
            ]
        }}
    ],
    "confidence_score": 95,
    "extraction_notes": "Successfully extracted X routes",
    "data_understanding": {{
        "contains_volume_or_projection_data": false,
        "volume_summary": null
    }}
}}
```

- **data_understanding**: Set contains_volume_or_projection_data true only if the sheet has volume/TEU/projection data (TOTAL TEUS, LOCATION TARGET, target quantities). Set volume_summary to a one-line summary (e.g. "Laem Chabang Jan 2026: 200 TEUs; Bangkok Jan 2026: 55 TEUs") or null if rates-only.

## CRITICAL REMINDERS
1. Extract EVERY route with pricing
2. 20' and 40' rates are DIFFERENT - extract both separately!
3. If VGM tiers exist, extract EACH tier as separate pricing_tier
4. Use FULL port names (NHAVA SHEVA, not NHV)
5. Return ONLY valid JSON
"""
        return prompt
    
    def _format_grid_for_ai(self, normalized_data: Dict[str, Any]) -> str:
        """Format normalized grid data for AI consumption"""
        
        parts = []
        
        for sheet in normalized_data.get("sheets", []):
            parts.append(f"\n{'='*60}")
            parts.append(f"SHEET: {sheet['name']}")
            parts.append(f"Dimensions: {sheet['dimensions']['rows']} rows x {sheet['dimensions']['cols']} cols")
            parts.append(f"Header Row: {sheet.get('detected_header_row', 0)}")
            parts.append('='*60)
            
            grid = sheet.get("grid", [])
            header_row = sheet.get("detected_header_row", 0)
            
            for row_idx, row in enumerate(grid):
                row_values = [str(cell).strip() for cell in row]
                row_str = " | ".join(row_values)
                
                if row_idx == header_row:
                    parts.append(f"[HEADER] {row_str}")
                    parts.append("-" * 60)
                else:
                    parts.append(f"[Row {row_idx}] {row_str}")
        
        return "\n".join(parts)
    
    def _parse_ai_response(self, content: str) -> Dict[str, Any]:
        """Parse JSON from AI response"""
        
        try:
            # Find JSON in response
            json_start = content.find("{")
            json_end = content.rfind("}") + 1
            
            if json_start >= 0 and json_end > json_start:
                json_str = content[json_start:json_end]
                data = json.loads(json_str)
                # Default data_understanding (Cursor-style: what kind of data this sheet has)
                data.setdefault("data_understanding", {
                    "contains_volume_or_projection_data": False,
                    "volume_summary": None
                })
                return data
            else:
                raise ValueError("No JSON found in AI response")
                
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse AI response: {e}")
            raise
    
    def _log_extraction_result(self, extracted: Dict[str, Any]):
        """Print what AI extracted for debugging"""
        
        print("\n" + "=" * 80)
        print("🤖 AI EXTRACTION RESULT")
        print("=" * 80)
        
        print(f"\n📋 METADATA:")
        print(f"   - Rate Sheet Type: {extracted.get('rate_sheet_type')}")
        print(f"   - Carrier: {extracted.get('carrier_name')}")
        print(f"   - Title: {extracted.get('title')}")
        print(f"   - Valid From: {extracted.get('valid_from')}")
        print(f"   - Valid To: {extracted.get('valid_to')}")
        print(f"   - Confidence: {extracted.get('confidence_score')}%")
        
        routes = extracted.get("routes", [])
        print(f"\n📍 ROUTES EXTRACTED: {len(routes)}")
        
        for i, route in enumerate(routes[:10], 1):  # Show first 10
            print(f"\n   Route {i}: {route.get('origin_port')} → {route.get('destination_port')}")
            print(f"      - Routing: {route.get('routing')}")
            print(f"      - Transit: {route.get('transit_time_days')} days")
            print(f"      - Free Detention: {route.get('free_detention_days')} days")
            print(f"      - Remarks: {route.get('remarks')}")
            
            pricing_tiers = route.get("pricing_tiers", [])
            print(f"      - Pricing Tiers: {len(pricing_tiers)}")
            for tier in pricing_tiers:
                vgm = f" (VGM≤{tier.get('vgm_max_weight_mt')}MT)" if tier.get('vgm_max_weight_mt') else ""
                print(f"         • {tier.get('container_type')}: {tier.get('currency')} {tier.get('base_rate')}{vgm}")
        
        if len(routes) > 10:
            print(f"\n   ... and {len(routes) - 10} more routes")
        
        du = extracted.get("data_understanding", {})
        print(f"\n📊 DATA UNDERSTANDING: volume/projection={du.get('contains_volume_or_projection_data')} | summary={du.get('volume_summary')}")
        print(f"\n📝 EXTRACTION NOTES: {extracted.get('extraction_notes')}")
        print("=" * 80 + "\n")
        
        logger.info(f"✅ [STAGE 2] AI extracted {len(routes)} routes")


# =============================================================================
# STAGE 3: VALIDATION + GUARDRAILS
# =============================================================================

class DataValidator:
    """
    Stage 3: Validation + Guardrails
    
    MANDATORY - All data must pass validation before storage
    
    Deterministic checks:
    - Is base_rate numeric?
    - Are ports valid?
    - Is valid_from <= valid_to?
    - Is currency known?
    """
    
    KNOWN_CURRENCIES = {"USD", "EUR", "GBP", "SGD", "MYR", "THB", "INR", "AED"}
    
    KNOWN_PORTS = {
        # Origins
        "LAEM CHABANG", "PORT KLANG", "BANGKOK", "SINGAPORE", "TANJUNG PELEPAS",
        "PENANG", "PASIR GUDANG",
        # Indian Ports
        "NHAVA SHEVA", "MUNDRA", "CHENNAI", "KOLKATA", "KOLKATTA", "PIPAVAV",
        "KATTUPALLI", "VIZAG", "VISAKHAPATNAM", "HALDIA", "TUTICORIN", "COCHIN",
        # Middle East
        "JEBEL ALI", "JEDDAH", "KARACHI", "AQABA", "SOKHANA", "DAMMAM",
        # Others
        "CHITTAGONG", "YANGON", "JAKARTA", "SURABAYA", "BELAWAN", "MOMBASA",
        "DAR ES SALAAM", "DJIBOUTI", "ICT PANGAON", "DHAKA"
    }
    
    def __init__(self):
        pass
    
    def validate(self, extracted_data: Dict[str, Any]) -> Tuple[bool, Dict[str, Any], List[str]]:
        """
        Validate extracted data.
        
        Returns:
            Tuple of:
            - is_valid: bool - whether data passed all validations
            - validated_data: Dict - cleaned and validated data
            - errors: List[str] - list of validation errors/warnings
        """
        logger.info("✅ [STAGE 3: VALIDATION] Starting validation")
        
        errors = []
        warnings = []
        validated_data = extracted_data.copy()
        
        # Validate metadata
        self._validate_metadata(validated_data, errors, warnings)
        
        # Validate validity dates
        self._validate_dates(validated_data, errors, warnings)
        
        # Validate routes
        validated_routes = []
        for i, route in enumerate(validated_data.get("routes", [])):
            route_errors, route_warnings, validated_route = self._validate_route(route, i)
            errors.extend(route_errors)
            warnings.extend(route_warnings)
            if validated_route:
                validated_routes.append(validated_route)
        
        validated_data["routes"] = validated_routes
        
        # Log validation results
        self._log_validation_results(validated_data, errors, warnings)
        
        is_valid = len(errors) == 0
        all_issues = errors + [f"WARNING: {w}" for w in warnings]
        
        return is_valid, validated_data, all_issues
    
    def _validate_metadata(self, data: Dict, errors: List, warnings: List):
        """Validate metadata fields"""
        
        if not data.get("rate_sheet_type"):
            data["rate_sheet_type"] = "ocean_freight"
            warnings.append("rate_sheet_type was empty, defaulting to 'ocean_freight'")
    
    def _validate_dates(self, data: Dict, errors: List, warnings: List):
        """Validate validity dates"""
        
        valid_from = data.get("valid_from")
        valid_to = data.get("valid_to")
        
        # Try to parse dates
        if valid_from:
            try:
                from_date = self._parse_date(valid_from)
                data["valid_from"] = from_date.strftime("%Y-%m-%d") if from_date else None
            except:
                warnings.append(f"Could not parse valid_from date: {valid_from}")
                data["valid_from"] = None
        
        if valid_to:
            try:
                to_date = self._parse_date(valid_to)
                data["valid_to"] = to_date.strftime("%Y-%m-%d") if to_date else None
            except:
                warnings.append(f"Could not parse valid_to date: {valid_to}")
                data["valid_to"] = None
        
        # Check valid_from <= valid_to
        if data.get("valid_from") and data.get("valid_to"):
            if data["valid_from"] > data["valid_to"]:
                errors.append(f"valid_from ({data['valid_from']}) is after valid_to ({data['valid_to']})")
    
    def _parse_date(self, date_str: str) -> Optional[datetime]:
        """Parse various date formats"""
        if not date_str:
            return None
        
        # Try different formats
        formats = [
            "%Y-%m-%d",
            "%d-%m-%Y",
            "%d/%m/%Y",
            "%m/%d/%Y",
            "%Y/%m/%d"
        ]
        
        for fmt in formats:
            try:
                return datetime.strptime(date_str, fmt)
            except:
                continue
        
        return None
    
    def _validate_route(self, route: Dict, index: int) -> Tuple[List[str], List[str], Optional[Dict]]:
        """Validate a single route"""
        
        errors = []
        warnings = []
        
        # Validate origin port
        origin = route.get("origin_port", "").upper()
        if not origin:
            errors.append(f"Route {index + 1}: Missing origin_port")
        elif origin not in self.KNOWN_PORTS:
            warnings.append(f"Route {index + 1}: Unknown origin port '{origin}'")
        else:
            route["origin_port"] = origin
        
        # Validate destination port
        dest = route.get("destination_port", "").upper()
        if not dest:
            errors.append(f"Route {index + 1}: Missing destination_port")
        elif dest not in self.KNOWN_PORTS:
            # Try to match partial
            matched = self._fuzzy_match_port(dest)
            if matched:
                route["destination_port"] = matched
                warnings.append(f"Route {index + 1}: Normalized '{dest}' to '{matched}'")
            else:
                warnings.append(f"Route {index + 1}: Unknown destination port '{dest}'")
        else:
            route["destination_port"] = dest
        
        # Validate pricing tiers
        validated_tiers = []
        for tier in route.get("pricing_tiers", []):
            tier_valid, validated_tier, tier_warnings = self._validate_pricing_tier(tier, index)
            warnings.extend(tier_warnings)
            if tier_valid:
                validated_tiers.append(validated_tier)
        
        if not validated_tiers:
            errors.append(f"Route {index + 1}: No valid pricing tiers")
            return errors, warnings, None
        
        route["pricing_tiers"] = validated_tiers
        
        # Validate transit time
        if route.get("transit_time_days"):
            try:
                route["transit_time_days"] = int(route["transit_time_days"])
            except:
                warnings.append(f"Route {index + 1}: Invalid transit_time_days")
                route["transit_time_days"] = None
        
        # Validate free detention
        if route.get("free_detention_days"):
            try:
                route["free_detention_days"] = int(route["free_detention_days"])
            except:
                route["free_detention_days"] = None
        
        return errors, warnings, route
    
    def _validate_pricing_tier(self, tier: Dict, route_index: int) -> Tuple[bool, Dict, List[str]]:
        """Validate a single pricing tier"""
        
        warnings = []
        
        # Validate base_rate is numeric
        base_rate = tier.get("base_rate")
        if base_rate is None:
            return False, {}, [f"Route {route_index + 1}: Pricing tier has no base_rate"]
        
        try:
            # Handle string rates like "525-550" (use lower value)
            if isinstance(base_rate, str):
                if "-" in base_rate:
                    base_rate = float(base_rate.split("-")[0].strip())
                else:
                    base_rate = float(base_rate.replace(",", ""))
            else:
                base_rate = float(base_rate)
            
            if base_rate <= 0:
                return False, {}, [f"Route {route_index + 1}: base_rate must be positive"]
            
            tier["base_rate"] = base_rate
        except:
            return False, {}, [f"Route {route_index + 1}: Invalid base_rate '{tier.get('base_rate')}'"]
        
        # Validate currency
        currency = tier.get("currency", "USD").upper()
        if currency not in self.KNOWN_CURRENCIES:
            warnings.append(f"Route {route_index + 1}: Unknown currency '{currency}', defaulting to USD")
            currency = "USD"
        tier["currency"] = currency
        
        # Validate container type
        container_type = tier.get("container_type", "")
        if container_type not in ["20'", "40'", "40'HC", "45'"]:
            # Try to normalize
            if "20" in str(container_type):
                tier["container_type"] = "20'"
                tier["container_size"] = 20
            elif "40" in str(container_type) and "HC" in str(container_type).upper():
                tier["container_type"] = "40'HC"
                tier["container_size"] = 40
            elif "40" in str(container_type):
                tier["container_type"] = "40'"
                tier["container_size"] = 40
            elif "45" in str(container_type):
                tier["container_type"] = "45'"
                tier["container_size"] = 45
            else:
                warnings.append(f"Route {route_index + 1}: Unknown container type '{container_type}'")
        
        return True, tier, warnings
    
    def _fuzzy_match_port(self, port: str) -> Optional[str]:
        """Try to fuzzy match a port name"""
        port_upper = port.upper()
        
        # Common variations
        variations = {
            "NAVA SHEVA": "NHAVA SHEVA",
            "NHAVASHEVA": "NHAVA SHEVA",
            "JNPT": "NHAVA SHEVA",
            "KOLKATTA": "KOLKATA",
            "CALCUTTA": "KOLKATA",
            "VISHAKAPATNAM": "VISAKHAPATNAM",
            "VIZAG": "VISAKHAPATNAM",
            "LAEMCHABANG": "LAEM CHABANG",
            "LCB": "LAEM CHABANG",
            "PKG": "PORT KLANG",
            "PORTKLANG": "PORT KLANG",
            "JEA": "JEBEL ALI",
            "JEBELALI": "JEBEL ALI",
        }
        
        if port_upper in variations:
            return variations[port_upper]
        
        # Check if port is a substring of known port
        for known_port in self.KNOWN_PORTS:
            if port_upper in known_port or known_port in port_upper:
                return known_port
        
        return None
    
    def _log_validation_results(self, data: Dict, errors: List, warnings: List):
        """Log validation results"""
        
        print("\n" + "=" * 80)
        print("✅ VALIDATION RESULTS")
        print("=" * 80)
        
        routes = data.get("routes", [])
        total_tiers = sum(len(r.get("pricing_tiers", [])) for r in routes)
        
        print(f"\n📊 SUMMARY:")
        print(f"   - Valid Routes: {len(routes)}")
        print(f"   - Total Pricing Tiers: {total_tiers}")
        print(f"   - Errors: {len(errors)}")
        print(f"   - Warnings: {len(warnings)}")
        
        if errors:
            print(f"\n❌ ERRORS ({len(errors)}):")
            for e in errors[:10]:
                print(f"   • {e}")
            if len(errors) > 10:
                print(f"   ... and {len(errors) - 10} more errors")
        
        if warnings:
            print(f"\n⚠️ WARNINGS ({len(warnings)}):")
            for w in warnings[:10]:
                print(f"   • {w}")
            if len(warnings) > 10:
                print(f"   ... and {len(warnings) - 10} more warnings")
        
        print("=" * 80 + "\n")
        
        if errors:
            logger.warning(f"⚠️ [STAGE 3] Validation completed with {len(errors)} errors")
        else:
            logger.info(f"✅ [STAGE 3] Validation passed: {len(routes)} routes, {total_tiers} pricing tiers")


# =============================================================================
# MAIN PIPELINE
# =============================================================================

class RateSheetPipeline:
    """
    Main Pipeline: Orchestrates all stages
    
    1. Pandas Normalization (NO AI)
    2. AI Semantic Extraction
    3. Validation + Guardrails
    4. Storage (SQL + Graph + ChromaDB)
    """
    
    def __init__(self, ai_service_url: str):
        self.normalizer = PandasNormalizer()
        self.extractor = AISemanticExtractor(ai_service_url)
        self.validator = DataValidator()
    
    async def process(self, file_path: str) -> Tuple[Dict[str, Any], str, bool, List[str]]:
        """
        Process a rate sheet through the full pipeline.
        
        Args:
            file_path: Path to the Excel file
        
        Returns:
            Tuple of:
            - structured_data: Validated structured data for SQL/Graph
            - full_text: Full text for ChromaDB embeddings
            - is_valid: Whether data passed validation
            - issues: List of errors/warnings
        """
        print("\n" + "=" * 80)
        print("🚀 RATE SHEET PROCESSING PIPELINE")
        print("=" * 80)
        print(f"📁 File: {file_path}")
        print("=" * 80 + "\n")
        
        # Stage 1: Pandas Normalization
        print("📊 STAGE 1: PANDAS NORMALIZATION (No AI)")
        print("-" * 40)
        normalized_data = self.normalizer.normalize(file_path)
        
        # Create full text for ChromaDB
        full_text = self._create_full_text(normalized_data)
        
        # Stage 2: AI Semantic Extraction
        print("\n🤖 STAGE 2: AI SEMANTIC EXTRACTION")
        print("-" * 40)
        extracted_data = await self.extractor.extract(normalized_data)
        
        # Stage 3: Validation
        print("\n✅ STAGE 3: VALIDATION + GUARDRAILS")
        print("-" * 40)
        is_valid, validated_data, issues = self.validator.validate(extracted_data)
        
        # Add file info
        validated_data["file_name"] = normalized_data.get("file_name", "")
        validated_data["extraction_method"] = "pandas_ai_pipeline"
        
        # Store full text for ChromaDB
        validated_data["_full_text_for_chromadb"] = full_text
        
        print("\n" + "=" * 80)
        print("🏁 PIPELINE COMPLETE")
        print("=" * 80)
        print(f"   - Validation: {'PASSED ✅' if is_valid else 'FAILED ❌'}")
        print(f"   - Routes: {len(validated_data.get('routes', []))}")
        print(f"   - Issues: {len(issues)}")
        print("=" * 80 + "\n")
        
        return validated_data, full_text, is_valid, issues
    
    def _create_full_text(self, normalized_data: Dict[str, Any]) -> str:
        """Create full text representation for ChromaDB"""
        
        parts = []
        parts.append(f"File: {normalized_data.get('file_name', 'Unknown')}")
        parts.append(f"Carriers: {', '.join(normalized_data['detected_metadata'].get('potential_carriers', []))}")
        parts.append(f"Origins: {', '.join(normalized_data['detected_metadata'].get('potential_origins', []))}")
        parts.append(f"Destinations: {', '.join(normalized_data['detected_metadata'].get('potential_destinations', []))}")
        parts.append("")
        
        for sheet in normalized_data.get("sheets", []):
            parts.append(f"=== SHEET: {sheet['name']} ===")
            for row in sheet.get("grid", []):
                row_text = " | ".join([str(cell) for cell in row if str(cell).strip()])
                if row_text:
                    parts.append(row_text)
            parts.append("")
        
        return "\n".join(parts)
