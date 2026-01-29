#!/usr/bin/env python
"""
Database Initialization Script for Rate Sheet Service

Creates all tables for the rate sheet service:
- rate_sheet_structured_data (main table)
- routes (normalized)
- pricing_tiers (normalized)
- surcharges (normalized)

Usage:
    cd rate_sheet_service
    python init_db.py
"""
import asyncio
import sys
from pathlib import Path

# Add the parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

# Import database and models
from app.core.config import settings
from app.core.database import Base, engine

# CRITICAL: Import all models to register them with Base.metadata
from app.models import RateSheetStructuredData, Route, PricingTier, Surcharge  # noqa: F401


async def check_connection():
    """Check if PostgreSQL is reachable"""
    try:
        async with engine.connect() as conn:
            result = await conn.execute(text("SELECT 1"))
            result.fetchone()
            return True
    except Exception as e:
        print(f"❌ Cannot connect to PostgreSQL: {e}")
        return False


async def create_database_if_not_exists():
    """Create the database if it doesn't exist"""
    # Connect to default postgres database to create our database
    default_url = f"postgresql+asyncpg://{settings.DB_USER}:{settings.DB_PASSWORD}@{settings.DB_HOST}:{settings.DB_PORT}/postgres"
    default_engine = create_async_engine(default_url, isolation_level="AUTOCOMMIT")
    
    try:
        async with default_engine.connect() as conn:
            # Check if database exists
            result = await conn.execute(
                text(f"SELECT 1 FROM pg_database WHERE datname = '{settings.DB_NAME}'")
            )
            exists = result.fetchone() is not None
            
            if not exists:
                print(f"📦 Creating database '{settings.DB_NAME}'...")
                await conn.execute(text(f'CREATE DATABASE "{settings.DB_NAME}"'))
                print(f"✅ Database '{settings.DB_NAME}' created")
            else:
                print(f"✅ Database '{settings.DB_NAME}' already exists")
                
    except Exception as e:
        print(f"⚠️  Could not create database (may already exist): {e}")
    finally:
        await default_engine.dispose()


async def init_db():
    """Initialize database - create all tables"""
    print("\n" + "=" * 60)
    print("🗄️  Rate Sheet Service - Database Initialization")
    print("=" * 60)
    print(f"\nDatabase URL: postgresql://{settings.DB_USER}:***@{settings.DB_HOST}:{settings.DB_PORT}/{settings.DB_NAME}")
    
    # First, try to create the database
    await create_database_if_not_exists()
    
    # Check connection to the target database
    if not await check_connection():
        print("\n❌ Cannot proceed - PostgreSQL is not reachable")
        print("\nMake sure PostgreSQL is running:")
        print("  brew services start postgresql@14")
        print("  # or")
        print("  pg_ctl -D /usr/local/var/postgresql@14 start")
        return False
    
    print("\n✅ Connected to PostgreSQL")
    
    # List registered models
    print("\n📋 Registered models:")
    for table_name in Base.metadata.tables.keys():
        print(f"   - {table_name}")
    
    # Create all tables
    print("\n🔧 Creating tables...")
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        print("✅ All tables created successfully!")
    except Exception as e:
        print(f"❌ Error creating tables: {e}")
        return False
    
    # Verify tables exist
    print("\n🔍 Verifying tables...")
    try:
        async with engine.connect() as conn:
            result = await conn.execute(text("""
                SELECT table_name 
                FROM information_schema.tables 
                WHERE table_schema = 'public' 
                AND table_type = 'BASE TABLE'
                ORDER BY table_name
            """))
            tables = [row[0] for row in result.fetchall()]
            
            expected_tables = ['rate_sheet_structured_data', 'routes', 'pricing_tiers', 'surcharges']
            
            print("\n   Existing tables:")
            for table in tables:
                status = "✅" if table in expected_tables else "  "
                print(f"   {status} {table}")
            
            # Check for missing tables
            missing = set(expected_tables) - set(tables)
            if missing:
                print(f"\n⚠️  Missing tables: {missing}")
                return False
            else:
                print("\n✅ All expected tables exist!")
                
    except Exception as e:
        print(f"⚠️  Could not verify tables: {e}")
    
    # Show index information
    print("\n📑 Created indexes:")
    try:
        async with engine.connect() as conn:
            result = await conn.execute(text("""
                SELECT indexname, tablename 
                FROM pg_indexes 
                WHERE schemaname = 'public'
                AND indexname LIKE 'idx_%'
                ORDER BY tablename, indexname
            """))
            indexes = result.fetchall()
            
            current_table = None
            for idx_name, table_name in indexes:
                if table_name != current_table:
                    current_table = table_name
                    print(f"\n   {table_name}:")
                print(f"      - {idx_name}")
                
    except Exception as e:
        print(f"⚠️  Could not list indexes: {e}")
    
    print("\n" + "=" * 60)
    print("✅ Database initialization complete!")
    print("=" * 60 + "\n")
    
    return True


async def drop_all_tables():
    """Drop all tables (use with caution!)"""
    print("\n⚠️  Dropping all tables...")
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        print("✅ All tables dropped")
    except Exception as e:
        print(f"❌ Error dropping tables: {e}")


async def main():
    """Main entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Initialize Rate Sheet Service database')
    parser.add_argument('--drop', action='store_true', help='Drop all tables before creating')
    parser.add_argument('--drop-only', action='store_true', help='Only drop tables (dangerous!)')
    args = parser.parse_args()
    
    try:
        if args.drop_only:
            confirm = input("⚠️  This will DELETE ALL DATA. Type 'yes' to confirm: ")
            if confirm.lower() == 'yes':
                await drop_all_tables()
            else:
                print("Aborted.")
            return
        
        if args.drop:
            confirm = input("⚠️  This will DELETE ALL DATA and recreate tables. Type 'yes' to confirm: ")
            if confirm.lower() != 'yes':
                print("Aborted.")
                return
            await drop_all_tables()
        
        success = await init_db()
        sys.exit(0 if success else 1)
        
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
