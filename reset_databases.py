#!/usr/bin/env python3
"""
Reset All Databases Script
Comprehensive reset of PostgreSQL, ArangoDB, and ChromaDB storage

This script:
1. Drops and recreates PostgreSQL databases
2. Resets ArangoDB graph database
3. Clears ChromaDB vector storage
4. Runs database migrations
5. Optionally clears uploaded files

Usage:
    python reset_databases.py
    # or
    ./reset_databases.sh
"""
import os
import sys
import shutil
import asyncio
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
MICROSERVICES_ROOT = Path(__file__).parent
ENV_FILE = MICROSERVICES_ROOT / ".env"
if ENV_FILE.exists():
    load_dotenv(ENV_FILE)

# Database configuration
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = int(os.getenv("DB_PORT", "5432"))
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASSWORD = os.getenv("DB_PASSWORD", "postgres")

ARANGO_HOST = os.getenv("ARANGO_HOST", "http://localhost:8529")
ARANGO_USER = os.getenv("ARANGO_USER", "root")
ARANGO_PASSWORD = os.getenv("ARANGO_PASSWORD", "password")
ARANGO_DATABASE = os.getenv("ARANGO_DATABASE", "freight_graph")

VECTOR_DB_URL = os.getenv("VECTOR_DB_SERVICE_URL", "http://localhost:8004")

DATABASES = [
    "auth_service_db",
    "user_service_db",
    "rate_sheet_service_db"
]


def print_header(text: str):
    """Print formatted header"""
    print(f"\n{'='*60}")
    print(f"  {text}")
    print(f"{'='*60}")


def print_success(text: str):
    """Print success message"""
    print(f"   ✅ {text}")


def print_warning(text: str):
    """Print warning message"""
    print(f"   ⚠️  {text}")


def print_error(text: str):
    """Print error message"""
    print(f"   ❌ {text}")


def reset_postgresql():
    """Reset PostgreSQL databases"""
    print_header("🗄️  Resetting PostgreSQL Databases")
    
    try:
        import psycopg2
        from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT
    except ImportError:
        print_error("psycopg2 not installed. Install with: pip install psycopg2-binary")
        print_warning("Skipping PostgreSQL reset")
        return False
    
    try:
        # Connect to postgres database
        conn = psycopg2.connect(
            host=DB_HOST,
            port=DB_PORT,
            user=DB_USER,
            password=DB_PASSWORD,
            database="postgres",
            connect_timeout=5
        )
        conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
        cursor = conn.cursor()
        
        success_count = 0
        for db_name in DATABASES:
            print(f"   Resetting {db_name}...")
            try:
                # Terminate existing connections
                cursor.execute(f"""
                    SELECT pg_terminate_backend(pid)
                    FROM pg_stat_activity
                    WHERE datname = '{db_name}' AND pid <> pg_backend_pid();
                """)
                
                # Drop database
                cursor.execute(f'DROP DATABASE IF EXISTS "{db_name}";')
                
                # Create database
                cursor.execute(f'CREATE DATABASE "{db_name}";')
                
                print_success(f"{db_name} reset")
                success_count += 1
            except Exception as e:
                print_error(f"Error resetting {db_name}: {e}")
        
        cursor.close()
        conn.close()
        
        if success_count == len(DATABASES):
            print_success(f"All {len(DATABASES)} PostgreSQL databases reset")
            return True
        else:
            print_warning(f"Only {success_count}/{len(DATABASES)} databases reset")
            return success_count > 0
        
    except psycopg2.OperationalError as e:
        error_msg = str(e).split('(')[0] if '(' in str(e) else str(e)
        print_error(f"PostgreSQL is not running or not accessible")
        print(f"      Error: {error_msg}")
        print(f"\n      To start PostgreSQL locally:")
        print(f"      # macOS (Homebrew)")
        print(f"      brew services start postgresql@14")
        print(f"      # or")
        print(f"      brew services start postgresql")
        print(f"\n      # Linux (systemd)")
        print(f"      sudo systemctl start postgresql")
        print(f"\n      Connection details: {DB_USER}@{DB_HOST}:{DB_PORT}")
        return False
    except Exception as e:
        print_error(f"Error connecting to PostgreSQL: {e}")
        print(f"      Make sure PostgreSQL is running and credentials are correct")
        print(f"      Connection: {DB_USER}@{DB_HOST}:{DB_PORT}")
        return False


def reset_arangodb():
    """Reset ArangoDB database (running in Docker)"""
    print_header("🕸️  Resetting ArangoDB Database")
    
    # Check if Docker is available
    import subprocess
    try:
        subprocess.run(["docker", "info"], capture_output=True, check=True, timeout=5)
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        print_warning("Docker is not running or not available")
        print("      ArangoDB runs in Docker. Please start Docker Desktop first.")
        print("      Then run: ./start_databases.sh")
        return False
    
    # Check if ArangoDB container is running
    try:
        result = subprocess.run(
            ["docker", "ps", "--filter", "name=arangodb", "--format", "{{.Names}}"],
            capture_output=True,
            text=True,
            timeout=5
        )
        if "arangodb" not in result.stdout:
            print_warning("ArangoDB container is not running")
            print("      Start it with: ./start_databases.sh")
            return False
    except Exception as e:
        print_warning(f"Error checking Docker containers: {e}")
        return False
    
    try:
        from arango import ArangoClient
    except ImportError:
        print_warning("python-arango not installed. Install with: pip install python-arango")
        print("      Skipping ArangoDB cleanup")
        return False
    
    try:
        client = ArangoClient(hosts=ARANGO_HOST, request_timeout=10)
        sys_db = client.db('_system', username=ARANGO_USER, password=ARANGO_PASSWORD)
        
        # Drop database if exists
        if sys_db.has_database(ARANGO_DATABASE):
            sys_db.delete_database(ARANGO_DATABASE)
            print_success(f"Deleted database: {ARANGO_DATABASE}")
        
        # Recreate database
        sys_db.create_database(ARANGO_DATABASE)
        print_success(f"Created database: {ARANGO_DATABASE}")
        
        return True
        
    except Exception as e:
        error_msg = str(e)
        if "Connection refused" in error_msg or "Failed to establish" in error_msg:
            print_warning("ArangoDB is not accessible")
            print(f"      Connection: {ARANGO_HOST}")
            print(f"\n      To start ArangoDB in Docker:")
            print(f"      docker run -d --name arangodb -p 8529:8529 -e ARANGO_ROOT_PASSWORD={ARANGO_PASSWORD} arangodb:latest")
            print(f"\n      Or use: ./start_databases.sh")
            print(f"\n      # Check if running")
            print(f"      curl http://localhost:8529/_api/version")
            print(f"\n      # Access web interface: http://localhost:8529")
            print(f"      # Username: {ARANGO_USER}, Password: {ARANGO_PASSWORD}")
        else:
            print_error(f"Error connecting to ArangoDB: {error_msg}")
            print(f"      Make sure ArangoDB Docker container is running at {ARANGO_HOST}")
            print(f"      Credentials: {ARANGO_USER} / {ARANGO_PASSWORD}")
        return False


async def reset_chromadb_async():
    """Reset ChromaDB/Vector storage via API and file deletion"""
    print_header("📦 Resetting Vector Storage (ChromaDB)")
    
    # Collections to clear
    collections = ["rate_sheets", "emails"]
    
    # Try to use Vector DB Service API first (more reliable)
    deleted_via_api = 0
    
    try:
        import httpx
        
        async with httpx.AsyncClient(timeout=10.0) as client:
            for collection_name in collections:
                try:
                    # Try to delete collection
                    response = await client.delete(
                        f"{VECTOR_DB_URL}/api/vector/collections/{collection_name}"
                    )
                    if response.status_code == 200:
                        print_success(f"Deleted collection '{collection_name}' via API")
                        deleted_via_api += 1
                    elif response.status_code == 404:
                        print(f"   ℹ️  Collection '{collection_name}' doesn't exist (skipping)")
                    else:
                        print_warning(f"Unexpected status {response.status_code} for '{collection_name}'")
                except httpx.ConnectError:
                    print_warning(f"Vector DB Service not running at {VECTOR_DB_URL}")
                    print("      Collections will be cleared via file deletion")
                    break
                except Exception as e:
                    print_warning(f"Could not delete '{collection_name}' via API: {e}")
        
        if deleted_via_api > 0:
            print_success(f"Deleted {deleted_via_api} collection(s) via Vector DB Service API")
    except ImportError:
        print_warning("httpx not available, skipping API-based deletion")
    except Exception as e:
        print_warning(f"Vector DB Service API unavailable: {e}")
        print("      Will fall back to file deletion")
    
    # Also delete files as fallback/cleanup
    chroma_dirs = [
        MICROSERVICES_ROOT / "chroma_db",
        MICROSERVICES_ROOT / "vector_db" / "chroma_db",
        MICROSERVICES_ROOT / "rate_sheet_service" / "chroma_db",
        MICROSERVICES_ROOT.parent / "chroma_db",
        Path.home() / ".chroma",  # Default ChromaDB location
    ]
    
    deleted_count = 0
    for chroma_dir in chroma_dirs:
        if chroma_dir.exists():
            print(f"   Clearing {chroma_dir}...")
            # Delete pickle files
            for pkl_file in chroma_dir.rglob("*.pkl"):
                try:
                    pkl_file.unlink()
                    deleted_count += 1
                except Exception:
                    pass
            # Delete database files
            for db_file in chroma_dir.rglob("*.db"):
                try:
                    db_file.unlink()
                    deleted_count += 1
                except Exception:
                    pass
            for sqlite_file in chroma_dir.rglob("*.sqlite*"):
                try:
                    sqlite_file.unlink()
                    deleted_count += 1
                except Exception:
                    pass
    
    if deleted_count > 0:
        print_success(f"Deleted {deleted_count} vector storage files")
    elif deleted_via_api == 0:
        print("   ℹ️  No vector storage files found")
    
    return True


def reset_chromadb():
    """Synchronous wrapper for ChromaDB reset"""
    return asyncio.run(reset_chromadb_async())


def reset_uploads():
    """Reset upload directories"""
    print_header("📁 Resetting Upload Directories")
    
    upload_dirs = [
        MICROSERVICES_ROOT / "rate_sheet_service" / "uploads",
    ]
    
    deleted_count = 0
    for upload_dir in upload_dirs:
        if upload_dir.exists():
            print(f"   Clearing {upload_dir}...")
            for file in upload_dir.rglob("*"):
                if file.is_file():
                    try:
                        file.unlink()
                        deleted_count += 1
                    except Exception as e:
                        print_warning(f"Could not delete {file}: {e}")
    
    if deleted_count > 0:
        print_success(f"Deleted {deleted_count} uploaded files")
    else:
        print("   ℹ️  No uploaded files found")
    
    return True


def run_migrations():
    """Run database migrations"""
    import subprocess
    print_header("🔄 Running Database Migrations")
    
    migration_results = {}
    
    # Authentication Service
    auth_dir = MICROSERVICES_ROOT / "authentication"
    if (auth_dir / "alembic").exists():
        print("   Running authentication migrations...")
        try:
            result = subprocess.run(
                [sys.executable, "-m", "alembic", "upgrade", "head"],
                cwd=str(auth_dir),
                capture_output=True,
                text=True,
                timeout=60,
                env=os.environ.copy()
            )
            if result.returncode == 0:
                print_success("Authentication migrations complete")
                migration_results["auth"] = True
                if result.stdout.strip():
                    print(f"      {result.stdout.strip()[:200]}")
            else:
                print_warning("Authentication migrations had issues")
                if result.stderr:
                    print(f"      {result.stderr[:300]}")
                migration_results["auth"] = False
        except subprocess.TimeoutExpired:
            print_warning("Authentication migrations timed out")
            migration_results["auth"] = False
        except FileNotFoundError:
            print_warning("Python or Alembic not found. Make sure you're in the virtual environment")
            migration_results["auth"] = False
        except Exception as e:
            print_warning(f"Error running authentication migrations: {e}")
            migration_results["auth"] = False
    else:
        print("   ℹ️  No authentication migrations found")
        migration_results["auth"] = None
    
    # User Service
    user_dir = MICROSERVICES_ROOT / "user_service"
    if (user_dir / "alembic").exists():
        print("   Running user service migrations...")
        try:
            result = subprocess.run(
                [sys.executable, "-m", "alembic", "upgrade", "head"],
                cwd=str(user_dir),
                capture_output=True,
                text=True,
                timeout=60,
                env=os.environ.copy()
            )
            if result.returncode == 0:
                print_success("User service migrations complete")
                migration_results["user"] = True
            else:
                print_warning("User service migrations had issues")
                if result.stderr:
                    print(f"      {result.stderr[:300]}")
                migration_results["user"] = False
        except subprocess.TimeoutExpired:
            print_warning("User service migrations timed out")
            migration_results["user"] = False
        except FileNotFoundError:
            print_warning("Python or Alembic not found")
            migration_results["user"] = False
        except Exception as e:
            print_warning(f"Error running user service migrations: {e}")
            migration_results["user"] = False
    else:
        print("   ℹ️  No user service migrations found")
        migration_results["user"] = None
    
    # Rate Sheet Service - initialize tables via init_db.py script
    rate_sheet_dir = MICROSERVICES_ROOT / "rate_sheet_service"
    init_db_script = rate_sheet_dir / "init_db.py"
    
    if init_db_script.exists():
        print("   Initializing rate sheet service tables...")
        try:
            result = subprocess.run(
                [sys.executable, str(init_db_script)],
                cwd=str(rate_sheet_dir),
                capture_output=True,
                text=True,
                timeout=60,
                env=os.environ.copy()
            )
            if result.returncode == 0:
                print_success("Rate sheet service tables initialized")
                # Show some output
                if result.stdout:
                    lines = result.stdout.strip().split('\n')
                    # Show last few lines that show the tables created
                    for line in lines[-5:]:
                        if line.strip():
                            print(f"      {line}")
                migration_results["rate_sheet"] = True
            else:
                print_warning("Rate sheet service table initialization had issues")
                if result.stderr:
                    print(f"      {result.stderr[:300]}")
                if result.stdout:
                    print(f"      {result.stdout[-300:]}")
                migration_results["rate_sheet"] = False
        except subprocess.TimeoutExpired:
            print_warning("Rate sheet service initialization timed out")
            migration_results["rate_sheet"] = False
        except Exception as e:
            print_warning(f"Error initializing rate sheet tables: {e}")
            print(f"      Tables will be created on first service startup")
            migration_results["rate_sheet"] = False
    elif (rate_sheet_dir / "app").exists():
        # Fallback: try to run init_db directly
        print("   Initializing rate sheet service tables (fallback method)...")
        try:
            sys.path.insert(0, str(rate_sheet_dir))
            # CRITICAL: Import models first to register them with Base.metadata
            from app.models import RateSheetStructuredData, Route, PricingTier, Surcharge  # noqa: F401
            from app.core.database import init_db
            asyncio.run(init_db())
            print_success("Rate sheet service tables initialized")
            migration_results["rate_sheet"] = True
        except Exception as e:
            print_warning(f"Error initializing rate sheet tables: {e}")
            print(f"      Tables will be created on first service startup")
            migration_results["rate_sheet"] = False
        finally:
            # Clean up path
            if str(rate_sheet_dir) in sys.path:
                sys.path.remove(str(rate_sheet_dir))
    else:
        print("   ℹ️  Rate sheet service not found")
        migration_results["rate_sheet"] = None
    
    # Ensure we're back in the root directory
    os.chdir(MICROSERVICES_ROOT)
    
    return migration_results


def main():
    """Main reset function"""
    print_header("🗑️  Resetting All Databases")
    print(f"\n📋 Configuration:")
    print(f"   PostgreSQL: {DB_USER}@{DB_HOST}:{DB_PORT}")
    print(f"   ArangoDB: {ARANGO_USER}@{ARANGO_HOST}")
    print(f"   Vector DB: {VECTOR_DB_URL}")
    print()
    
    # Reset PostgreSQL
    pg_success = reset_postgresql()
    
    # Reset ArangoDB
    arango_success = reset_arangodb()
    
    # Reset ChromaDB
    chroma_success = reset_chromadb()
    
    # Ask about uploads
    print()
    try:
        response = input("🗑️  Delete uploaded files? (y/N): ").strip().lower()
        if response == 'y':
            reset_uploads()
        else:
            print("   ℹ️  Skipping upload directory cleanup")
    except (KeyboardInterrupt, EOFError):
        print("\n   ℹ️  Skipping upload directory cleanup")
    
    # Run migrations
    migration_results = {}
    if pg_success:
        migration_results = run_migrations()
    
    # Summary
    print_header("✅ Database Reset Complete")
    print("\n📋 Summary:")
    
    if pg_success:
        print_success("PostgreSQL databases reset and recreated")
    else:
        print_warning("PostgreSQL reset skipped (database not running)")
        print("      Start PostgreSQL first, then run this script again")
    
    if arango_success:
        print_success("ArangoDB database reset")
    else:
        print_warning("ArangoDB reset skipped (database not running)")
        print("      Start ArangoDB first, then run this script again")
    
    if chroma_success:
        print_success("ChromaDB/Vector storage cleared")
    
    # Migration summary
    if migration_results:
        print("\n🔄 Migration Summary:")
        for service, result in migration_results.items():
            if result is True:
                print_success(f"{service} migrations completed")
            elif result is False:
                print_warning(f"{service} migrations had issues")
            elif result is None:
                print(f"   ℹ️  {service} service not found")
    
    # Check if databases need to be started
    if not pg_success or not arango_success:
        print("\n💡 Quick Start Commands:")
        if not pg_success:
            print("   # Start PostgreSQL locally:")
            print("   # macOS: brew services start postgresql")
            print("   # Linux: sudo systemctl start postgresql")
        if not arango_success:
            print("   # Start ArangoDB in Docker:")
            print(f"   docker run -d --name arangodb -p 8529:8529 -e ARANGO_ROOT_PASSWORD={ARANGO_PASSWORD} arangodb:latest")
            print("   # Or use: ./start_databases.sh")
        print("\n   Or run: ./start_databases.sh (to check status)")
        print("   Then run this script again to reset databases")
    
    print("\n🚀 Once databases are running, start services with:")
    print("   ./start_services.sh")
    print()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⚠️  Reset cancelled by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
