# Freight Forwarder - AI-Powered Freight Forwarding Automation Platform

A comprehensive microservices-based platform for automating freight forwarding operations with AI-powered email processing, semantic search, and intelligent automation.

## 📋 Table of Contents

- [Architecture Overview](#architecture-overview)
- [Services](#services)
- [Prerequisites](#prerequisites)
- [Setup Guide](#setup-guide)
- [Running Services](#running-services)
- [Database Setup](#database-setup)
- [Environment Variables](#environment-variables)
- [Gmail Webhook Setup](#gmail-webhook-setup)
- [API Endpoints](#api-endpoints)
- [Email Storage](#email-storage)
- [Admin Features](#admin-features)
- [Troubleshooting](#troubleshooting)

---

## 🏗️ Architecture Overview

The platform uses a **microservices architecture** with the following components:

```
┌─────────────────┐
│   Frontend      │  Next.js 16, React 19, TypeScript
│  (Port 3000)    │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  API Gateway    │  Routes requests to microservices
│  (Port 8000)    │
└────────┬────────┘
         │
    ┌────┴────┬──────────┬──────────┬──────────┬──────────┐
    ▼         ▼          ▼          ▼          ▼          ▼
┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐
│  Auth   │ │   User  │ │  Email  │ │  Vector │ │   AI    │ │Constants│
│ Service │ │ Service │ │ Service │ │   DB    │ │ Service │ │ Service │
│ 8001    │ │  8006   │ │  8005   │ │  8004   │ │  8003   │ │  8002   │
└─────────┘ └─────────┘ └─────────┘ └─────────┘ └─────────┘ └─────────┘
    │           │           │           │           │           │
    ▼           ▼           ▼           ▼           ▼           ▼
┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐
│PostgreSQL│ │PostgreSQL│ │ChromaDB │ │ChromaDB │ │  OpenAI │ │   N/A   │
│  (Auth)  │ │  (User)  │ │ (Emails)│ │ (Emails)│ │  API    │ │         │
└─────────┘ └─────────┘ └─────────┘ └─────────┘ └─────────┘ └─────────┘
```

### Key Features

- **Real-time Email Monitoring**: Gmail webhooks via Google Cloud Pub/Sub
- **Semantic Search**: BGE embeddings for intelligent email search
- **Vector Storage**: ChromaDB for email storage with full raw content + embeddings
- **Organization Management**: Multi-tenant organization and user management
- **AI Integration**: OpenAI API for intelligent email processing
- **Admin Dashboard**: Comprehensive admin interface for managing organizations and settings

---

## 🔧 Services

### 1. **API Gateway** (Port 8000)
- Routes all incoming requests to appropriate microservices
- Handles CORS and request forwarding
- Entry point for all API calls

### 2. **Authentication Service** (Port 8001)
- User authentication (Google OAuth & credentials)
- JWT token generation and validation
- Gmail API integration
- Gmail webhook handling (Pub/Sub notifications)
- **Database**: PostgreSQL (`auth_service_db`)

### 3. **User Service** (Port 8006)
- Organization management
- User profiles and roles
- Team management and invitations
- Email settings and preferences
- **Database**: PostgreSQL (`user_service_db`)

### 4. **Email Service** (Port 8005)
- Email storage in Vector DB
- Email retrieval and search
- Email status management (read, processed, etc.)
- **Storage**: ChromaDB (no PostgreSQL)

### 5. **Vector DB Service** (Port 8004)
- ChromaDB wrapper with BGE embeddings
- Document storage with embeddings
- Semantic search capabilities
- **Storage**: Local pickle files (`chroma_db/` directory)

### 6. **AI Service** (Port 8003)
- OpenAI API integration
- Email analysis and response generation
- AI-powered automation

### 7. **Constants Service** (Port 8002)
- Static data and constants
- Reference data management

---

## 📦 Prerequisites

Before starting, ensure you have:

1. **Python 3.14** (or Python 3.10+)
2. **PostgreSQL** (version 12+)
   - Two databases needed: `auth_service_db` and `user_service_db`
3. **Node.js 18+** (for frontend)
4. **Google Cloud Project** (for Gmail integration)
   - OAuth 2.0 credentials
   - Pub/Sub topic and subscription
5. **OpenAI API Key** (for AI service)

---

## 🚀 Setup Guide

### Step 1: Clone and Navigate

```bash
cd microservices
```

### Step 2: Create Virtual Environment

```bash
# Create virtual environment
python3.14 -m venv venv

# Activate virtual environment
# On macOS/Linux:
source venv/bin/activate

# On Windows:
venv\Scripts\activate
```

### Step 3: Install Dependencies

```bash
# Upgrade pip
pip install --upgrade pip setuptools wheel

# Install all dependencies
pip install -r requirements.txt
```

### Step 4: Set Up PostgreSQL Databases

Create the required databases:

```bash
# Create auth_service_db
psql -U postgres -c "CREATE DATABASE auth_service_db;"

# Create user_service_db
psql -U postgres -c "CREATE DATABASE user_service_db;"
```

Or use the provided script:

```bash
# For authentication service
cd authentication
python create_db.py
cd ..

# For user service (create manually or use similar script)
psql -U postgres -c "CREATE DATABASE user_service_db;"
```

### Step 5: Run Database Migrations

```bash
# Authentication service migrations
cd authentication
alembic upgrade head
cd ..

# User service migrations
cd user_service
alembic upgrade head
cd ..
```

### Step 6: Configure Environment Variables

Create a `.env` file in the `microservices/` directory:

```bash
# Database Configuration
DB_HOST=localhost
DB_PORT=5432
DB_USER=postgres
DB_PASSWORD=postgres

# JWT Configuration
JWT_SECRET=your-super-secret-jwt-key-change-this-in-production
JWT_EXPIRY_MINUTES=1440

# Google OAuth Configuration
GOOGLE_CLIENT_ID=your-google-client-id.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=your-google-client-secret
GOOGLE_REDIRECT_URI=http://localhost:8000/api/auth/google/callback

# Gmail Push Notifications (Pub/Sub)
GOOGLE_CLOUD_PROJECT=your-gcp-project-id
GMAIL_PUBSUB_TOPIC=projects/your-project-id/topics/gmail-notifications
GMAIL_WEBHOOK_URL=https://your-domain.com/api/auth/gmail/webhook

# OpenAI API (for AI service)
OPENAI_API_KEY=your-openai-api-key

# Service URLs (usually defaults are fine)
AUTH_SERVICE_URL=http://localhost:8001
USER_SERVICE_URL=http://localhost:8006
EMAIL_SERVICE_URL=http://localhost:8005
VECTOR_DB_SERVICE_URL=http://localhost:8004
AI_SERVICE_URL=http://localhost:8003
CONSTANTS_SERVICE_URL=http://localhost:8002
FRONTEND_URL=http://localhost:3000
```

---

## 🏃 Running Services

### Option 1: Using Startup Script (Recommended)

```bash
# Make script executable
chmod +x start_services.sh

# Start all services
./start_services.sh
```

This will start all services in the background. Press `Ctrl+C` to stop all services.

### Option 2: Run Services Individually

Open separate terminal windows for each service:

**Terminal 1 - API Gateway:**
```bash
cd microservices/api_gateway
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

**Terminal 2 - Authentication Service:**
```bash
cd microservices/authentication
uvicorn app.main:app --host 0.0.0.0 --port 8001 --reload
```

**Terminal 3 - User Service:**
```bash
cd microservices/user_service
uvicorn app.main:app --host 0.0.0.0 --port 8006 --reload
```

**Terminal 4 - Email Service:**
```bash
cd microservices/email_service
uvicorn app.main:app --host 0.0.0.0 --port 8005 --reload
```

**Terminal 5 - Vector DB Service:**
```bash
cd microservices/vector_db
uvicorn app.main:app --host 0.0.0.0 --port 8004 --reload
```

**Terminal 6 - AI Service:**
```bash
cd microservices/ai_service
uvicorn app.main:app --host 0.0.0.0 --port 8003 --reload
```

**Terminal 7 - Constants Service:**
```bash
cd microservices/constants
uvicorn app.main:app --host 0.0.0.0 --port 8002 --reload
```

### Verify Services Are Running

Check health endpoints:

```bash
# API Gateway
curl http://localhost:8000/health

# Authentication Service
curl http://localhost:8001/health

# User Service
curl http://localhost:8006/health

# Email Service
curl http://localhost:8005/health

# Vector DB Service
curl http://localhost:8004/health

# AI Service
curl http://localhost:8003/health

# Constants Service
curl http://localhost:8002/health
```

---

## 🗄️ Database Setup

### Authentication Service Database

```bash
cd microservices/authentication

# Create database (if not exists)
python create_db.py

# Run migrations
alembic upgrade head
```

### User Service Database

```bash
cd microservices/user_service

# Create database manually
psql -U postgres -c "CREATE DATABASE user_service_db;"

# Run migrations
alembic upgrade head
```

### Database Schema

**Authentication Service** (`auth_service_db`):
- `users` table: User accounts, Google OAuth tokens, connection status

**User Service** (`user_service_db`):
- `organizations` table: Organization details, settings, email thresholds
- `user_profiles` table: User profiles, signatures, departments
- `user_organizations` table: User-organization relationships, roles
- `roles` table: Role definitions (admin, member, etc.)
- `invitations` table: Organization invitations

**Email Storage** (ChromaDB):
- Collection: `emails`
- Stores: Full raw email content + embeddings + metadata
- Location: `microservices/chroma_db/emails.pkl`

---

## 🔐 Environment Variables

All services read from a single `.env` file in the `microservices/` directory.

### Required Variables

| Variable | Description | Example |
|----------|-------------|---------|
| `DB_HOST` | PostgreSQL host | `localhost` |
| `DB_PORT` | PostgreSQL port | `5432` |
| `DB_USER` | PostgreSQL user | `postgres` |
| `DB_PASSWORD` | PostgreSQL password | `postgres` |
| `JWT_SECRET` | Secret key for JWT tokens | `your-secret-key` |
| `GOOGLE_CLIENT_ID` | Google OAuth client ID | `xxx.apps.googleusercontent.com` |
| `GOOGLE_CLIENT_SECRET` | Google OAuth client secret | `xxx` |
| `GOOGLE_CLOUD_PROJECT` | GCP project ID | `your-project-id` |
| `GMAIL_PUBSUB_TOPIC` | Pub/Sub topic for Gmail | `projects/xxx/topics/gmail-notifications` |
| `GMAIL_WEBHOOK_URL` | Webhook URL for Pub/Sub | `https://your-domain.com/api/auth/gmail/webhook` |

### Optional Variables (with defaults)

- `JWT_EXPIRY_MINUTES=1440` (24 hours)
- `GOOGLE_REDIRECT_URI=http://localhost:8000/api/auth/google/callback`
- `OPENAI_API_KEY` (for AI service)

---

## 📧 Gmail Webhook Setup

### Step 1: Create Google Cloud Project

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project or select existing one
3. Enable Gmail API and Cloud Pub/Sub API

### Step 2: Create Pub/Sub Topic and Subscription

```bash
# Create topic
gcloud pubsub topics create gmail-notifications --project=your-project-id

# Create subscription
gcloud pubsub subscriptions create gmail-notifications-sub \
  --topic=gmail-notifications \
  --push-endpoint=https://your-domain.com/api/auth/gmail/webhook \
  --project=your-project-id
```

### Step 3: Grant Permissions

Grant the Pub/Sub service account permission to publish:

```bash
# Get the service account email
gcloud pubsub topics get-iam-policy gmail-notifications --project=your-project-id

# Grant Publisher role to gmail-api-push@system.gserviceaccount.com
gcloud projects add-iam-policy-binding your-project-id \
  --member="serviceAccount:gmail-api-push@system.gserviceaccount.com" \
  --role="roles/pubsub.publisher"
```

### Step 4: Configure OAuth 2.0

1. Go to [Google Cloud Console > APIs & Services > Credentials](https://console.cloud.google.com/apis/credentials)
2. Create OAuth 2.0 Client ID
3. Add authorized redirect URIs:
   - `http://localhost:8000/api/auth/google/callback` (development)
   - `https://your-domain.com/api/auth/google/callback` (production)
4. Copy Client ID and Secret to `.env` file

### Step 5: Start Gmail Watch

After user logs in, call the watch endpoint:

```bash
POST /api/auth/gmail/watch/start
Authorization: Bearer <user-token>
```

This sets up push notifications for the user's Gmail inbox.

---

## 📡 API Endpoints

All endpoints are accessed through the API Gateway at `http://localhost:8000`.

### Authentication Endpoints

```
POST   /api/auth/login              # Login with credentials
POST   /api/auth/signup             # Sign up new user
POST   /api/auth/logout             # Logout
GET    /api/auth/me                 # Get current user
GET    /api/auth/google             # Initiate Google OAuth
POST   /api/auth/google/callback    # OAuth callback
POST   /api/auth/gmail/watch/start  # Start Gmail push notifications
POST   /api/auth/gmail/watch/stop   # Stop Gmail push notifications
POST   /api/auth/gmail/webhook      # Gmail Pub/Sub webhook (called by Google)
```

### User Service Endpoints

```
GET    /api/user/organizations                    # Get user's organizations
POST   /api/user/organizations                    # Create organization
GET    /api/user/organizations/{id}               # Get organization details
PATCH  /api/user/organizations/{id}               # Update organization
GET    /api/user/admin/organizations               # Get all organizations (admin)
PATCH  /api/user/organizations/{id}/email-settings # Update email settings
GET    /api/user/profiles/me                      # Get current user profile
PATCH  /api/user/profiles/{id}                    # Update user profile
GET    /api/user/organizations/{id}/users         # Get organization users
POST   /api/user/organizations/{id}/invitations    # Invite user
GET    /api/user/roles                            # Get all roles
```

### Email Service Endpoints

```
POST   /api/email/store              # Store email in vector DB
GET    /api/email/new                 # Get new emails
GET    /api/email/list                # List user emails
POST   /api/email/search              # Semantic search emails
POST   /api/email/{id}/read           # Mark email as read
POST   /api/email/{id}/processed      # Mark email as processed
POST   /api/email/fetch               # Manually fetch emails
```

### Admin Endpoints

```
GET    /api/auth/admin                # Admin dashboard data
GET    /api/auth/admin/users          # List all users (admin)
POST   /api/auth/admin/users          # Create user (admin)
PATCH  /api/auth/admin/users/{id}     # Update user (admin)
DELETE /api/auth/admin/users/{id}     # Delete user (admin)
```

---

## 📨 Email Storage

### How Emails Are Stored

1. **Gmail Webhook Received**: When a new email arrives, Google sends a Pub/Sub notification
2. **Authentication Service**: Receives webhook, identifies user, fetches email details
3. **Email Service**: Stores email in ChromaDB via Vector DB service
4. **Vector DB Service**: 
   - Stores **full raw email content** as document
   - Generates **embeddings** using BGE model (`BAAI/bge-base-en-v1.5`)
   - Stores **metadata** (user_id, gmail_message_id, dates, flags, etc.)

### Storage Format

```python
{
    "documents": [
        "Subject: Email Subject\nFrom: sender@example.com\nTo: recipient@example.com\nBody (Plain): Full email body...\nBody (HTML): <html>...</html>"
    ],
    "metadatas": [
        {
            "id": "uuid",
            "user_id": "123",
            "gmail_message_id": "xxx",
            "subject": "Email Subject",
            "from_email": "sender@example.com",
            "body_plain": "Full body text",
            "body_html": "<html>...</html>",
            "date": "2024-01-01T00:00:00",
            "is_sent": false,
            "is_read": false,
            ...
        }
    ],
    "ids": ["uuid"],
    "embeddings": [[0.1, 0.2, ...]]  # BGE embeddings
}
```

### Key Points

- ✅ **Full raw email content** is stored (not just embeddings)
- ✅ **Embeddings** are generated for semantic search
- ✅ **Metadata** contains all email fields for filtering
- ✅ **Duplicate prevention**: Checks `gmail_message_id` before storing
- ✅ **Real-time**: Emails stored instantly via webhooks (no polling)

---

## 👨‍💼 Admin Features

### Admin Dashboard

Access at: `http://localhost:3000/admin`

**Features:**
- **Overview**: System statistics and metrics
- **Admin Users**: Manage admin accounts
- **Organizations**: View and manage all organizations
- **General Settings**: Update organization information
- **Email Settings**: Configure email thresholds and automation
- **Team Management**: Manage organization members
- **Notifications**: Configure notification preferences
- **Integrations**: View webhook URLs and API documentation

### Admin Access

1. Create a user with `is_staff=True` or `is_superuser=True` in the authentication database
2. Login with that user
3. Access `/admin` route

---

## 🐛 Troubleshooting

### Services Not Starting

**Check if ports are available:**
```bash
# Check if ports are in use
lsof -i :8000  # API Gateway
lsof -i :8001  # Authentication
lsof -i :8006  # User Service
# etc.
```

**Kill processes if needed:**
```bash
kill -9 <PID>
```

### Database Connection Errors

**Verify PostgreSQL is running:**
```bash
# macOS/Linux
sudo service postgresql status
# or
brew services list  # if installed via Homebrew

# Start if not running
sudo service postgresql start
# or
brew services start postgresql
```

**Check database exists:**
```bash
psql -U postgres -l | grep auth_service_db
psql -U postgres -l | grep user_service_db
```

### Migration Errors

**Reset migrations (development only):**
```bash
cd authentication
alembic downgrade base
alembic upgrade head
```

### Gmail Webhook Not Working

1. **Verify webhook URL is accessible**: Use a tool like [ngrok](https://ngrok.com/) for local development
2. **Check Pub/Sub subscription**: Verify subscription exists and push endpoint is correct
3. **Check logs**: Look for errors in authentication service logs
4. **Verify permissions**: Ensure `gmail-api-push@system.gserviceaccount.com` has Publisher role

### Email Not Storing

1. **Check Vector DB service**: Verify it's running on port 8004
2. **Check ChromaDB directory**: Ensure `chroma_db/` directory exists and is writable
3. **Check logs**: Look for errors in email service logs
4. **Verify webhook**: Check if webhook is being received

### Admin Access Issues

1. **Verify user is admin**: Check `is_staff` or `is_superuser` flag in database
2. **Check token**: Ensure JWT token is valid and includes admin claims
3. **Check logs**: Look for 403 errors in authentication service

---

## 📁 Project Structure

```
microservices/
├── api_gateway/          # API Gateway (Port 8000)
│   └── app/
│       ├── main.py       # FastAPI app
│       └── core/
│           └── config.py # Configuration
│
├── authentication/        # Authentication Service (Port 8001)
│   ├── app/
│   │   ├── main.py
│   │   ├── api/routes.py # API endpoints
│   │   ├── models/       # SQLAlchemy models
│   │   ├── services/     # Business logic
│   │   └── core/
│   │       ├── config.py
│   │       └── database.py
│   ├── alembic/          # Database migrations
│   └── create_db.py      # Database creation script
│
├── user_service/         # User Service (Port 8006)
│   ├── app/
│   │   ├── main.py
│   │   ├── api/routes.py
│   │   ├── models/       # Organization, UserProfile, etc.
│   │   ├── services/     # Organization, UserProfile services
│   │   └── core/
│   │       ├── config.py
│   │       └── database.py
│   └── alembic/          # Database migrations
│
├── email_service/        # Email Service (Port 8005)
│   ├── app/
│   │   ├── main.py
│   │   ├── api/routes.py
│   │   ├── models/       # Email models
│   │   └── services/     # Email storage, retrieval
│   └── core/
│       └── config.py
│
├── vector_db/            # Vector DB Service (Port 8004)
│   ├── app/
│   │   ├── main.py
│   │   ├── api/routes.py
│   │   └── services/
│   │       └── vector_service.py  # ChromaDB wrapper
│   └── core/
│       └── config.py
│
├── ai_service/           # AI Service (Port 8003)
│   └── app/
│       ├── main.py
│       └── services/
│           └── ai_service.py
│
├── constants/            # Constants Service (Port 8002)
│   └── app/
│       └── main.py
│
├── chroma_db/           # ChromaDB storage directory
│   └── emails.pkl       # Email collection (pickle file)
│
├── .env                  # Environment variables (create this)
├── requirements.txt      # Python dependencies
├── start_services.sh     # Startup script
└── README.md            # This file
```

---

## 🔄 Data Flow

### Email Reception Flow

```
1. User receives email in Gmail
   ↓
2. Google Pub/Sub sends notification
   ↓
3. Authentication Service receives webhook (/api/auth/gmail/webhook)
   ↓
4. Fetches email details from Gmail API
   ↓
5. Calls Email Service (/api/email/store)
   ↓
6. Email Service calls Vector DB Service
   ↓
7. Vector DB Service:
   - Stores raw email content
   - Generates BGE embeddings
   - Stores metadata
   ↓
8. Email stored in ChromaDB (emails.pkl)
```

### User Login Flow

```
1. User logs in (Google OAuth or credentials)
   ↓
2. Authentication Service validates credentials
   ↓
3. Returns JWT token
   ↓
4. Frontend stores token
   ↓
5. Subsequent requests include token in Authorization header
   ↓
6. API Gateway forwards to appropriate service
   ↓
7. Service validates token with Authentication Service
   ↓
8. Request processed
```

---

## 🧪 Testing

### Test Email Storage

```bash
# Store an email
curl -X POST http://localhost:8000/api/email/store \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <token>" \
  -d '{
    "user_id": 1,
    "gmail_message_id": "test-123",
    "subject": "Test Email",
    "from_email": "test@example.com",
    "body_plain": "This is a test email",
    "is_sent": false
  }'
```

### Test Semantic Search

```bash
curl -X POST http://localhost:8000/api/email/search \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <token>" \
  -d '{
    "query": "shipping inquiry",
    "limit": 10
  }'
```

---

## 📝 Notes

- **Development**: All services run on `localhost` with default ports
- **Production**: Update `.env` file with production URLs and credentials
- **Database**: Each service has its own PostgreSQL database (except Email Service which uses ChromaDB)
- **Storage**: ChromaDB stores data in pickle files in `chroma_db/` directory
- **Webhooks**: For local development, use [ngrok](https://ngrok.com/) to expose webhook endpoint

---

## 🆘 Support

For issues or questions:
1. Check the [Troubleshooting](#troubleshooting) section
2. Review service logs for error messages
3. Verify all prerequisites are installed
4. Ensure databases are created and migrations are run

---

## 📄 License

[Your License Here]

---

**Last Updated**: January 2025
