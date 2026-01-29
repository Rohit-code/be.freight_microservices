#!/usr/bin/env python3
"""
Quick fix: Create rate_sheet_structured_data table
Run: python fix_table.py
"""
import asyncio
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

async def main():
    """Create the missing table"""
    print("🔧 Creating rate_sheet_structured_data table...")
    
    try:
        # Import everything needed
        from app.core.database import init_db, engine, Base
        from app.models.structured_data import RateSheetStructuredData  # Import to register
        
        # Create tables
        await init_db()
        
        print("✅ Table created successfully!")
        print("\n💡 Restart the Rate Sheet Service to use the new table")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        from app.core.database import engine
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
