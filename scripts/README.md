# Seed test customer and orders (Docker)

Inserts test customer and sample orders into **Docker Postgres** so you can use the Customer Portal.

**Credentials:** test@test.com / password123  
**Login URL:** `/customer-portal/login?organization_id=1`

## Prerequisites

- Postgres running in Docker (e.g. `docker-compose up -d postgres`).
- Tables exist: start **customer_service** and **order_service** at least once so they create their DBs/tables.
- One organization in the app (org id `1` and auth user id `1` by default).

## Run (one shell command)

From `microservices/`:

```bash
bash scripts/seed_customer_and_orders.sh
```

Uses Postgres container `freight_postgres` by default. Override:

```bash
PG_CONTAINER=your_postgres_container bash scripts/seed_customer_and_orders.sh
```

Optional: `ORG_ID=1 USER_ID=1` (defaults).

## Check Docker

```bash
docker ps -a
```

Use the postgres container name as `PG_CONTAINER` if it’s not `freight_postgres`.

## After seeding

Open **`/customer-portal/login?organization_id=1`** and sign in with **test@test.com** / **password123**. You’ll see orders and tracking.
