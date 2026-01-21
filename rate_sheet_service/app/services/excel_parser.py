import pandas as pd
import openpyxl
from typing import Dict, List, Any, Optional
from pathlib import Path
import json
import logging
import numpy as np

logger = logging.getLogger(__name__)


def convert_numpy_types(obj: Any) -> Any:
    """
    Recursively convert numpy types to native Python types for JSON serialization
    Handles numpy types, pandas types, nan, inf, and other non-serializable types
    """
    # Handle None first
    if obj is None:
        return None
    
    # Handle numpy integer types
    if isinstance(obj, (np.integer, np.int64, np.int32, np.int16, np.int8)):
        return int(obj)
    # Handle numpy float types (including nan and inf)
    elif isinstance(obj, (np.floating, np.float64, np.float32, np.float16)):
        # Check for nan and inf values
        if np.isnan(obj):
            return None
        elif np.isinf(obj):
            return None  # or could return "inf" or "-inf" as string, but None is safer
        return float(obj)
    # Handle numpy boolean
    elif isinstance(obj, np.bool_):
        return bool(obj)
    # Handle numpy arrays
    elif isinstance(obj, np.ndarray):
        return [convert_numpy_types(item) for item in obj]
    # Handle pandas Index objects
    elif hasattr(obj, '__class__') and 'pandas' in str(type(obj)) and hasattr(obj, 'tolist'):
        return [convert_numpy_types(item) for item in obj.tolist()]
    # Handle pandas NA/NaN values
    elif hasattr(obj, '__class__') and 'pandas' in str(type(obj)):
        if hasattr(obj, 'isna') and obj.isna().any() if hasattr(obj, 'any') else False:
            return None
    # Handle dictionaries
    elif isinstance(obj, dict):
        return {str(key): convert_numpy_types(value) for key, value in obj.items()}
    # Handle lists and tuples
    elif isinstance(obj, (list, tuple)):
        return [convert_numpy_types(item) for item in obj]
    # Handle native Python float (check for nan/inf)
    elif isinstance(obj, float):
        if np.isnan(obj):
            return None
        elif np.isinf(obj):
            return None
        return obj
    # Handle native Python types (pass through)
    elif isinstance(obj, (str, int, bool)):
        return obj
    # Handle datetime objects
    elif hasattr(obj, 'isoformat'):
        return obj.isoformat()
    else:
        # Try to convert numpy scalar types using item() method
        try:
            if hasattr(obj, 'item') and not isinstance(obj, (str, bytes)):
                item_value = obj.item()
                # Check if the item value is nan or inf
                if isinstance(item_value, float):
                    if np.isnan(item_value):
                        return None
                    elif np.isinf(item_value):
                        return None
                return convert_numpy_types(item_value)
        except (ValueError, AttributeError, TypeError):
            pass
        # Check if it's a pandas NA value
        try:
            if str(type(obj)) in ["<class 'pandas._libs.missing.NAType'>", "<class 'pandas._libs.tslibs.nattype.NaTType'>"]:
                return None
        except Exception:
            pass
        # Try to convert to string as last resort
        try:
            return str(obj)
        except Exception:
            return None  # Return None instead of obj if all else fails


class ExcelParser:
    """Parser for Excel rate sheet files"""
    
    def __init__(self):
        self.supported_formats = ['.xlsx', '.xls', '.csv']
    
    def parse_file(self, file_path: str) -> Dict[str, Any]:
        """
        Parse Excel file and extract raw data structure
        
        Returns:
            Dictionary with sheets, data, and metadata
        """
        file_path_obj = Path(file_path)
        file_ext = file_path_obj.suffix.lower()
        
        if file_ext not in self.supported_formats:
            raise ValueError(f"Unsupported file format: {file_ext}")
        
        result = {
            "file_name": file_path_obj.name,
            "file_type": file_ext,
            "sheets": [],
            "metadata": {}
        }
        
        try:
            if file_ext == '.csv':
                # Handle CSV files
                df = pd.read_csv(file_path)
                # Replace NaN values with None before converting to dict
                df = df.where(pd.notna(df), None)
                # Convert DataFrame to dict and handle numpy types
                data_dict = df.to_dict('records')
                sheet_data = {
                    "name": "Sheet1",
                    "data": convert_numpy_types(data_dict),
                    "columns": [str(col) for col in df.columns.tolist()],
                    "rows": int(len(df))
                }
                result["sheets"].append(sheet_data)
            else:
                # Handle Excel files
                excel_file = pd.ExcelFile(file_path, engine='openpyxl' if file_ext == '.xlsx' else None)
                
                for sheet_name in excel_file.sheet_names:
                    df = pd.read_excel(file_path, sheet_name=sheet_name, engine='openpyxl' if file_ext == '.xlsx' else None)
                    
                    # Replace NaN values with None before converting to dict
                    df = df.where(pd.notna(df), None)
                    
                    # Detect merged cells (for .xlsx)
                    merged_cells = []
                    if file_ext == '.xlsx':
                        try:
                            wb = openpyxl.load_workbook(file_path)
                            ws = wb[sheet_name]
                            merged_cells = [str(mc) for mc in ws.merged_cells.ranges]
                        except Exception as e:
                            logger.warning(f"Could not detect merged cells: {e}")
                    
                    # Convert DataFrame to dict and handle numpy types
                    data_dict = df.to_dict('records')
                    sheet_data = {
                        "name": sheet_name,
                        "data": convert_numpy_types(data_dict),
                        "columns": [str(col) for col in df.columns.tolist()],
                        "rows": int(len(df)),
                        "columns_count": int(len(df.columns)),
                        "merged_cells": merged_cells,
                        "sample_data": convert_numpy_types(self._get_sample_data(df))
                    }
                    
                    result["sheets"].append(sheet_data)
                
                # Extract metadata from Excel file properties
                try:
                    wb = openpyxl.load_workbook(file_path)
                    result["metadata"] = {
                        "title": wb.properties.title,
                        "author": wb.properties.creator,
                        "created": str(wb.properties.created) if wb.properties.created else None,
                        "modified": str(wb.properties.modified) if wb.properties.modified else None,
                    }
                except Exception as e:
                    logger.warning(f"Could not extract Excel metadata: {e}")
        
        except Exception as e:
            logger.error(f"Error parsing file {file_path}: {e}")
            raise
        
        # Ensure all numpy types are converted before returning
        return convert_numpy_types(result)
    
    def _get_sample_data(self, df: pd.DataFrame, max_rows: int = 5) -> Dict[str, Any]:
        """Extract sample data from DataFrame"""
        sample = {}
        for col in df.columns:
            # Get non-null values and replace NaN with None
            non_null_values = df[col].dropna().head(max_rows).tolist()
            # Replace any remaining NaN values
            non_null_values = [None if (isinstance(v, float) and np.isnan(v)) else v for v in non_null_values]
            sample[str(col)] = {
                "dtype": str(df[col].dtype),
                "non_null_count": int(df[col].notna().sum()),
                "sample_values": convert_numpy_types(non_null_values[:max_rows])
            }
        return sample
    
    def detect_structure(self, parsed_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Detect structure patterns in the parsed data
        This is a preliminary detection before AI analysis
        """
        structure_info = {
            "has_headers": False,
            "detected_columns": [],
            "likely_data_start_row": 0,
            "format_hints": []
        }
        
        if not parsed_data.get("sheets"):
            return structure_info
        
        # Analyze first sheet
        first_sheet = parsed_data["sheets"][0]
        columns = first_sheet.get("columns", [])
        
        # Look for common rate sheet column patterns
        common_patterns = {
            "origin": ["POL", "Origin", "From", "Origin Port", "Origin Port Code"],
            "destination": ["POD", "Destination", "To", "Destination Port", "Destination Port Code"],
            "container": ["20'", "40'", "40HC", "Container", "Container Type"],
            "routing": ["Routing", "Via", "Transit", "Route"],
            "price": ["Rate", "Price", "Freight", "Cost", "Amount"],
            "transit_time": ["Transit Time", "TT", "Days", "Transit"],
        }
        
        detected_columns = {}
        for col in columns:
            col_lower = str(col).lower()
            for pattern_type, patterns in common_patterns.items():
                for pattern in patterns:
                    if pattern.lower() in col_lower:
                        detected_columns[pattern_type] = col
                        break
        
        structure_info["detected_columns"] = detected_columns
        structure_info["has_headers"] = len(detected_columns) > 0
        
        return structure_info
