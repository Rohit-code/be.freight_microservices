#!/usr/bin/env bash
# Seed test customer and orders into Docker Postgres. Run from repo root or microservices/.
# Usage: bash scripts/seed_customer_and_orders.sh   (do NOT run with python)
# Login: test@test.com / password123 at /customer-portal/login?organization_id=1

set -e
PG_CONTAINER="${PG_CONTAINER:-freight_postgres}"
ORG_ID="${ORG_ID:-1}"
USER_ID="${USER_ID:-1}"

echo "Using Postgres container: $PG_CONTAINER"
docker ps -a --format '{{.Names}}' | grep -q "^${PG_CONTAINER}$" || { echo "Container $PG_CONTAINER not found. Set PG_CONTAINER=your_postgres_container"; exit 1; }

# Create databases if missing (e.g. container was created before they were in docker-compose)
for db in customer_service_db order_service_db; do
  EXISTS=$(docker exec "$PG_CONTAINER" psql -U postgres -d postgres -t -A -c "SELECT 1 FROM pg_database WHERE datname = '$db'" 2>/dev/null | tr -d '\r\n ')
  if [ -z "$EXISTS" ]; then
    echo "Creating database: $db"
    docker exec "$PG_CONTAINER" psql -U postgres -d postgres -c "CREATE DATABASE $db;"
  fi
done

# Create tables if missing (so script works even if customer/order services never started)
docker exec "$PG_CONTAINER" psql -U postgres -d customer_service_db -c "
  CREATE TABLE IF NOT EXISTS customers (
    id SERIAL PRIMARY KEY,
    organization_id INTEGER,
    user_id INTEGER NOT NULL,
    company_name VARCHAR(255) NOT NULL,
    contact_email VARCHAR(255) NOT NULL,
    default_origin_port VARCHAR(128),
    default_destination_port VARCHAR(128),
    preferences JSON,
    password_hash VARCHAR(255),
    created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT NOW() NOT NULL
  );
" > /dev/null

docker exec "$PG_CONTAINER" psql -U postgres -d order_service_db -c "
  CREATE TABLE IF NOT EXISTS orders (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL,
    customer_id INTEGER,
    reference_number VARCHAR(64) UNIQUE NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'booked',
    origin_port VARCHAR(128),
    destination_port VARCHAR(128),
    carrier VARCHAR(128),
    created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT NOW() NOT NULL
  );
  CREATE TABLE IF NOT EXISTS order_tracking_events (
    id SERIAL PRIMARY KEY,
    order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    event_type VARCHAR(64) NOT NULL,
    description TEXT,
    location VARCHAR(256),
    occurred_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL
  );
  CREATE TABLE IF NOT EXISTS containers (
    id SERIAL PRIMARY KEY,
    order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    container_number VARCHAR(64) NOT NULL,
    container_type VARCHAR(32),
    created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT NOW() NOT NULL
  );
" > /dev/null

# bcrypt hash for password123 (generated inside Docker to avoid local Python/passlib issues)
HASH=$(docker run --rm python:3.11-slim sh -c "pip install bcrypt -q && python3 -c \"import bcrypt; print(bcrypt.hashpw(b'password123', bcrypt.gensalt()).decode())\"")
HASH_SAFE="${HASH//\'/\'\'}"

# Customer (skip if already exists)
docker exec "$PG_CONTAINER" psql -U postgres -d customer_service_db -t -A -c "
  INSERT INTO customers (organization_id, user_id, company_name, contact_email, password_hash, created_at, updated_at)
  SELECT $ORG_ID, $USER_ID, 'Test Company', 'test@test.com', '$HASH_SAFE', NOW(), NOW()
  WHERE NOT EXISTS (SELECT 1 FROM customers WHERE contact_email = 'test@test.com' AND organization_id = $ORG_ID);
" > /dev/null

CUSTOMER_ID=$(docker exec "$PG_CONTAINER" psql -U postgres -d customer_service_db -t -A -c "SELECT id FROM customers WHERE contact_email = 'test@test.com' AND organization_id = $ORG_ID LIMIT 1;")
CUSTOMER_ID=$(echo "$CUSTOMER_ID" | tr -d '\r\n ')
[ -z "$CUSTOMER_ID" ] && { echo "Failed to get customer id"; exit 1; }
echo "Customer id: $CUSTOMER_ID"

# Orders + tracking (reference_number is unique, so we insert only if missing)
for REF in ORD-TEST-001 ORD-TEST-002 ORD-TEST-003; do
  case "$REF" in
    ORD-TEST-001) STATUS=in_transit; ORIGIN=Mumbai; DEST="Los Angeles"; CARRIER=Maersk ;;
    ORD-TEST-002) STATUS=booked; ORIGIN=Chennai; DEST=Rotterdam; CARRIER=MSC ;;
    ORD-TEST-003) STATUS=delivered; ORIGIN=Singapore; DEST=Hamburg; CARRIER=ONE ;;
  esac
  ORDER_ID=$(docker exec "$PG_CONTAINER" psql -U postgres -d order_service_db -t -A -c "
    INSERT INTO orders (user_id, customer_id, reference_number, status, origin_port, destination_port, carrier, created_at, updated_at)
    SELECT $USER_ID, $CUSTOMER_ID, '$REF', '$STATUS', '$ORIGIN', '$DEST', '$CARRIER', NOW(), NOW()
    WHERE NOT EXISTS (SELECT 1 FROM orders WHERE reference_number = '$REF')
    RETURNING id;
  " 2>/dev/null | grep -E '^[0-9]+$' | head -1 | tr -d '\r\n ')
  if [ -n "$ORDER_ID" ]; then
    echo "Order $REF id: $ORDER_ID"
    case "$REF" in
      ORD-TEST-001)
        docker exec "$PG_CONTAINER" psql -U postgres -d order_service_db -c "
          INSERT INTO order_tracking_events (order_id, event_type, description, location, occurred_at, created_at) VALUES
          ($ORDER_ID, 'booked', 'Booking confirmed', 'Mumbai', NOW() - INTERVAL '3 days', NOW()),
          ($ORDER_ID, 'departed', 'Departed origin port', 'Mumbai', NOW() - INTERVAL '2 days', NOW()),
          ($ORDER_ID, 'in_transit', 'Vessel at sea', NULL, NOW() - INTERVAL '1 day', NOW());
        " > /dev/null
        ;;
      ORD-TEST-002)
        docker exec "$PG_CONTAINER" psql -U postgres -d order_service_db -c "
          INSERT INTO order_tracking_events (order_id, event_type, description, location, occurred_at, created_at) VALUES
          ($ORDER_ID, 'booked', 'Booking confirmed', 'Chennai', NOW(), NOW());
        " > /dev/null
        ;;
      ORD-TEST-003)
        docker exec "$PG_CONTAINER" psql -U postgres -d order_service_db -c "
          INSERT INTO order_tracking_events (order_id, event_type, description, location, occurred_at, created_at) VALUES
          ($ORDER_ID, 'booked', 'Booking confirmed', 'Singapore', NOW() - INTERVAL '4 days', NOW()),
          ($ORDER_ID, 'departed', 'Departed origin', 'Singapore', NOW() - INTERVAL '3 days', NOW()),
          ($ORDER_ID, 'in_transit', 'In transit', NULL, NOW() - INTERVAL '2 days', NOW()),
          ($ORDER_ID, 'arrived', 'Arrived at destination', 'Hamburg', NOW() - INTERVAL '1 day', NOW()),
          ($ORDER_ID, 'delivered', 'Delivered to consignee', 'Hamburg', NOW(), NOW());
        " > /dev/null
        ;;
    esac
  fi
done

# Containers: add sample containers per order (idempotent: skip if already exist)
for REF in ORD-TEST-001 ORD-TEST-002 ORD-TEST-003; do
  ORDER_ID=$(docker exec "$PG_CONTAINER" psql -U postgres -d order_service_db -t -A -c "SELECT id FROM orders WHERE reference_number = '$REF' LIMIT 1;" 2>/dev/null | tr -d '\r\n ')
  [ -z "$ORDER_ID" ] && continue
  case "$REF" in
    ORD-TEST-001)
      docker exec "$PG_CONTAINER" psql -U postgres -d order_service_db -c "
        INSERT INTO containers (order_id, container_number, container_type, created_at, updated_at)
        SELECT $ORDER_ID, 'CNTR-001-1', '20GP', NOW(), NOW()
        WHERE NOT EXISTS (SELECT 1 FROM containers WHERE order_id = $ORDER_ID AND container_number = 'CNTR-001-1');
        INSERT INTO containers (order_id, container_number, container_type, created_at, updated_at)
        SELECT $ORDER_ID, 'CNTR-001-2', '40HC', NOW(), NOW()
        WHERE NOT EXISTS (SELECT 1 FROM containers WHERE order_id = $ORDER_ID AND container_number = 'CNTR-001-2');
      " > /dev/null
      echo "Containers for $REF: CNTR-001-1 (20GP), CNTR-001-2 (40HC)"
      ;;
    ORD-TEST-002)
      docker exec "$PG_CONTAINER" psql -U postgres -d order_service_db -c "
        INSERT INTO containers (order_id, container_number, container_type, created_at, updated_at)
        SELECT $ORDER_ID, 'CNTR-002-1', '20GP', NOW(), NOW()
        WHERE NOT EXISTS (SELECT 1 FROM containers WHERE order_id = $ORDER_ID AND container_number = 'CNTR-002-1');
      " > /dev/null
      echo "Containers for $REF: CNTR-002-1 (20GP)"
      ;;
    ORD-TEST-003)
      docker exec "$PG_CONTAINER" psql -U postgres -d order_service_db -c "
        INSERT INTO containers (order_id, container_number, container_type, created_at, updated_at)
        SELECT $ORDER_ID, 'CNTR-003-1', '40HC', NOW(), NOW()
        WHERE NOT EXISTS (SELECT 1 FROM containers WHERE order_id = $ORDER_ID AND container_number = 'CNTR-003-1');
        INSERT INTO containers (order_id, container_number, container_type, created_at, updated_at)
        SELECT $ORDER_ID, 'CNTR-003-2', '40HC', NOW(), NOW()
        WHERE NOT EXISTS (SELECT 1 FROM containers WHERE order_id = $ORDER_ID AND container_number = 'CNTR-003-2');
      " > /dev/null
      echo "Containers for $REF: CNTR-003-1 (40HC), CNTR-003-2 (40HC)"
      ;;
  esac
done

echo "Done. Login: test@test.com / password123 at /customer-portal/login?organization_id=$ORG_ID"
