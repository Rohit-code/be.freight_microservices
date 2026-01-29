#!/bin/bash

# Install Python Dependencies
# This script installs all required Python packages

set -e

echo "📦 Installing Python Dependencies..."
echo ""

# Check if virtual environment is activated
if [ -z "$VIRTUAL_ENV" ]; then
    echo "⚠️  Virtual environment not activated"
    echo "   Activate it first: source venv/bin/activate"
    exit 1
fi

echo "✅ Virtual environment: $VIRTUAL_ENV"
echo ""

# Upgrade pip
echo "⬆️  Upgrading pip..."
pip install --upgrade pip setuptools wheel

echo ""

# Install requirements
echo "📥 Installing from requirements.txt..."
pip install -r requirements.txt

echo ""

# Verify critical packages
echo "🔍 Verifying critical packages..."

packages=(
    "fastapi"
    "uvicorn"
    "sqlalchemy"
    "psycopg2-binary"
    "python-arango"
    "openai"
    "sentence-transformers"
)

for package in "${packages[@]}"; do
    if pip show "$package" > /dev/null 2>&1; then
        version=$(pip show "$package" | grep Version | awk '{print $2}')
        echo "   ✅ $package ($version)"
    else
        echo "   ❌ $package (not installed)"
    fi
done

echo ""
echo "✅ Dependency installation complete!"
echo ""
echo "💡 If python-arango failed to install, try:"
echo "   pip install python-arango"
echo ""
