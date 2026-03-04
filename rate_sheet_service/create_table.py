#!/usr/bin/env python3
"""
Create rate_sheet_structured_data table manually
Run this if the table doesn't exist after service startup
"""
import asyncio
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

from app.core.database import init_db, engine
from app.models import RateSheetStructuredData  # Import model to register it


async def create_table():
    """Create the table"""
    print("Creating rate_sheet_structured_data table...")
    try:
        # Import the model to ensure it's registered with Base.metadata
        from app.models.structured_data import RateSheetStructuredData
        
        # Create all tables
        from app.core.database import Base
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        
        print("✅ Table created successfully!")
        
        # Verify table exists
        from sqlalchemy import inspect, text
        async with engine.connect() as conn:
            result = await conn.execute(text("""
                SELECT table_name 
                FROM information_schema.tables 
                WHERE table_schema = 'public' 
                AND table_name = 'rate_sheet_structured_data'
            """))
            table_exists = result.fetchone() is not None
            if table_exists:
                print("✅ Verified: rate_sheet_structured_data table exists")
            else:
                print("⚠️  Warning: Table not found in database")
                # List all tables
                result = await conn.execute(text("""
                    SELECT table_name 
                    FROM information_schema.tables 
                    WHERE table_schema = 'public'
                """))
                tables = [row[0] for row in result.fetchall()]
                print(f"   Available tables: {tables}")
        
    except Exception as e:
        print(f"❌ Error creating table: {e}")
        import traceback
        traceback.print_exc()
        raise
    finally:
        await engine.dispose()


if __name__ == "__main__":
    from app.core.database import Base
    asyncio.run(create_table())
