#!/bin/bash
set -e

# Fix permissions for chroma_data directory if it exists
if [ -d "/app/chroma_data" ]; then
    # Ensure the directory is writable by appuser (uid 1000)
    chown -R 1000:1000 /app/chroma_data 2>/dev/null || true
    chmod -R 755 /app/chroma_data 2>/dev/null || true
fi

# Execute the original command
exec "$@"
