"""
Create database for rate sheet service
Run this script to create the PostgreSQL database
"""
import asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from app.core.config import settings


async def create_database():
    """Create the database if it doesn't exist"""
    import asyncpg
    
    try:
        # Connect to postgres database (not the target database)
        conn = await asyncpg.connect(
            host=settings.DB_HOST,
            port=settings.DB_PORT,
            user=settings.DB_USER,
            password=settings.DB_PASSWORD,
            database="postgres"  # Connect to default postgres database
        )
        
        try:
            # Check if database exists
            db_exists = await conn.fetchval(
                "SELECT 1 FROM pg_database WHERE datname = $1",
                settings.DB_NAME
            )
            
            if db_exists:
                print(f"✅ Database '{settings.DB_NAME}' already exists")
            else:
                # Create database
                await conn.execute(f'CREATE DATABASE "{settings.DB_NAME}"')
                print(f"✅ Created database '{settings.DB_NAME}'")
        finally:
            await conn.close()
    except ImportError:
        print("⚠️  asyncpg not installed. Using psql command instead...")
        import subprocess
        result = subprocess.run(
            ["psql", "-U", settings.DB_USER, "-h", settings.DB_HOST, "-c", f'CREATE DATABASE "{settings.DB_NAME}";'],
            capture_output=True,
            text=True
        )
        if result.returncode == 0:
            print(f"✅ Created database '{settings.DB_NAME}'")
        else:
            print(f"⚠️  Database creation skipped (may already exist): {result.stderr}")


async def create_tables():
    """Create tables in the database"""
    from app.core.database import init_db
    
    try:
        await init_db()
        print("✅ Tables created successfully")
    except Exception as e:
        print(f"❌ Error creating tables: {e}")
        raise


async def main():
    """Main function"""
    print("=" * 60)
    print("Creating Rate Sheet Service Database")
    print("=" * 60)
    
    try:
        await create_database()
        await create_tables()
        print("\n✅ Database setup completed successfully!")
    except Exception as e:
        print(f"\n❌ Error: {e}")
        raise


if __name__ == "__main__":
    asyncio.run(main())
