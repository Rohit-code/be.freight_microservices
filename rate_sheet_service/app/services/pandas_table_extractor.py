"""
Pandas-based Table Extractor for Rate Sheets

FLOW:
1. Pandas reads Excel → Creates CLEAN TEXT representation of ALL data
2. Clean text sent to AI → AI extracts ports, costs, routes intelligently
3. Structured data → PostgreSQL (for exact queries)
4. ENTIRE sheet → ChromaDB (for semantic search)

This approach:
- Pandas handles the messy Excel reading (merged cells, different formats)
- AI handles the intelligent interpretation (what is a port? what is a rate?)
- No hardcoded format assumptions
"""

import pandas as pd
import numpy as np
import re
import logging
from typing import Dict, Any, List, Optional, Tuple
from pathlib import Path

logger = logging.getLogger(__name__)


class PandasTableExtractor:
    """
    Extract rate sheet data using pandas for CLEAN reading, AI for SMART interpretation.
    
    The key insight:
    - Pandas is good at reading messy Excel files
    - AI is good at understanding what the data means
    - Combine both for accurate extraction
    """
    
    def __init__(self):
        pass
    
    async def extract_from_file(self, file_path: str) -> Tuple[str, str, Dict[str, Any]]:
        """
        Extract rate sheet data using pandas.
        
        Returns:
            Tuple of:
            - clean_table_text: Clean text representation for AI
            - full_sheet_text: ENTIRE sheet content for ChromaDB embeddings
            - metadata: Basic detected metadata
        """
        logger.info(f"🐼 [PANDAS] Starting extraction for: {file_path}")
        
        try:
            # Read all sheets from Excel
            if file_path.endswith('.xlsx'):
                excel_file = pd.ExcelFile(file_path, engine='openpyxl')
            elif file_path.endswith('.xls'):
                excel_file = pd.ExcelFile(file_path, engine='xlrd')
            elif file_path.endswith('.csv'):
                # Handle CSV files
                df = pd.read_csv(file_path, header=None)
                clean_text = self._dataframe_to_clean_text(df, "Sheet1")
                full_text = df.to_string(index=False, na_rep='')
                metadata = self._detect_basic_metadata(clean_text)
                return clean_text, full_text, metadata
            else:
                raise ValueError(f"Unsupported file type: {file_path}")
            
            all_clean_texts = []
            all_full_texts = []
            combined_metadata = {
                "file_name": Path(file_path).name,
                "sheets_count": len(excel_file.sheet_names),
                "detected_carriers": set(),
                "detected_origins": set(),
                "detected_destinations": set(),
                "detected_validity": {}
            }
            
            for sheet_name in excel_file.sheet_names:
                logger.info(f"🐼 [PANDAS] Processing sheet: {sheet_name}")
                
                # Read sheet without headers to get raw data
                df = pd.read_excel(excel_file, sheet_name=sheet_name, header=None)
                
                if df.empty or df.shape[0] < 2:
                    logger.info(f"   Sheet {sheet_name} is empty or too small, skipping")
                    continue
                
                # Convert to clean text representation
                clean_text = self._dataframe_to_clean_text(df, sheet_name)
                full_text = self._dataframe_to_full_text(df, sheet_name)
                
                if clean_text and len(clean_text) > 50:
                    all_clean_texts.append(f"\n{'='*60}\nSHEET: {sheet_name}\n{'='*60}\n{clean_text}")
                    all_full_texts.append(f"\n=== SHEET: {sheet_name} ===\n{full_text}")
                    
                    # Detect basic metadata from this sheet
                    sheet_metadata = self._detect_basic_metadata(clean_text)
                    if sheet_metadata.get("carriers"):
                        combined_metadata["detected_carriers"].update(sheet_metadata["carriers"])
                    if sheet_metadata.get("origins"):
                        combined_metadata["detected_origins"].update(sheet_metadata["origins"])
                    if sheet_metadata.get("destinations"):
                        combined_metadata["detected_destinations"].update(sheet_metadata["destinations"])
                    if sheet_metadata.get("validity") and not combined_metadata["detected_validity"]:
                        combined_metadata["detected_validity"] = sheet_metadata["validity"]
            
            # Convert sets to lists for JSON serialization
            combined_metadata["detected_carriers"] = list(combined_metadata["detected_carriers"])
            combined_metadata["detected_origins"] = list(combined_metadata["detected_origins"])
            combined_metadata["detected_destinations"] = list(combined_metadata["detected_destinations"])
            
            clean_table_text = "\n".join(all_clean_texts) if all_clean_texts else "No data found"
            full_sheet_text = "\n".join(all_full_texts) if all_full_texts else "No data found"
            
            logger.info(f"🐼 [PANDAS] Extraction complete: {len(all_clean_texts)} sheets processed")
            logger.info(f"🐼 [PANDAS] Detected: carriers={combined_metadata['detected_carriers']}, origins={combined_metadata['detected_origins']}")
            
            return clean_table_text, full_sheet_text, combined_metadata
            
        except Exception as e:
            logger.error(f"🐼 [PANDAS] Error extracting from file: {e}", exc_info=True)
            return f"Error reading file: {e}", "", {"error": str(e)}
    
    def _dataframe_to_clean_text(self, df: pd.DataFrame, sheet_name: str) -> str:
        """
        Convert a dataframe to a clean, readable text format for AI.
        
        This creates a table-like representation that AI can easily understand.
        """
        # Clean the dataframe
        df = df.copy()
        
        # Replace NaN with empty string
        df = df.fillna('')
        
        # Convert all values to strings
        df = df.astype(str)
        
        # Remove rows that are completely empty
        df = df[~(df == '').all(axis=1)]
        
        # Remove columns that are completely empty
        df = df.loc[:, ~(df == '').all(axis=0)]
        
        if df.empty:
            return ""
        
        # Try to detect header row (row with most unique non-empty values that look like headers)
        header_row_idx = self._detect_header_row(df)
        
        parts = []
        
        # Add raw data in a structured way
        parts.append(f"Total Rows: {len(df)}")
        parts.append(f"Total Columns: {len(df.columns)}")
        parts.append("")
        
        # Show column numbers for reference
        parts.append("COLUMN POSITIONS:")
        for i, col in enumerate(df.columns):
            # Get sample values from this column
            sample_values = df.iloc[:3, i].tolist()
            sample_str = " | ".join([str(v)[:30] for v in sample_values if str(v).strip()])
            parts.append(f"  Column {i}: {sample_str}")
        parts.append("")
        
        # Create a clean table representation
        parts.append("DATA TABLE:")
        parts.append("-" * 80)
        
        # Show all rows as a formatted table
        for row_idx in range(len(df)):
            row = df.iloc[row_idx]
            row_values = [str(v).strip() for v in row.values]
            
            # Skip completely empty rows
            if not any(v for v in row_values):
                continue
            
            # Format row
            row_str = " | ".join(row_values)
            
            # Mark potential header rows
            if row_idx == header_row_idx:
                parts.append(f"[HEADER ROW {row_idx}] {row_str}")
                parts.append("-" * 80)
            else:
                parts.append(f"[Row {row_idx}] {row_str}")
        
        return "\n".join(parts)
    
    def _dataframe_to_full_text(self, df: pd.DataFrame, sheet_name: str) -> str:
        """
        Convert dataframe to full text for ChromaDB embeddings.
        Includes EVERYTHING from the sheet.
        """
        parts = []
        
        # Clean the dataframe
        df = df.fillna('')
        df = df.astype(str)
        
        # Add sheet info
        parts.append(f"Sheet Name: {sheet_name}")
        parts.append(f"Dimensions: {df.shape[0]} rows x {df.shape[1]} columns")
        parts.append("")
        
        # Add all data
        for row_idx in range(len(df)):
            row = df.iloc[row_idx]
            row_values = [str(v).strip() for v in row.values if str(v).strip()]
            if row_values:
                parts.append(" | ".join(row_values))
        
        return "\n".join(parts)
    
    def _detect_header_row(self, df: pd.DataFrame) -> int:
        """
        Detect which row is likely the header row.
        
        Looks for rows containing keywords like:
        - POL, POD, Origin, Destination
        - 20', 40', Rate, Price, Freight
        - Transit, Detention, Remarks
        """
        header_keywords = [
            'pol', 'pod', 'origin', 'destination', 'port', 'discharge', 'loading',
            '20', '40', 'rate', 'price', 'freight', 'usd', 'cost',
            'transit', 'detention', 'remarks', 'routing', 'service',
            'vgm', 'container', 'teu'
        ]
        
        best_row = 0
        best_score = 0
        
        # Check first 15 rows
        for row_idx in range(min(15, len(df))):
            row = df.iloc[row_idx]
            row_text = " ".join([str(v).lower() for v in row.values])
            
            # Count keyword matches
            score = sum(1 for kw in header_keywords if kw in row_text)
            
            if score > best_score:
                best_score = score
                best_row = row_idx
        
        return best_row
    
    def _detect_basic_metadata(self, text: str) -> Dict[str, Any]:
        """
        Detect basic metadata from the text using pattern matching.
        
        This is just for hints - AI will do the real extraction.
        """
        metadata = {
            "carriers": set(),
            "origins": set(),
            "destinations": set(),
            "validity": {}
        }
        
        text_upper = text.upper()
        
        # Detect carriers
        carriers = ['MAXICON', 'MSC', 'MAERSK', 'CMA CGM', 'HAPAG', 'ONE', 'EVERGREEN', 'COSCO', 'PIL', 'YANGMING']
        for carrier in carriers:
            if carrier in text_upper:
                metadata["carriers"].add(carrier)
        
        # Detect known ports
        known_ports = {
            # Origins (typically South East Asia)
            "LAEM CHABANG": "origin",
            "PORT KLANG": "origin", 
            "BANGKOK": "origin",
            "SINGAPORE": "origin",
            "TANJUNG PELEPAS": "origin",
            "PENANG": "origin",
            # Indian ports (typically destinations for these sheets)
            "NHAVA SHEVA": "destination",
            "MUNDRA": "destination",
            "CHENNAI": "destination",
            "KOLKATA": "destination",
            "KOLKATTA": "destination",
            "PIPAVAV": "destination",
            "KATTUPALLI": "destination",
            "VIZAG": "destination",
            "VISAKHAPATNAM": "destination",
            "HALDIA": "destination",
            "TUTICORIN": "destination",
            # Middle East
            "JEBEL ALI": "destination",
            "JEDDAH": "destination",
            "KARACHI": "destination",
            "AQABA": "destination",
            # Others
            "CHITTAGONG": "destination",
            "YANGON": "destination",
            "JAKARTA": "destination",
        }
        
        for port, port_type in known_ports.items():
            if port in text_upper:
                if port_type == "origin":
                    metadata["origins"].add(port)
                else:
                    metadata["destinations"].add(port)
        
        # Detect validity dates (e.g., "1-1-2026 to 31-1-2026")
        date_pattern = r'(\d{1,2}[-/]\d{1,2}[-/]\d{4})\s*(?:to|TO|-)\s*(\d{1,2}[-/]\d{1,2}[-/]\d{4})'
        date_match = re.search(date_pattern, text)
        if date_match:
            metadata["validity"] = {
                "valid_from": date_match.group(1),
                "valid_to": date_match.group(2)
            }
        
        return metadata


def format_for_ai_extraction(clean_text: str, full_text: str, metadata: Dict[str, Any], file_name: str) -> str:
    """
    Format the pandas-extracted data for AI to perform intelligent extraction.
    
    The AI will:
    1. Understand the structure of the rate sheet
    2. Identify origin ports, destination ports
    3. Extract pricing for each container type
    4. Identify routing, transit times, remarks
    """
    
    prompt = f"""You are an expert freight forwarding rate sheet data extractor. Your task is to ACCURATELY extract ALL pricing data from this rate sheet.

## FILE INFORMATION
- File Name: {file_name}
- Detected Carriers: {metadata.get('detected_carriers', [])}
- Detected Origin Ports: {metadata.get('detected_origins', [])}
- Detected Destination Ports: {metadata.get('detected_destinations', [])}
- Detected Validity: {metadata.get('detected_validity', {})}

## RAW DATA (Read by Pandas from Excel)

{clean_text}

---

## EXTRACTION INSTRUCTIONS

**STEP 1: UNDERSTAND THE STRUCTURE**
- Look at the header row to understand column meanings
- Identify which column contains: Origin, Destination, 20' rate, 40' rate, Transit time, Remarks
- Rate sheets often have multiple sections (Indian ports, Middle East, etc.)

**STEP 2: IDENTIFY PORTS**
- ORIGIN PORT: The port where cargo STARTS (e.g., "LAEM CHABANG", "PORT KLANG")
  - Often in header/title or first column (POL = Port of Loading)
- DESTINATION PORT: The port where cargo ENDS (e.g., "NHAVA SHEVA", "CHENNAI")
  - Often listed in rows (POD = Port of Discharge)

**STEP 3: EXTRACT PRICING**
- 20' Container Rate: Price for 20-foot container (in USD)
- 40' Container Rate: Price for 40-foot container (in USD)
- If there are VGM tiers (e.g., "VGM up to 18MT", "VGM up to 26MT"), extract EACH tier separately
- If rate shows range (e.g., "$525-550"), use the LOWER value

**STEP 4: EXTRACT ADDITIONAL INFO**
- Transit Time: How many days the journey takes
- Routing: Direct or via transshipment port
- Free Detention: Free days at destination
- Remarks: Any special notes

**CRITICAL RULES:**
1. EVERY row with pricing data should become a route
2. 20' and 40' containers have DIFFERENT rates - extract BOTH
3. If 40' column is empty, set it as null (don't use 20' rate)
4. Use FULL port names (NHAVA SHEVA, not NHV)
5. Skip section headers (e.g., "INDIAN SECTORS", "MIDDLE EAST")

## REQUIRED OUTPUT FORMAT

Return ONLY valid JSON (no markdown, no explanation):

```json
{{
    "rate_sheet_type": "ocean_freight",
    "carrier_name": "carrier name or null",
    "title": "extracted title",
    "validity": {{
        "valid_from": "YYYY-MM-DD or null",
        "valid_to": "YYYY-MM-DD or null"
    }},
    "routes": [
        {{
            "origin_port": "FULL PORT NAME (e.g., LAEM CHABANG)",
            "origin_country": "country",
            "destination_port": "FULL PORT NAME (e.g., NHAVA SHEVA)",
            "destination_country": "country",
            "routing": "Direct or via XXX",
            "transit_time_days": number or null,
            "service_type": "FCL",
            "free_detention_days": number or null,
            "remarks": "any remarks",
            "pricing_tiers": [
                {{
                    "container_type": "20'",
                    "container_size": 20,
                    "base_rate": number,
                    "currency": "USD",
                    "vgm_max_weight_mt": 18 or null,
                    "remarks": "e.g., VGM up to 18MT"
                }},
                {{
                    "container_type": "40'",
                    "container_size": 40,
                    "base_rate": number,
                    "currency": "USD",
                    "vgm_max_weight_mt": 26 or null,
                    "remarks": "e.g., VGM up to 26MT"
                }}
            ]
        }}
    ],
    "detected_format": "description of the format",
    "confidence_score": 90,
    "extraction_notes": "any issues or notes"
}}
```

**REMEMBER:**
- Extract EVERY route from the data
- 20' and 40' are SEPARATE prices
- Use FULL port names
- Return ONLY valid JSON
"""
    
    return prompt
