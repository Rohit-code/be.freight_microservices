"""
Pandas-based Rate Sheet Extractor

Uses pandas for DETERMINISTIC extraction of structured data from rate sheets.
AI is only used for semantic content (notes, clauses) - NOT for pricing.

BENEFITS:
- Deterministic: Same file → Same output every time
- Fast: No API calls, processes locally
- Accurate: Direct cell reading, no AI hallucinations
- Cost-effective: No token costs for structured data

FLOW:
1. Pandas extracts structured data (ports, rates, container types)
2. AI handles semantic content only (notes, clauses, remarks)
3. Both stored in PostgreSQL (structured) and ChromaDB (semantic)
"""

import pandas as pd
import re
import logging
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime
import xlrd
import openpyxl

logger = logging.getLogger(__name__)


class PandasRateSheetExtractor:
    """
    Extract rate sheet data using pandas for reliability.
    
    Handles multiple formats:
    - Format A: POL/POD style (MAXICON)
    - Format B: Origin header style (Thailand rate sheets)
    - Format C: Projection style with targets
    """
    
    # Known origin ports (not destinations)
    KNOWN_ORIGINS = {
        "LAEM CHABANG", "PORT KLANG", "BANGKOK", "SINGAPORE", 
        "TANJUNG PELEPAS", "PASIR GUDANG", "PENANG"
    }
    
    # Known Indian ports (typically destinations in these sheets)
    INDIAN_PORTS = {
        "NHAVA SHEVA", "MUNDRA", "CHENNAI", "KOLKATA", "KOLKATTA",
        "PIPAVAV", "KATTUPALLI", "VIZAG", "VISAKHAPATNAM", "HALDIA",
        "TUTICORIN", "COCHIN", "BANGALORE", "ICD BANGALORE"
    }
    
    # Container type patterns
    CONTAINER_PATTERNS = {
        r"20['\"]?\s*(?:ft|feet)?": "20'",
        r"40['\"]?\s*(?:ft|feet)?(?!\s*hc)": "40'",
        r"40['\"]?\s*(?:hc|high\s*cube)": "40'HC",
        r"VGM\s*(?:UPTO|UP\s*TO)?\s*(\d+)\s*MT?\s*(\d+)['\"]?": "VGM",
    }
    
    def __init__(self):
        self.detected_format = None
        self.origin_port = None
        self.validity = {}
    
    async def extract_from_file(self, file_path: str) -> Dict[str, Any]:
        """
        Main extraction method - uses pandas for structured data.
        
        Returns:
            {
                "rate_sheet_type": "ocean_freight",
                "carrier_name": str or None,
                "origin_port": str,  # CRITICAL: The actual origin
                "validity": {"valid_from": date, "valid_to": date},
                "routes": [...],  # List of routes with pricing
                "semantic_content": str,  # Notes, clauses, remarks
                "extraction_method": "pandas",
                "confidence": float
            }
        """
        try:
            logger.info(f"🐼 Pandas extraction starting for: {file_path}")
            
            # Detect file type and load
            if file_path.endswith('.xlsx'):
                df_dict = self._load_xlsx(file_path)
            elif file_path.endswith('.xls'):
                df_dict = self._load_xls(file_path)
            else:
                raise ValueError(f"Unsupported file type: {file_path}")
            
            # Detect format and extract
            all_routes = []
            all_semantic = []
            carrier_name = None
            
            for sheet_name, df in df_dict.items():
                if df.empty:
                    continue
                
                # Detect format
                format_type = self._detect_format(df, sheet_name)
                logger.info(f"  Sheet '{sheet_name}': Detected format {format_type}")
                
                # Extract based on format
                if format_type == "POL_POD":
                    routes, semantic, carrier = self._extract_pol_pod_format(df)
                elif format_type == "ORIGIN_HEADER":
                    routes, semantic, carrier = self._extract_origin_header_format(df)
                elif format_type == "PROJECTION":
                    routes, semantic, carrier = self._extract_projection_format(df)
                else:
                    logger.warning(f"  Unknown format in sheet '{sheet_name}'")
                    continue
                
                all_routes.extend(routes)
                all_semantic.append(semantic)
                if carrier and not carrier_name:
                    carrier_name = carrier
            
            # Build result
            result = {
                "rate_sheet_type": "ocean_freight",
                "carrier_name": carrier_name,
                "validity": self.validity,
                "routes": all_routes,
                "semantic_content": "\n".join(all_semantic),
                "extraction_method": "pandas",
                "confidence": 0.95 if all_routes else 0.5,
                "detected_format": self.detected_format,
                "total_routes": len(all_routes)
            }
            
            logger.info(f"✅ Pandas extraction complete: {len(all_routes)} routes extracted")
            return result
            
        except Exception as e:
            logger.error(f"❌ Pandas extraction failed: {e}", exc_info=True)
            raise
    
    def _load_xlsx(self, file_path: str) -> Dict[str, pd.DataFrame]:
        """Load .xlsx file into DataFrames"""
        excel_file = pd.ExcelFile(file_path)
        result = {}
        for sheet_name in excel_file.sheet_names:
            df = pd.read_excel(file_path, sheet_name=sheet_name, header=None)
            result[sheet_name] = df
        return result
    
    def _load_xls(self, file_path: str) -> Dict[str, pd.DataFrame]:
        """Load .xls file into DataFrames"""
        wb = xlrd.open_workbook(file_path)
        result = {}
        for sheet_idx in range(wb.nsheets):
            sheet = wb.sheet_by_index(sheet_idx)
            data = []
            for row_idx in range(sheet.nrows):
                data.append(sheet.row_values(row_idx))
            result[sheet.name] = pd.DataFrame(data)
        return result
    
    def _detect_format(self, df: pd.DataFrame, sheet_name: str) -> str:
        """
        Detect the rate sheet format based on structure.
        
        Returns: "POL_POD", "ORIGIN_HEADER", "PROJECTION", or "UNKNOWN"
        """
        # Convert first 10 rows to strings for pattern matching
        header_text = ""
        for idx, row in df.head(10).iterrows():
            row_str = " ".join([str(cell).upper() for cell in row.values if pd.notna(cell)])
            header_text += row_str + " "
        
        # Check for POL/POD format (MAXICON style)
        if "POL" in header_text and "POD" in header_text:
            self.detected_format = "POL_POD"
            return "POL_POD"
        
        # Check for Origin Header format (Thailand style)
        for origin in self.KNOWN_ORIGINS:
            if origin in header_text:
                self.detected_format = "ORIGIN_HEADER"
                self.origin_port = origin
                return "ORIGIN_HEADER"
        
        # Check for Projection format
        if "PROJECTION" in header_text or "TARGET" in header_text or "FREIGHT RATE" in header_text:
            self.detected_format = "PROJECTION"
            return "PROJECTION"
        
        return "UNKNOWN"
    
    def _extract_pol_pod_format(self, df: pd.DataFrame) -> Tuple[List[Dict], str, Optional[str]]:
        """
        Extract from POL/POD format (e.g., MAXICON).
        
        Structure:
        Row 1: Carrier name (MAXICON CONTAINER LINE)
        Row 2: POL | POD | ROUTING | 20' | 40' | TRANSIT TIME | FREE DETENTION | REMARKS
        Row 3: Validity date
        Row 4+: Data rows (PORT KLANG | NHAVA SHEVA | Direct | 525 | 800 | 7 days | 14 days | ...)
        """
        routes = []
        semantic_parts = []
        carrier_name = None
        
        # Find header row with POL/POD
        header_row_idx = None
        validity_str = None
        
        for idx, row in df.iterrows():
            row_str = " ".join([str(cell).upper() for cell in row.values if pd.notna(cell)])
            
            # Extract carrier name (usually first non-empty row)
            if carrier_name is None and any(pd.notna(cell) and str(cell).strip() for cell in row.values):
                first_cell = str(row.iloc[0]).strip() if pd.notna(row.iloc[0]) else ""
                if first_cell and "POL" not in first_cell.upper() and "SECTOR" not in first_cell.upper():
                    carrier_name = first_cell
            
            # Find header row
            if "POL" in row_str and "POD" in row_str:
                header_row_idx = idx
                continue
            
            # Extract validity date
            validity_match = re.search(r'(\d{1,2}-\d{1,2}-\d{4})\s*to\s*(\d{1,2}-\d{1,2}-\d{4})', row_str, re.IGNORECASE)
            if validity_match:
                try:
                    self.validity = {
                        "valid_from": datetime.strptime(validity_match.group(1), "%d-%m-%Y").strftime("%Y-%m-%d"),
                        "valid_to": datetime.strptime(validity_match.group(2), "%d-%m-%Y").strftime("%Y-%m-%d")
                    }
                except:
                    pass
        
        if header_row_idx is None:
            logger.warning("Could not find POL/POD header row")
            return routes, "", carrier_name
        
        # Process data rows after header
        for idx, row in df.iloc[header_row_idx + 1:].iterrows():
            # Skip empty rows and section headers
            first_cell = str(row.iloc[0]).strip() if pd.notna(row.iloc[0]) else ""
            if not first_cell or "SECTOR" in first_cell.upper() or "ISC" in first_cell.upper():
                continue
            
            # Check if this is a data row (has a known port in first column)
            origin_port = first_cell.upper()
            if origin_port not in self.KNOWN_ORIGINS:
                # Check if it's a known destination in wrong column
                continue
            
            # Extract route data
            try:
                destination = str(row.iloc[1]).strip() if pd.notna(row.iloc[1]) else ""
                routing = str(row.iloc[2]).strip() if len(row) > 2 and pd.notna(row.iloc[2]) else "Direct"
                rate_20 = self._parse_rate(row.iloc[3]) if len(row) > 3 else None
                rate_40 = self._parse_rate(row.iloc[4]) if len(row) > 4 else None
                transit_time = str(row.iloc[5]).strip() if len(row) > 5 and pd.notna(row.iloc[5]) else None
                free_detention = str(row.iloc[6]).strip() if len(row) > 6 and pd.notna(row.iloc[6]) else None
                remarks = str(row.iloc[7]).strip() if len(row) > 7 and pd.notna(row.iloc[7]) else ""
                
                # Skip if no valid destination
                if not destination or destination.upper() in ["NAN", "NONE", ""]:
                    continue
                
                # Build pricing tiers
                pricing_tiers = []
                if rate_20:
                    pricing_tiers.append({
                        "container_type": "20'",
                        "container_size": 20,
                        "base_rate": rate_20,
                        "currency": "USD"
                    })
                if rate_40:
                    pricing_tiers.append({
                        "container_type": "40'",
                        "container_size": 40,
                        "base_rate": rate_40,
                        "currency": "USD"
                    })
                
                if pricing_tiers:
                    route = {
                        "origin_port": origin_port,
                        "destination_port": destination.upper(),
                        "routing": routing,
                        "service_type": "FCL",
                        "transit_time_text": transit_time,
                        "transit_time_days": self._parse_transit_days(transit_time),
                        "free_detention_text": free_detention,
                        "free_detention_days": self._parse_detention_days(free_detention),
                        "remarks": remarks,
                        "pricing_tiers": pricing_tiers
                    }
                    routes.append(route)
                    
                    # Add to semantic content
                    if remarks:
                        semantic_parts.append(f"{origin_port} to {destination}: {remarks}")
                        
            except Exception as e:
                logger.warning(f"Error processing row {idx}: {e}")
                continue
        
        return routes, "\n".join(semantic_parts), carrier_name
    
    def _extract_origin_header_format(self, df: pd.DataFrame) -> Tuple[List[Dict], str, Optional[str]]:
        """
        Extract from Origin Header format (e.g., Thailand rate sheets).
        
        Structure:
        Row 2: LAEM CHABANG | LOCATION TARGET | ... | FREIGHT RATE | ...
        Row 3: PORT OF DISCHARGE | 20' | 40' | TOTAL TEUS | VGM UPTO 18MT 20' | VGM UPTO 26MT 20' | VGM UPTO 26MT 40'
        Row 4+: NHAVA SHEVA | 40 | ... | 650 | 700 | 1100 | via PKG/SIN
        """
        routes = []
        semantic_parts = []
        carrier_name = None
        
        # Find origin port in header
        origin_port = self.origin_port  # Already detected in _detect_format
        
        # Find the header row with container types
        header_row_idx = None
        column_mapping = {}
        
        for idx, row in df.iterrows():
            row_str = " ".join([str(cell).upper() for cell in row.values if pd.notna(cell)])
            
            # Look for row with "PORT OF DISCHARGE" or "20'" column headers
            if "PORT OF DISCHARGE" in row_str or ("20'" in row_str and "40'" in row_str):
                header_row_idx = idx
                
                # Map columns
                for col_idx, cell in enumerate(row.values):
                    cell_str = str(cell).upper() if pd.notna(cell) else ""
                    if "DISCHARGE" in cell_str or "DESTINATION" in cell_str:
                        column_mapping["destination"] = col_idx
                    elif "VGM" in cell_str and "18" in cell_str and "20" in cell_str:
                        column_mapping["vgm_18_20"] = col_idx
                    elif "VGM" in cell_str and "26" in cell_str and "20" in cell_str:
                        column_mapping["vgm_26_20"] = col_idx
                    elif "VGM" in cell_str and "26" in cell_str and "40" in cell_str:
                        column_mapping["vgm_26_40"] = col_idx
                    elif "20'" in cell_str and "VGM" not in cell_str:
                        column_mapping["rate_20"] = col_idx
                    elif "40'" in cell_str and "VGM" not in cell_str:
                        column_mapping["rate_40"] = col_idx
                    elif "REMARK" in cell_str:
                        column_mapping["remarks"] = col_idx
                break
        
        if header_row_idx is None:
            logger.warning("Could not find header row with container types")
            return routes, "", carrier_name
        
        # Use first column as destination if not mapped
        if "destination" not in column_mapping:
            column_mapping["destination"] = 1  # Usually column B
        
        # Process data rows
        for idx, row in df.iloc[header_row_idx + 1:].iterrows():
            try:
                dest_col = column_mapping.get("destination", 1)
                destination = str(row.iloc[dest_col]).strip() if pd.notna(row.iloc[dest_col]) else ""
                
                # Skip empty or invalid destinations
                if not destination or destination.upper() in ["NAN", "NONE", "", "TOTAL"]:
                    continue
                
                # Skip section headers
                if any(keyword in destination.upper() for keyword in ["SECTOR", "ISC", "ICD's", "TOTAL"]):
                    continue
                
                # Extract rates based on column mapping
                pricing_tiers = []
                
                # VGM-based pricing (preferred for Thailand sheets)
                if "vgm_18_20" in column_mapping:
                    rate = self._parse_rate(row.iloc[column_mapping["vgm_18_20"]])
                    if rate:
                        pricing_tiers.append({
                            "container_type": "20'",
                            "container_size": 20,
                            "base_rate": rate,
                            "currency": "USD",
                            "vgm_max_weight_mt": 18
                        })
                
                if "vgm_26_20" in column_mapping:
                    rate = self._parse_rate(row.iloc[column_mapping["vgm_26_20"]])
                    if rate:
                        pricing_tiers.append({
                            "container_type": "20'",
                            "container_size": 20,
                            "base_rate": rate,
                            "currency": "USD",
                            "vgm_max_weight_mt": 26
                        })
                
                if "vgm_26_40" in column_mapping:
                    rate = self._parse_rate(row.iloc[column_mapping["vgm_26_40"]])
                    if rate:
                        pricing_tiers.append({
                            "container_type": "40'",
                            "container_size": 40,
                            "base_rate": rate,
                            "currency": "USD",
                            "vgm_max_weight_mt": 26
                        })
                
                # Fallback to regular 20'/40' columns
                if not pricing_tiers:
                    if "rate_20" in column_mapping:
                        rate = self._parse_rate(row.iloc[column_mapping["rate_20"]])
                        if rate:
                            pricing_tiers.append({
                                "container_type": "20'",
                                "container_size": 20,
                                "base_rate": rate,
                                "currency": "USD"
                            })
                    
                    if "rate_40" in column_mapping:
                        rate = self._parse_rate(row.iloc[column_mapping["rate_40"]])
                        if rate:
                            pricing_tiers.append({
                                "container_type": "40'",
                                "container_size": 40,
                                "base_rate": rate,
                                "currency": "USD"
                            })
                
                # Extract remarks
                remarks = ""
                if "remarks" in column_mapping:
                    remarks = str(row.iloc[column_mapping["remarks"]]).strip() if pd.notna(row.iloc[column_mapping["remarks"]]) else ""
                else:
                    # Check last column for remarks
                    last_cell = row.iloc[-1]
                    if pd.notna(last_cell) and isinstance(last_cell, str) and len(last_cell) > 3:
                        remarks = last_cell.strip()
                
                if pricing_tiers:
                    route = {
                        "origin_port": origin_port,
                        "destination_port": destination.upper(),
                        "routing": remarks if "via" in remarks.lower() else "N/A",
                        "service_type": "FCL",
                        "remarks": remarks if "via" not in remarks.lower() else "",
                        "pricing_tiers": pricing_tiers
                    }
                    routes.append(route)
                    
            except Exception as e:
                logger.warning(f"Error processing row {idx}: {e}")
                continue
        
        return routes, "\n".join(semantic_parts), carrier_name
    
    def _extract_projection_format(self, df: pd.DataFrame) -> Tuple[List[Dict], str, Optional[str]]:
        """
        Extract from Projection format.
        Similar to Origin Header but with additional target columns.
        """
        # Reuse origin header logic with slight modifications
        return self._extract_origin_header_format(df)
    
    def _parse_rate(self, value) -> Optional[float]:
        """Parse rate value, handling ranges like '525-550'"""
        if pd.isna(value):
            return None
        
        str_val = str(value).strip().upper()
        if str_val in ["NA", "N/A", "", "-", "NAN"]:
            return None
        
        # Handle ranges: take the lower value
        if "-" in str_val and not str_val.startswith("-"):
            parts = str_val.split("-")
            try:
                return float(parts[0].strip())
            except:
                pass
        
        # Handle with currency symbols
        str_val = re.sub(r'[USD$€£,]', '', str_val)
        
        # Handle "+IHC" type suffixes
        str_val = re.sub(r'\+.*', '', str_val)
        
        try:
            return float(str_val)
        except:
            return None
    
    def _parse_transit_days(self, value) -> Optional[int]:
        """Parse transit time to integer days"""
        if not value or pd.isna(value):
            return None
        
        match = re.search(r'(\d+)\s*(?:days?|d)', str(value), re.IGNORECASE)
        if match:
            return int(match.group(1))
        return None
    
    def _parse_detention_days(self, value) -> Optional[int]:
        """Parse free detention to integer days"""
        if not value or pd.isna(value):
            return None
        
        match = re.search(r'(\d+)\s*(?:days?|d)', str(value), re.IGNORECASE)
        if match:
            return int(match.group(1))
        return None


# Test function
async def test_pandas_extractor():
    """Test the pandas extractor on demo files"""
    import os
    
    extractor = PandasRateSheetExtractor()
    
    test_files = [
        "/Users/rohitboni/Downloads/freight_forwarder/rate-sheets-demo/MAXICON PKG MRG JAN 26.xls",
        "/Users/rohitboni/Downloads/freight_forwarder/rate-sheets-demo/THAILAND RATESHEET & PROJECTION - JAN 2026.xlsx"
    ]
    
    for file_path in test_files:
        if not os.path.exists(file_path):
            print(f"File not found: {file_path}")
            continue
        
        print(f"\n{'='*80}")
        print(f"Testing: {os.path.basename(file_path)}")
        print(f"{'='*80}")
        
        try:
            result = await extractor.extract_from_file(file_path)
            
            print(f"Carrier: {result.get('carrier_name')}")
            print(f"Format: {result.get('detected_format')}")
            print(f"Validity: {result.get('validity')}")
            print(f"Total Routes: {result.get('total_routes')}")
            print(f"Confidence: {result.get('confidence')}")
            
            print("\nSample Routes:")
            for route in result.get('routes', [])[:5]:
                origin = route.get('origin_port')
                dest = route.get('destination_port')
                pricing = route.get('pricing_tiers', [])
                rates = ", ".join([f"{p.get('container_type')}: ${p.get('base_rate')}" for p in pricing[:2]])
                print(f"  {origin} → {dest}: {rates}")
                
        except Exception as e:
            print(f"Error: {e}")
            import traceback
            traceback.print_exc()


if __name__ == "__main__":
    import asyncio
    asyncio.run(test_pandas_extractor())
