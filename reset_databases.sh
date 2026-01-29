#!/bin/bash

# Reset All Databases Script
# Comprehensive reset of PostgreSQL, ArangoDB, and ChromaDB storage
#
# This script:
# 1. Drops and recreates PostgreSQL databases
# 2. Resets ArangoDB graph database
# 3. Clears ChromaDB vector storage
# 4. Runs database migrations
# 5. Optionally clears uploaded files
#
# Usage:
#     ./reset_databases.sh
#     # or
#     python reset_databases.py

set -euo pipefail  # Exit on error, undefined vars, pipe failures

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Function to print header
print_header() {
    echo ""
    echo "============================================================"
    echo "  $1"
    echo "============================================================"
}

# Function to print success
print_success() {
    echo -e "   ${GREEN}✅ $1${NC}"
}

# Function to print warning
print_warning() {
    echo -e "   ${YELLOW}⚠️  $1${NC}"
}

# Function to print error
print_error() {
    echo -e "   ${RED}❌ $1${NC}"
}

# Function to print info
print_info() {
    echo -e "   ${BLUE}ℹ️  $1${NC}"
}

# Load environment variables if .env exists
if [ -f .env ]; then
    set -a
    source .env
    set +a
fi

# Default values if not in .env
DB_HOST=${DB_HOST:-localhost}
DB_PORT=${DB_PORT:-5432}
DB_USER=${DB_USER:-postgres}
DB_PASSWORD=${DB_PASSWORD:-postgres}

ARANGO_HOST=${ARANGO_HOST:-http://localhost:8529}
ARANGO_USER=${ARANGO_USER:-root}
ARANGO_PASSWORD=${ARANGO_PASSWORD:-password}
ARANGO_DATABASE=${ARANGO_DATABASE:-freight_graph}

VECTOR_DB_URL=${VECTOR_DB_SERVICE_URL:-http://localhost:8004}

print_header "🗑️  Resetting All Databases"
echo ""
echo "📋 Configuration:"
echo "   PostgreSQL: ${DB_USER}@${DB_HOST}:${DB_PORT}"
echo "   ArangoDB: ${ARANGO_USER}@${ARANGO_HOST}"
echo "   Vector DB: ${VECTOR_DB_URL}"
echo ""

# ============================================
# PostgreSQL Databases
# ============================================
print_header "🗄️  Resetting PostgreSQL Databases"

DATABASES=(
    "auth_service_db"
    "user_service_db"
    "rate_sheet_service_db"
)

SUCCESS_COUNT=0
for DB_NAME in "${DATABASES[@]}"; do
    echo "   Resetting ${DB_NAME}..."
    
    # Terminate existing connections and drop database
    if PGPASSWORD="${DB_PASSWORD}" psql -h "${DB_HOST}" -p "${DB_PORT}" -U "${DB_USER}" -d postgres -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '${DB_NAME}' AND pid <> pg_backend_pid();" > /dev/null 2>&1; then
        : # Connections terminated
    fi
    
    # Drop database
    if PGPASSWORD="${DB_PASSWORD}" psql -h "${DB_HOST}" -p "${DB_PORT}" -U "${DB_USER}" -d postgres -c "DROP DATABASE IF EXISTS \"${DB_NAME}\";" > /dev/null 2>&1; then
        : # Database dropped
    fi
    
    # Create database
    if PGPASSWORD="${DB_PASSWORD}" psql -h "${DB_HOST}" -p "${DB_PORT}" -U "${DB_USER}" -d postgres -c "CREATE DATABASE \"${DB_NAME}\";" > /dev/null 2>&1; then
        print_success "${DB_NAME} reset"
        ((SUCCESS_COUNT++))
    else
        print_error "Failed to reset ${DB_NAME}"
        print_warning "Make sure PostgreSQL is running:"
        echo "      # macOS: brew services start postgresql"
        echo "      # Linux: sudo systemctl start postgresql"
    fi
done

if [ $SUCCESS_COUNT -eq ${#DATABASES[@]} ]; then
    print_success "All ${#DATABASES[@]} PostgreSQL databases reset"
    PG_SUCCESS=true
else
    print_warning "Only ${SUCCESS_COUNT}/${#DATABASES[@]} databases reset"
    PG_SUCCESS=false
fi

echo ""

# ============================================
# Run Migrations
# ============================================
if [ "$PG_SUCCESS" = true ]; then
    print_header "🔄 Running Database Migrations"
    
    # Authentication Service Migrations
    if [ -d "authentication/alembic" ]; then
        echo "   Running authentication migrations..."
        cd authentication
        if alembic upgrade head > /dev/null 2>&1; then
            print_success "Authentication migrations complete"
            AUTH_MIGRATION=true
        else
            print_warning "Authentication migrations had issues (may need manual setup)"
            AUTH_MIGRATION=false
        fi
        cd ..
    else
        print_info "No authentication migrations found"
        AUTH_MIGRATION=null
    fi
    
    # User Service Migrations
    if [ -d "user_service/alembic" ]; then
        echo "   Running user service migrations..."
        cd user_service
        if alembic upgrade head > /dev/null 2>&1; then
            print_success "User service migrations complete"
            USER_MIGRATION=true
        else
            print_warning "User service migrations had issues (may need manual setup)"
            USER_MIGRATION=false
        fi
        cd ..
    else
        print_info "No user service migrations found"
        USER_MIGRATION=null
    fi
    
    # Rate Sheet Service (uses init_db, not alembic)
    if [ -d "rate_sheet_service" ]; then
        print_info "Rate sheet service will initialize tables on startup"
        RATE_SHEET_MIGRATION=null
    else
        print_info "Rate sheet service not found"
        RATE_SHEET_MIGRATION=null
    fi
    
    echo ""
else
    print_warning "Skipping migrations (PostgreSQL not available)"
    AUTH_MIGRATION=null
    USER_MIGRATION=null
    RATE_SHEET_MIGRATION=null
fi

# ============================================
# ArangoDB Database
# ============================================
print_header "🕸️  Resetting ArangoDB Database"

# Check if Docker is available
if ! command -v docker &> /dev/null; then
    print_warning "Docker is not installed or not in PATH"
    print_warning "ArangoDB runs in Docker. Please install Docker Desktop first."
    ARANGO_SUCCESS=false
elif ! docker info > /dev/null 2>&1; then
    print_warning "Docker is not running"
    print_warning "Please start Docker Desktop first."
    ARANGO_SUCCESS=false
else
    # Check if ArangoDB container is running
    if docker ps --filter "name=arangodb" --format "{{.Names}}" | grep -q arangodb; then
        echo "   Resetting ArangoDB database..."
        
        # Try using HTTP API first
        if command -v curl &> /dev/null; then
            # Drop database if exists
            if curl -s -X DELETE -u "${ARANGO_USER}:${ARANGO_PASSWORD}" \
                "${ARANGO_HOST}/_api/database/${ARANGO_DATABASE}" > /dev/null 2>&1; then
                print_success "Deleted database: ${ARANGO_DATABASE}"
            fi
            
            # Create database
            if curl -s -X POST -u "${ARANGO_USER}:${ARANGO_PASSWORD}" \
                "${ARANGO_HOST}/_api/database" \
                -d "{\"name\": \"${ARANGO_DATABASE}\"}" > /dev/null 2>&1; then
                print_success "Created database: ${ARANGO_DATABASE}"
                ARANGO_SUCCESS=true
            else
                print_warning "Failed to create database via API, trying Docker exec..."
                ARANGO_SUCCESS=false
            fi
        fi
        
        # Fallback: Use Docker exec
        if [ "${ARANGO_SUCCESS:-false}" != "true" ]; then
            if docker exec -i arangodb arangosh --server.password "${ARANGO_PASSWORD}" \
                --javascript.execute "db._dropDatabase('${ARANGO_DATABASE}'); db._createDatabase('${ARANGO_DATABASE}');" > /dev/null 2>&1; then
                print_success "ArangoDB database reset via Docker exec"
                ARANGO_SUCCESS=true
            else
                print_error "Failed to reset ArangoDB database"
                ARANGO_SUCCESS=false
            fi
        fi
    else
        print_warning "ArangoDB container is not running"
        echo "      To start ArangoDB in Docker:"
        echo "      docker run -d --name arangodb -p 8529:8529 -e ARANGO_ROOT_PASSWORD=${ARANGO_PASSWORD} arangodb:latest"
        echo "      Or use: ./start_databases.sh"
        ARANGO_SUCCESS=false
    fi
fi

echo ""

# ============================================
# ChromaDB / Vector Storage
# ============================================
print_header "📦 Resetting Vector Storage (ChromaDB)"

# Collections to clear
COLLECTIONS=("rate_sheets" "emails")

# Try to delete collections via API first (if Vector DB Service is running)
DELETED_VIA_API=0
if command -v curl &> /dev/null; then
    for COLLECTION in "${COLLECTIONS[@]}"; do
        echo "   Deleting collection '${COLLECTION}' via API..."
        if curl -s -X DELETE "${VECTOR_DB_URL}/api/vector/collections/${COLLECTION}" > /dev/null 2>&1; then
            print_success "Deleted collection '${COLLECTION}' via API"
            ((DELETED_VIA_API++))
        else
            print_info "Collection '${COLLECTION}' not found or Vector DB Service not running"
        fi
    done
    
    if [ $DELETED_VIA_API -gt 0 ]; then
        print_success "Deleted ${DELETED_VIA_API} collection(s) via Vector DB Service API"
    fi
else
    print_warning "curl not found, skipping API-based deletion"
fi

# Also delete files as fallback/cleanup
CHROMA_DIRS=(
    "chroma_db"
    "vector_db/chroma_db"
    "rate_sheet_service/chroma_db"
    "../chroma_db"
    "${HOME}/.chroma"
)

DELETED_FILES=0
for DIR in "${CHROMA_DIRS[@]}"; do
    if [ -d "${DIR}" ]; then
        echo "   Clearing ${DIR}..."
        find "${DIR}" -name "*.pkl" -type f -delete 2>/dev/null || true
        find "${DIR}" -name "*.db" -type f -delete 2>/dev/null || true
        find "${DIR}" -name "*.sqlite*" -type f -delete 2>/dev/null || true
        DELETED_FILES=$((DELETED_FILES + $(find "${DIR}" -name "*.pkl" -o -name "*.db" -o -name "*.sqlite*" 2>/dev/null | wc -l | tr -d ' ')))
    fi
done

if [ $DELETED_FILES -gt 0 ] || [ $DELETED_VIA_API -gt 0 ]; then
    print_success "ChromaDB/Vector storage cleared"
    CHROMA_SUCCESS=true
else
    print_info "No vector storage files found"
    CHROMA_SUCCESS=true  # Not an error if nothing to delete
fi

echo ""

# ============================================
# Upload Directories (Optional)
# ============================================
read -p "🗑️  Delete uploaded files? (y/N): " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    print_header "📁 Clearing Upload Directories"
    
    UPLOAD_DIRS=(
        "rate_sheet_service/uploads"
    )
    
    DELETED_UPLOADS=0
    for DIR in "${UPLOAD_DIRS[@]}"; do
        if [ -d "${DIR}" ]; then
            echo "   Clearing ${DIR}..."
            DELETED_COUNT=$(find "${DIR}" -type f | wc -l | tr -d ' ')
            find "${DIR}" -type f -delete 2>/dev/null || true
            if [ "$DELETED_COUNT" -gt 0 ]; then
                print_success "Deleted ${DELETED_COUNT} file(s) from ${DIR}"
                DELETED_UPLOADS=$((DELETED_UPLOADS + DELETED_COUNT))
            fi
        fi
    done
    
    if [ $DELETED_UPLOADS -gt 0 ]; then
        print_success "Deleted ${DELETED_UPLOADS} uploaded file(s)"
    else
        print_info "No uploaded files found"
    fi
else
    print_info "Skipping upload directory cleanup"
fi

echo ""

# ============================================
# Summary
# ============================================
print_header "✅ Database Reset Complete"

echo ""
echo "📋 Summary:"

if [ "$PG_SUCCESS" = true ]; then
    print_success "PostgreSQL databases reset and recreated"
else
    print_warning "PostgreSQL reset skipped (database not running)"
    echo "      Start PostgreSQL first, then run this script again"
fi

if [ "${ARANGO_SUCCESS:-false}" = true ]; then
    print_success "ArangoDB database reset"
else
    print_warning "ArangoDB reset skipped (database not running)"
    echo "      Start ArangoDB first, then run this script again"
fi

if [ "${CHROMA_SUCCESS:-false}" = true ]; then
    print_success "ChromaDB/Vector storage cleared"
fi

# Migration summary
if [ "$PG_SUCCESS" = true ]; then
    echo ""
    echo "🔄 Migration Summary:"
    if [ "${AUTH_MIGRATION:-null}" = "true" ]; then
        print_success "Authentication migrations completed"
    elif [ "${AUTH_MIGRATION:-null}" = "false" ]; then
        print_warning "Authentication migrations had issues"
    fi
    
    if [ "${USER_MIGRATION:-null}" = "true" ]; then
        print_success "User service migrations completed"
    elif [ "${USER_MIGRATION:-null}" = "false" ]; then
        print_warning "User service migrations had issues"
    fi
    
    if [ "${RATE_SHEET_MIGRATION:-null}" = "null" ]; then
        print_info "Rate sheet service will initialize on startup"
    fi
fi

# Check if databases need to be started
if [ "$PG_SUCCESS" != true ] || [ "${ARANGO_SUCCESS:-false}" != true ]; then
    echo ""
    echo "💡 Quick Start Commands:"
    if [ "$PG_SUCCESS" != true ]; then
        echo "   # Start PostgreSQL locally:"
        echo "   # macOS: brew services start postgresql"
        echo "   # Linux: sudo systemctl start postgresql"
    fi
    if [ "${ARANGO_SUCCESS:-false}" != true ]; then
        echo "   # Start ArangoDB in Docker:"
        echo "   docker run -d --name arangodb -p 8529:8529 -e ARANGO_ROOT_PASSWORD=${ARANGO_PASSWORD} arangodb:latest"
        echo "   # Or use: ./start_databases.sh"
    fi
    echo ""
    echo "   Or run: ./start_databases.sh (to check status)"
    echo "   Then run this script again to reset databases"
fi

echo ""
echo "🚀 Once databases are running, start services with:"
echo "   ./start_services.sh"
echo ""
