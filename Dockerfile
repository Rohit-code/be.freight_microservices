# Multi-stage Dockerfile for Freight Forwarder Microservices
FROM python:3.11-slim AS base

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN groupadd --gid 1000 appgroup && \
    useradd --uid 1000 --gid appgroup --shell /bin/bash --create-home appuser

WORKDIR /app

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --upgrade pip && \
    pip install -r requirements.txt

# Copy shared code
COPY shared/ /app/shared/

# The service-specific code will be mounted or copied based on build args
ARG SERVICE_NAME=api_gateway
ENV SERVICE_NAME=${SERVICE_NAME}

# Copy service code
COPY ${SERVICE_NAME}/ /app/${SERVICE_NAME}/

# Set working directory to service
WORKDIR /app/${SERVICE_NAME}

# Change ownership
RUN chown -R appuser:appgroup /app

# Switch to non-root user
USER appuser

# Default port (overridden per service)
ARG PORT=8000
ENV PORT=${PORT}
EXPOSE ${PORT}

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:${PORT}/health || exit 1

# Start uvicorn
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
