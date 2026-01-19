# Authentication Microservice

FastAPI-based authentication microservice with PostgreSQL database.

## Database Setup

### 1. Create the Database

The authentication service uses its own PostgreSQL database. Create it using:

```bash
# Make sure PostgreSQL is running
# Then run:
python create_db.py
```

Or manually:
```sql
CREATE DATABASE auth_service_db;
```

### 2. Environment Variables

Create a `.env` file in the `authentication/` directory:

```env
# Database Configuration
DB_HOST=localhost
DB_PORT=5432
DB_USER=postgres
DB_PASSWORD=postgres
DB_NAME=auth_service_db

# JWT Configuration
JWT_SECRET=your-secret-key-here-change-in-production
JWT_EXPIRY_MINUTES=1440

# Google OAuth
GOOGLE_CLIENT_ID=your-google-client-id
GOOGLE_CLIENT_SECRET=your-google-client-secret
GOOGLE_BACKEND_CALLBACK_URL=http://localhost:8000/api/auth/google/callback

# Service Configuration
ENVIRONMENT=development
DEBUG=true
```

### 3. Run Migrations

```bash
# Activate virtual environment first
source ../venv/bin/activate

# Create initial migration
alembic revision --autogenerate -m "Initial migration"

# Apply migrations
alembic upgrade head
```

### 4. Run the Service

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8001 --reload
```

## Database Schema

The service uses the following main table:

- **users**: Stores user accounts, Google OAuth tokens, and connection status

## API Endpoints

- `GET /health` - Health check
- `POST /api/auth/login` - Email/password login
- `POST /api/auth/signup` - User registration
- `GET /api/auth/google` - Initiate Google OAuth
- `GET /api/auth/google/callback` - Google OAuth callback
- `POST /api/auth/google/verify` - Verify Google credential
- `GET /api/auth/me` - Get current user
- `POST /api/auth/logout` - Logout
