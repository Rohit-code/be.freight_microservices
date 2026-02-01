# Freight Forwarder – Application Architecture

This document describes the **architecture, storage, schemas, and flows** of the AI-powered Freight Forwarding Automation Platform as implemented in the `microservices/` codebase.

---

## 1. High-Level Architecture

The system is a **microservices-based B2B SaaS** with:

- **Single entry point**: API Gateway (port 8000)
- **Core services**: Auth, User, Email, Vector DB, AI, Constants
- **Agentic services**: Knowledge Graph, Intent Classifier, Orchestrator, Decision Engine
- **Domain service**: Rate Sheet (upload, search, draft email responses)
- **Databases**: PostgreSQL (multiple DBs), ChromaDB (vector store), ArangoDB (graph)

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                              FRONTEND (Next.js, Port 3000)                      │
└───────────────────────────────────────────┬─────────────────────────────────────┘
                                            │
                                            ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│                         API GATEWAY (FastAPI, Port 8000)                          │
│  Proxies: /api/auth/*, /api/user/*, /api/email/*, /api/vector/*, /api/ai/*,      │
│           /api/constants/*, /api/rate-sheets/*                                   │
└───┬─────┬─────┬─────┬─────┬─────┬─────┬──────────────────────────────────────────┘
    │     │     │     │     │     │     │
    ▼     ▼     ▼     ▼     ▼     ▼     ▼
┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐  ┌────────────────────────────┐
│ Auth │ │User  │ │Email │ │Vector│ │  AI  │ │Const │  │   RATE SHEET SERVICE       │
│ 8001 │ │ 8006 │ │ 8005 │ │ 8004 │ │ 8003 │ │ 8002 │  │   8010                     │
└──┬───┘ └──┬───┘ └──┬───┘ └──┬───┘ └──┬───┘ └──────┘  │  (calls internally:)       │
   │        │        │        │        │               │  - Orchestrator 8013       │
   │        │        │        │        │               │  - Intent Classifier 8012  │
   ▼        ▼        │        ▼        │               │  - Decision Engine 8014    │
┌──────┐ ┌──────┐   │   ┌──────┐   │   │               │  - Knowledge Graph 8011    │
│ PG   │ │ PG   │   │   │Chroma│   │   │               │  - Vector DB 8004          │
│auth_ │ │user_ │   │   │ (pkl)│   │   │               │  - AI 8003                 │
│svc_db│ │svc_db│   │   └──────┘   │   │               └──────────────┬─────────────┘
└──────┘ └──────┘   │              │   │                              │
                    │              │   │               ┌──────────────┴──────────────┐
                    │   ┌──────────┴───┴───┐           │ PG rate_sheet_service_db    │
                    └──►│ Vector DB 8004   │           │ ArangoDB freight_graph      │
                        │ (emails + rate   │           │ ChromaDB rate_sheets        │
                        │ _sheets in pkl)  │            └-────────────────────────────┘
                        └──────────────────┘
```

**Note:** Knowledge Graph (8011), Intent Classifier (8012), Orchestrator (8013), and Decision Engine (8014) are **not** exposed as separate routes on the API Gateway. They are used **internally** by the Rate Sheet Service (e.g. for drafting email responses).

---

## 2. Services Overview

| Service              | Port | Responsibility |
|----------------------|------|----------------|
| **API Gateway**      | 8000 | Single entry; CORS; proxy to all services; root handler can forward Pub/Sub webhooks to `/api/auth/gmail/webhook`. |
| **Authentication**   | 8001 | Login/signup, Google OAuth, JWT, Gmail/Drive/Sheets/Docs tokens, Gmail watch & webhook, admin CRUD, internal Gmail/list by user. |
| **Constants**        | 8002 | Static data (e.g. FAQs). No DB. |
| **AI Service**       | 8003 | OpenAI (e.g. GPT-4o-mini): chat, analyze email/document/spreadsheet/rate-sheet, generate email response. |
| **Vector DB**        | 8004 | ChromaDB-like API over local pickle files; BGE embeddings (`BAAI/bge-base-en-v1.5`); collections: `emails`, `rate_sheets`. |
| **Email Service**    | 8005 | Store/list/search emails in Vector DB; mark read/processed; fetch from Gmail; draft responses via Rate Sheet Service. |
| **User Service**     | 8006 | Organizations, user profiles, roles, invitations, email settings (e.g. auto_send_threshold, manual_review_threshold). |
| **Rate Sheet Service** | 8010 | Upload/process rate sheets; store in ChromaDB + PostgreSQL; query routes; draft/send email responses (orchestrator → decision engine → AI). |
| **Knowledge Graph**  | 8011 | ArangoDB graph: carriers, ports, lanes, routes; edges carry rate/validity data. |
| **Intent Classifier**| 8012 | Classify email intent (rate_inquiry, tracking, booking, general) and extract entities (ports, container type, etc.). |
| **Orchestrator**     | 8013 | Coordinates: intent → SQL (rate_sheet_service), graph (knowledge_graph), vector (vector_db); returns combined results. |
| **Decision Engine**  | 8014 | Validates orchestration results, confidence score, decision (auto_send / review_required / escalate). |

---

## 3. Databases and Storage

### 3.1 PostgreSQL (single instance, multiple databases)

Created at startup via `init-multiple-dbs.sh` (env: `POSTGRES_MULTIPLE_DATABASES`):

- **auth_service_db** – Authentication service
- **rate_sheet_service_db** – Rate sheet structured data (see §4.6 for triple store: PG + ChromaDB + ArangoDB and handling of diverse formats)
- **email_service_db** – Reserved (email content is in Vector DB; this DB is created but email storage uses ChromaDB)
- **user_service_db** – User service

### 3.2 ChromaDB (vector store)

- **Deployment**: Standalone container (port 8500→8000) **or** in-process via **Vector DB Service** (8004) using **pickle files** under `CHROMA_DB_PATH` (e.g. `/app/chroma_data` in Docker).
- **Model**: Embeddings from **BAAI/bge-base-en-v1.5** (Sentence Transformers), normalized; query side uses retrieval prefix.
- **Collections**:
  - **emails** – Full email text + metadata (user_id, gmail_message_id, subject, from, to, body, flags, drafted_response, etc.). **User-scoped**: filter by `user_id`.
  - **rate_sheets** – Rate sheet content + metadata (organization_id, user_id, file_name, carrier_name, etc.). **Organization-scoped**: filter by `organization_id`. Document text is built from AI-extracted structured data + full sheet text for semantic search. See §4.6 for how diverse/unstructured rate sheet files are normalized and stored (PG + Chroma + Arango).

### 3.3 ArangoDB (graph)

- **Container**: Port 8529; database `freight_graph`; used by Knowledge Graph Service (8011).
- **Usage**: Nodes (e.g. RateSheet, Port, Lane, Carrier); edges (e.g. HAS_ROUTE with base_rate, validity). Rates live on edges, not nodes.

---

## 4. Schemas and Data Models

### 4.1 Authentication Service (`auth_service_db`)

**Table: `users`**

| Column                   | Type           | Notes |
|--------------------------|----------------|--------|
| id                       | Integer        | PK    |
| email                    | String(255)    | Unique, indexed |
| username                 | String(150)    | Unique, indexed |
| password_hash            | String(255)    | Nullable for Google-only users |
| first_name, last_name    | String(150)     | Nullable |
| google_id                | String(255)    | Unique, nullable |
| is_google_user           | Boolean        | Default False |
| picture                  | String(500)    | Nullable |
| google_access_token      | Text           | Nullable |
| google_refresh_token     | Text           | Nullable |
| google_token_expiry      | DateTime(TZ)   | Nullable |
| gmail_connected          | Boolean        | Default False |
| drive_connected, sheets_connected, docs_connected | Boolean | Default False |
| last_processed_history_id| String(50)     | Gmail history sync |
| email_drafting_enabled   | Boolean        | Default False |
| email_drafting_enabled_at| DateTime(TZ)   | Nullable |
| is_active, is_staff, is_superuser | Boolean | Defaults True, False, False |
| created_at, updated_at, last_login | DateTime(TZ) | |

Migrations: Alembic under `authentication/alembic/`.

---

### 4.2 User Service (`user_service_db`)

**Tables:**

- **organizations** – id, name, slug, description, domain, admin_email, logo_url, website, industry_type, timezone, default_currency, status, is_active, emails_per_day_limit, ai_usage_limit, auto_send_threshold, manual_review_threshold, vip_auto_review, proactive_delay_notifications, created_at, updated_at.
- **user_profiles** – id, auth_user_id (FK to auth users), email, first_name, last_name, department, signature, is_enabled, deleted_at.
- **user_organizations** – user_profile_id, organization_id, role_id, is_active, joined_at (user–org–role link).
- **roles** – id, name, display_name, description.
- **invitations** – organization_id, invited_by_user_id, email, token, role_id, is_accepted, expires_at.

Migrations: Alembic under `user_service/alembic/`.

---

### 4.3 Rate Sheet Service (`rate_sheet_service_db`)

**Tables:**

- **rate_sheet_structured_data**
  - Primary key: `rate_sheet_id` (UUID, links to ChromaDB document).
  - organization_id, user_id, file_name, file_path, carrier_name, rate_sheet_type, title.
  - file_hash, idempotency_key (idempotent uploads).
  - status (`pending` | `processing` | `processed` | `failed`), processing_error, processing_*_at.
  - version, supersedes_rate_sheet_id, is_active, deactivated_at, deactivated_by.
  - JSONB: routes, pricing_tiers, surcharges, additional_charges (kept for compatibility).
  - valid_from, valid_to, effective_date; is_related, relationship_type, related_rate_sheet_ids.
  - created_at, updated_at.

- **routes** – id, rate_sheet_id (FK), organization_id, origin_port, origin_port_name, origin_country, destination_port, destination_port_name, destination_country, container_type, base_rate, currency, transit_time_days, transit_time_text, service_type, carrier_name, vessel_name, valid_from, valid_to, extra_data (JSONB), created_at, updated_at.

- **pricing_tiers** – id, rate_sheet_id (FK), organization_id, tier_name, tier_type, min_quantity, max_quantity, origin_port, destination_port, container_type, rate, currency, rate_basis, discount_percentage, markup_amount, valid_from, valid_to, extra_data, created_at, updated_at.

- **surcharges** – id, rate_sheet_id (FK), organization_id, surcharge_code, surcharge_name, surcharge_type, description, applies_to_all, origin_port, destination_port, container_type, amount, percentage, currency, charge_basis, is_included, valid_from, valid_to, extra_data, created_at, updated_at.

Indexes: e.g. (organization_id, valid_from, valid_to), (organization_id, status), idempotency (organization_id, file_hash), GIN on JSONB columns.

---

### 4.4 Email (Vector DB – collection `emails`)

**Logical model (metadata + document):**

- **id** – UUID (ChromaDB document id).
- **user_id** – Owner (integer); **isolation by user**.
- **gmail_message_id**, gmail_thread_id, subject, from_email, to_email, cc_email, bcc_email, snippet, body_html, body_plain, date.
- **has_attachments**, attachment_count, is_sent, is_read, is_processed, is_rate_sheet.
- **drafted_response** – JSON (subject, body, confidence, rate sheets used, etc.).
- **created_at**, **updated_at**.

Document text: full email content (e.g. subject, from, to, body plain/html) for embedding and retrieval.

---

### 4.5 Rate Sheet (Vector DB – collection `rate_sheets`)

**Logical model:**

- **id** – UUID (same as `rate_sheet_structured_data.rate_sheet_id`).
- **organization_id** – **Isolation by organization**.
- **user_id**, file_name, carrier_name, file_path, status, created_at, updated_at, processed_at, etc.
- **document** – Full rate sheet text used for embedding and semantic search.

---

### 4.6 Rate sheet ingestion: diverse formats and storage

Rate sheets in the real world are **not standardized**. They come from many carriers and sources, in different layouts, with merged cells, multiple sheets, and varying column names. The system accepts this variety and uses a **four-stage pipeline** to normalize, extract, validate, and store them in **three stores** (PostgreSQL, ChromaDB, ArangoDB).

#### Why rate sheets are diverse and unstructured

- **Different layouts**: POL/POD style (origin in header, destinations in rows), origin-in-first-column style, projection-style with volume targets, multi-sheet workbooks.
- **Different carriers**: Each carrier may use different headers (e.g. "20'", "20FT", "VGM UPTO 18MT 20'"), date formats, and section headers ("INDIAN SECTORS", "FAR EAST").
- **Non-standard structure**: Merged cells, notes in rows, validity dates in titles or footers, pricing in ranges ("525–550").
- **File formats**: Excel (.xlsx, .xls) and CSV; column names are often generic ("Unnamed: 1") or in the first data row rather than the first row.

The system does **not** require a single template. It accepts any supported file and uses **deterministic normalization** plus **AI semantic extraction** to map content into a **canonical schema**, then stores that schema in the DBs.

#### Methods used to handle and store rate sheets

**1. Pandas normalization (Stage 1 – no AI)**  
- **Goal**: Turn any Excel/CSV into a clean, machine-readable grid.  
- **Input**: Raw file (path).  
- **Output**: Normalized structure: `file_name`, `file_type`, `sheets[]` (each with `name`, `grid` 2D array, dimensions, detected header row), and `detected_metadata` (potential carriers, origins, destinations, validity hints).  
- **Why**: Removes format variability (merged cells, multiple sheets) so the next stage sees a consistent grid. No LLM is used here.

**2. AI semantic extraction (Stage 2)**  
- **Goal**: Map the normalized grid to a **canonical schema** (routes, pricing_tiers, surcharges, validity, carrier_name, etc.).  
- **Input**: Normalized data from Stage 1.  
- **Output**: Structured JSON: `rate_sheet_type`, `carrier_name`, `title`, `valid_from`/`valid_to`, `routes[]` (each with `origin_port`, `destination_port`, `routing`, `transit_time_days`, `pricing_tiers[]` with `container_type`, `base_rate`, `currency`, `vgm_max_weight_mt`, etc.), `confidence_score`, `extraction_notes`.  
- **Why**: Prompts and rules handle multiple layout patterns (POL/POD, origin-header, projection-style), port standardization (full names, codes), and extraction rules (e.g. 20' vs 40' separate, VGM tiers, skip section headers). AI is used here because the same logical data appears in many different visual layouts.

**3. Validation and guardrails (Stage 3)**  
- **Goal**: Run deterministic checks on the extracted data (required fields, numeric ranges, port presence) and optionally fix or flag issues.  
- **Output**: `is_valid`, `issues[]`.  
- **Why**: Ensures only coherent data is written to the DBs; failures are non-fatal but logged.

**4. Storage (Stage 4 – triple write)**  
- **PostgreSQL (`rate_sheet_service_db`)**:  
  - **rate_sheet_structured_data**: One row per rate sheet (rate_sheet_id, organization_id, user_id, file_name, carrier_name, status, validity, file_hash, idempotency_key, JSONB columns for backward compatibility).  
  - **Normalized tables**: **routes**, **pricing_tiers**, **surcharges** – one row per route/tier/surcharge, linked by `rate_sheet_id`. Used for exact SQL queries (e.g. query-routes by origin, destination, container, date).  
- **ChromaDB (Vector DB – collection `rate_sheets`)**:  
  - One **document** per rate sheet: id = `rate_sheet_id`, metadata = organization_id, user_id, file_name, carrier_name, etc.  
  - **Document text**: Built from the AI-extracted structured data plus full sheet text (routes, pricing, validity, carrier, remarks). This text is embedded with BGE and used for **semantic search** (e.g. “rates from Laem Chabang to India”).  
- **ArangoDB (graph)**:  
  - **Knowledge Graph Service** ingests the same structured data: nodes (RateSheet, Port, Lane, Carrier), edges (e.g. HAS_ROUTE with rate/validity). Used for **graph traversal** (alternative lanes, carrier options) in the orchestrator.

So: **diverse, unstructured files** → **normalized grid** → **canonical structured schema** → **three stores** (SQL for precise querying, vector for semantic search, graph for relationships). The same `rate_sheet_id` links the row in PostgreSQL, the document in ChromaDB, and the graph nodes/edges in ArangoDB.

---

## 5. Process Flows (Detailed)

Every major process is described below with **step-by-step flow**, **which service/DB is used**, and **what is stored or returned**.

---

### 5.1 Authentication Processes

#### 5.1.1 Login (credentials)

| Step | Actor | Action |
|------|--------|--------|
| 1 | Frontend | `POST /api/auth/login` with `{ email, password }` → API Gateway |
| 2 | API Gateway | Proxies to Authentication Service `POST /api/auth/login` |
| 3 | Authentication | Looks up user by email in **PostgreSQL (auth_service_db.users)** |
| 4 | Authentication | Verifies password with bcrypt; checks `is_active` |
| 5 | Authentication | Updates `last_login`; commits |
| 6 | Authentication | Generates JWT (user id, email); returns `{ user, token }` |
| 7 | (Optional) | If user has `gmail_connected`, Auth triggers **Email Service** `POST /api/email/fetch` (async, non-blocking) so recent Gmail messages are pulled and stored in Vector DB |

#### 5.1.2 Google OAuth – initiate

| Step | Actor | Action |
|------|--------|--------|
| 1 | Frontend | User clicks “Sign in with Google”; frontend redirects to `GET /api/auth/google` |
| 2 | API Gateway | Proxies to Authentication |
| 3 | Authentication | Builds Google OAuth URL (client_id, redirect_uri, scopes); returns **RedirectResponse** to Google consent screen |

#### 5.1.3 Google OAuth – callback

| Step | Actor | Action |
|------|--------|--------|
| 1 | Google | After user consents, redirects to `GET /api/auth/google/callback?code=...` |
| 2 | API Gateway | Proxies to Authentication |
| 3 | Authentication | Exchanges `code` for tokens (access + refresh) via Google OAuth API |
| 4 | Authentication | Fetches user profile from Google (email, name, picture); gets or creates user in **PostgreSQL users**; stores/updates `google_id`, `google_access_token`, `google_refresh_token`, `is_google_user`, etc. |
| 5 | Authentication | Generates JWT; redirects to frontend callback URL with token (e.g. in query or fragment) |

#### 5.1.4 Get current user (/me)

| Step | Actor | Action |
|------|--------|--------|
| 1 | Frontend | `GET /api/auth/me` with header `Authorization: Bearer <token>` |
| 2 | API Gateway | Proxies to Authentication |
| 3 | Authentication | Validates JWT; loads user from **PostgreSQL users**; returns user payload (id, email, has_google_connected, organization_id if resolved, etc.) |

#### 5.1.5 Logout

| Step | Actor | Action |
|------|--------|--------|
| 1 | Frontend | `POST /api/auth/logout` (optional: with token) |
| 2 | API Gateway | Proxies to Authentication |
| 3 | Authentication | Returns success (JWT is stateless; actual “logout” is client discarding the token) |

---

### 5.2 Gmail Watch & Webhook Processes

#### 5.2.1 Start Gmail watch

| Step | Actor | Action |
|------|--------|--------|
| 1 | Frontend | `POST /api/auth/gmail/watch/start` with `Authorization: Bearer <token>` |
| 2 | API Gateway | Proxies to Authentication |
| 3 | Authentication | Validates JWT; gets user; ensures Google tokens exist |
| 4 | Authentication | Calls Gmail API `users.watch()` with topic = `GMAIL_PUBSUB_TOPIC`; receives `historyId` and `expiration` |
| 5 | Authentication | Saves `last_processed_history_id` (or similar) and sets `gmail_connected`; returns success |

#### 5.2.2 Gmail webhook (Pub/Sub push) – full flow

| Step | Actor | Action |
|------|--------|--------|
| 1 | Google Pub/Sub | On new mail, POSTs to configured URL (e.g. `https://your-domain/api/auth/gmail/webhook`). Body: `{ message: { data: <base64>, messageId, publishTime }, subscription }` |
| 2 | API Gateway | If request hits `POST /` and body contains `message`/`subscription`, gateway **forwards** body to Authentication `POST /api/auth/gmail/webhook`. Otherwise proxies normally if path is `/api/auth/gmail/webhook` |
| 3 | Authentication | Decodes `message.data` (base64 JSON) → `{ emailAddress, historyId }` |
| 4 | Authentication | Finds user by `emailAddress` in **PostgreSQL users**; loads refresh token |
| 5 | Authentication | Calls Gmail API `users.history.list(userId, startHistoryId)` to get list of changed message IDs since last processed history |
| 6 | Authentication | For each **new** message ID: calls Gmail API `users.messages.get()` to get full message (headers, body, attachments metadata) |
| 7 | Authentication | For each message: calls **Email Service** `POST /api/email/store` with JSON: `user_id`, `gmail_message_id`, `gmail_thread_id`, `subject`, `from_email`, `to_email`, `body_plain`, `body_html`, `snippet`, `date`, `has_attachments`, `attachment_count`, `is_sent`, and optionally `organization_id`, `auto_draft` (e.g. from user’s default org) |
| 8 | Email Service | (See **5.3.1 Store email** below.) Stores in Vector DB; optionally requests draft from Rate Sheet Service and writes `drafted_response` back into email metadata |
| 9 | Authentication | Updates user’s `last_processed_history_id` to current `historyId` |
| 10 | Authentication | Returns HTTP 200 to Pub/Sub (so it does not retry) |

#### 5.2.3 Stop Gmail watch

| Step | Actor | Action |
|------|--------|--------|
| 1 | Frontend | `POST /api/auth/gmail/watch/stop` with Bearer token |
| 2 | API Gateway | Proxies to Authentication |
| 3 | Authentication | Validates JWT; calls Gmail API `users.stop()`; clears `gmail_connected` (and optionally watch-related fields); returns success |

---

### 5.3 Email Service Processes

#### 5.3.1 Store email (with optional auto-draft)

| Step | Actor | Action |
|------|--------|--------|
| 1 | Caller (Auth or API) | `POST /api/email/store` with body: `user_id`, `gmail_message_id`, subject, from, to, body_plain, body_html, date, flags, optional `organization_id`, optional `auto_draft` |
| 2 | API Gateway | Proxies to Email Service |
| 3 | Email Service | Generates UUID for document id; builds **document** string (e.g. subject + from + to + body); builds **metadata** (user_id, gmail_message_id, subject, from_email, to_email, body_plain, body_html, date, is_read=false, is_processed=false, is_rate_sheet=false, created_at, updated_at) |
| 4 | Email Service | Calls **Vector DB** `POST /api/vector/collections/emails/documents` with `documents=[document]`, `metadatas=[metadata]`, `ids=[uuid]`. Vector DB generates BGE embeddings and persists to **pickle (emails collection)** |
| 5 | Email Service | If `organization_id` present and `auto_draft` true: calls **Rate Sheet Service** `POST /api/rate-sheets/draft-email-response?organization_id=<id>` with `email_query` (body/snippet), `original_email_subject`, `original_email_from` |
| 6 | Rate Sheet Service | Runs **Draft email response** flow (see 5.6); returns draft, intent, decision, confidence_score |
| 7 | Email Service | If draft returned: builds `drafted_response` JSON; calls **Vector DB** `PATCH /api/vector/collections/emails/documents/<uuid>` to update metadata with `drafted_response` |
| 8 | Email Service | Returns `{ id, gmail_message_id, message, drafted_response?, has_draft? }` |

#### 5.3.2 Get new emails

| Step | Actor | Action |
|------|--------|--------|
| 1 | Frontend | `GET /api/email/new?limit=50` with Bearer token |
| 2 | Email Service | Validates token via **Authentication** `GET /api/auth/me`; gets `user_id` |
| 3 | Email Service | Calls **Vector DB** `POST /api/vector/collections/emails/query` with a broad query and `n_results=limit`; filters results by metadata `user_id`; sorts by date; returns only unread or “new” (e.g. is_processed=false) |
| 4 | Email Service | Returns `{ emails: [...], total }` |

#### 5.3.3 List user emails (with optional drafts)

| Step | Actor | Action |
|------|--------|--------|
| 1 | Frontend | `GET /api/email/list?limit=100&organization_id=...&include_drafts=true` with Bearer token |
| 2 | Email Service | Validates token; gets `user_id` (and org_id from auth or query) |
| 3 | Email Service | Queries **Vector DB** for collection `emails` filtered by `user_id`; builds list of email objects from metadata + document |
| 4 | Email Service | For each email: if `include_drafts=true` and no `drafted_response` and not processed and org_id present, calls **Rate Sheet Service** `POST /api/rate-sheets/draft-email-response?organization_id=...` with email content; attaches draft to response |
| 5 | Email Service | Returns `{ emails: [...], total }` |

#### 5.3.4 List drafts (paginated)

| Step | Actor | Action |
|------|--------|--------|
| 1 | Frontend | `GET /api/email/drafts?page=1&page_size=10` with Bearer token |
| 2 | Email Service | Validates token; gets `user_id` |
| 3 | Email Service | Queries **Vector DB** emails collection by `user_id`; filters to documents that have `drafted_response` in metadata; applies pagination (offset = (page-1)*page_size, limit = page_size) |
| 4 | Email Service | Returns `{ drafts: [{ email, draft }], pagination: { page, page_size, total_count, total_pages, has_next, has_previous } }` |

#### 5.3.5 Search emails (semantic)

| Step | Actor | Action |
|------|--------|--------|
| 1 | Frontend | `POST /api/email/search` with body `{ query, limit }` and Bearer token |
| 2 | Email Service | Validates token; gets `user_id` |
| 3 | Email Service | Calls **Vector DB** `POST /api/vector/collections/emails/query` with `query_texts=[query]`, `n_results=limit`; Vector DB computes query embedding and returns top similar documents |
| 4 | Email Service | Filters results by metadata `user_id`; maps to email list; returns `{ emails, total, query }` |

#### 5.3.6 Mark email read / processed

| Step | Actor | Action |
|------|--------|--------|
| 1 | Frontend | `POST /api/email/<email_id>/read` or `.../processed` with Bearer token |
| 2 | Email Service | Validates token; gets `user_id`; verifies document exists in Vector DB and metadata `user_id` matches |
| 3 | Email Service | Calls **Vector DB** `PATCH /api/vector/collections/emails/documents/<email_id>` with metadata update `is_read: true` or `is_processed: true` |
| 4 | Email Service | Returns success |

#### 5.3.7 Manual fetch emails

| Step | Actor | Action |
|------|--------|--------|
| 1 | Frontend | `POST /api/email/fetch` with Bearer token |
| 2 | Email Service | Validates token; gets `user_id`; checks user has Gmail connected (via auth response) |
| 3 | Email Service | Calls **Authentication** internal `GET /api/auth/internal/gmail/<user_id>/list?max_results=50` (uses stored refresh token, no user JWT) |
| 4 | Authentication | Loads user from DB; uses refresh token to get Gmail messages list; for each message fetches detail; returns list of message payloads |
| 5 | Email Service | For each message not already in Vector DB (by gmail_message_id): calls **Store email** (5.3.1) with same payload (no auto_draft unless org passed) |
| 6 | Email Service | Returns `{ message, user_id, fetched, new, existing }` |

---

### 5.4 Rate Sheet Processes

#### 5.4.1 Upload rate sheet (sync)

Upload runs the **four-stage pipeline** (see §4.6): Pandas normalization → AI semantic extraction → validation → triple storage (PostgreSQL + ChromaDB + ArangoDB). This allows diverse, unstructured rate sheet files to be stored in a canonical form.

| Step | Actor | Action |
|------|--------|--------|
| 1 | Frontend | `POST /api/rate-sheets/upload` with multipart file + query params `organization_id`, `user_id` |
| 2 | API Gateway | Proxies to Rate Sheet Service (long timeout, e.g. 600s) |
| 3 | Rate Sheet Service | Validates file type (.xlsx, .xls, .csv) and size (e.g. max 50MB); optionally computes file_hash for idempotency; saves file to disk |
| 4 | Rate Sheet Service | **Stage 1 (Pandas)**: Normalizes Excel/CSV into a clean grid + detected_metadata (no AI). **Stage 2 (AI)**: Calls AI (e.g. `POST /api/ai/chat`) with extraction prompt; receives structured JSON (routes, pricing_tiers, surcharges, validity, carrier_name). **Stage 3**: Validation/guardrails; logs issues if any. |
| 5 | Rate Sheet Service | Generates `rate_sheet_id` (UUID). **Stage 4a – ChromaDB**: Builds document text from structured data + full sheet text; calls **Vector DB** `POST /api/vector/collections/rate_sheets/documents` with document, metadata, id = rate_sheet_id. |
| 6 | Rate Sheet Service | **Stage 4b – PostgreSQL**: Inserts **rate_sheet_structured_data** (rate_sheet_id, organization_id, user_id, file_name, carrier_name, status=processed, JSONB + valid_from/valid_to); inserts normalized **routes**, **pricing_tiers**, **surcharges**. |
| 7 | Rate Sheet Service | **Stage 4c – ArangoDB**: Calls **Knowledge Graph Service** to upsert nodes (RateSheet, Port, Lane, Carrier) and edges (HAS_ROUTE with rate/validity). |
| 8 | Rate Sheet Service | Returns `{ id: rate_sheet_id, status, file_name, carrier_name, ... }` |

#### 5.4.2 Upload rate sheet (async)

| Step | Actor | Action |
|------|--------|--------|
| 1 | Frontend | `POST /api/rate-sheets/upload-async` with file + `organization_id`, `user_id` |
| 2 | Rate Sheet Service | Creates a **pending** record in **PostgreSQL** (rate_sheet_id, organization_id, user_id, file_name, status=pending); saves file to disk (e.g. uploads folder); returns immediately `{ id, status: 'pending', message }` |
| 3 | Rate Sheet Service | Enqueues a **background task** that runs the same pipeline as 5.4.1 (parse → AI → PG + graph + Vector DB); updates status to `processing` then `processed` or `failed` |
| 4 | Frontend | Polls `GET /api/rate-sheets/<id>/status?organization_id=...` until status is `processed` or `failed` |

#### 5.4.3 List / search rate sheets (agentic when query present)

| Step | Actor | Action |
|------|--------|--------|
| 1 | Frontend | `GET /api/rate-sheets/?organization_id=...&query=...&carrier_name=...&origin_code=...&destination_code=...&container_type=...&limit=50&page=1` |
| 2 | Rate Sheet Service | **No query (list path)**: Vector DB (embedding_service) with generic query; filters by organization_id and optional carrier. **With query (search/agentic path)**: calls Orchestrator (Intent + SQL + Graph + Vector), then re-rank and generate answer. |
| 3 | Rate Sheet Service | **Response**: Always returns `rate_sheets`, `total`, `page`, `page_size`. **Only when `query` is present**: also returns `answer` and, when agentic, `intent`, `engines_used`, `exact_rates`, `route_alternatives`. List calls (no query) do not include `answer` or agentic fields. |

#### 5.4.4 Get rate sheet by ID

| Step | Actor | Action |
|------|--------|--------|
| 1 | Frontend | `GET /api/rate-sheets/<rate_sheet_id>?organization_id=...` |
| 2 | Rate Sheet Service | Calls **Vector DB** `GET /api/vector/collections/rate_sheets/documents/<id>`; verifies metadata `organization_id` matches; optionally enriches from **PostgreSQL** rate_sheet_structured_data + routes/pricing_tiers/surcharges |
| 3 | Rate Sheet Service | Returns full rate sheet payload |

#### 5.4.5 Query routes (structured/SQL)

| Step | Actor | Action |
|------|--------|--------|
| 1 | Caller (e.g. Orchestrator) | `POST /api/rate-sheets/query-routes?organization_id=...` with body `{ origin_port, destination_port, container_type, valid_date }` |
| 2 | Rate Sheet Service | Uses **PostgreSQL**: queries **routes** (and optionally pricing_tiers, surcharges) filtered by organization_id and optional filters; returns `{ routes: [...], count }` |

#### 5.4.6 Delete rate sheet

| Step | Actor | Action |
|------|--------|--------|
| 1 | Frontend | `DELETE /api/rate-sheets/<rate_sheet_id>?organization_id=...` |
| 2 | Rate Sheet Service | Verifies ownership via **PostgreSQL** (get structured record by rate_sheet_id + organization_id). Deletes from **PostgreSQL**: routes, pricing_tiers, surcharges, then rate_sheet_structured_data. Deletes from **Vector DB** collection `rate_sheets` document by id. Deletes the **uploaded file** on disk (file_path from PG record) if it exists. Returns 204. (ArangoDB graph cleanup is not implemented; graph nodes/edges for this rate sheet may remain.) |

#### 5.4.7 Reprocess rate sheet / reprocess all / sync ChromaDB

- **Reprocess one**: `POST /api/rate-sheets/<id>/reprocess?organization_id=...` – re-reads stored file, re-runs AI extraction, updates PostgreSQL and optionally Vector DB/Graph.
- **Reprocess all pending**: `POST /api/rate-sheets/reprocess-all-pending?organization_id=...` – finds rows in PostgreSQL with status pending/failed; queues background reprocess for each.
- **Reprocess all**: `POST /api/rate-sheets/reprocess-all?organization_id=...` – re-runs AI extraction for all rate sheets of the org and updates normalized tables.
- **Sync ChromaDB**: `POST /api/rate-sheets/sync-chromadb?organization_id=...` – for each processed rate sheet in PostgreSQL, checks if it exists in Vector DB; if missing, builds document and adds to `rate_sheets` collection.

---

### 5.5 Send Email Response Process

| Step | Actor | Action |
|------|--------|--------|
| 1 | Frontend | `POST /api/rate-sheets/send-email-response?organization_id=...&user_id=...` with header `Authorization: Bearer <token>` and body `{ drafted_email: { subject, body, ... }, to_email, cc_email?, bcc_email? }` |
| 2 | Rate Sheet Service | Verifies token; calls **Authentication** `POST /api/auth/gmail/send` (or equivalent) with user token, to, subject, body (and optional signature from user profile) |
| 3 | Authentication | Validates JWT; gets user; uses stored Google access/refresh token; calls Gmail API `users.messages.send()` |
| 4 | Rate Sheet Service | Returns `{ success, message_id? }` or error |

---

### 5.6 Draft Email Response Process (Agentic Flow – Full Detail)

This flow is used when: (a) an email is stored with `organization_id` and `auto_draft`, (b) list emails with `include_drafts=true` and draft is missing, or (c) direct `POST /api/rate-sheets/draft-email-response?organization_id=...`.

| Step | Actor | Action |
|------|--------|--------|
| 1 | Caller | `POST /api/rate-sheets/draft-email-response?organization_id=<id>` with body `{ email_query, original_email_subject, original_email_from, limit? }` |
| 2 | Rate Sheet Service (EmailResponseServiceV2) | Calls **Orchestrator** `POST /orchestrate` (or equivalent) with organization_id, email_content=email_query, subject, from_email |
| 3 | **Orchestrator** | Calls **Intent Classifier** `POST /classify` with email content, subject, from_email |
| 4 | **Intent Classifier** | Calls **AI Service** with a classification prompt; parses response to get `intent` (rate_inquiry | tracking | booking | general), `confidence`, `entities` (origin_port, destination_port, container_type, cargo_type, quantity, carrier_preference, date_range), `query_type`, `requires_structured_data`, `requires_graph_traversal`, `requires_vector_search` |
| 5 | **Orchestrator** | If intent is “general” or low-confidence non–freight: returns early with “skip” decision; no draft body. Otherwise continues. |
| 6 | **Orchestrator** | **SQL**: Calls **Rate Sheet Service** `POST /api/rate-sheets/query-routes` with organization_id and entities (origin_port, destination_port, container_type, valid_date) → `sql_results` |
| 7 | **Orchestrator** | **Graph**: If entities have origin/destination: calls **Knowledge Graph Service** with organization_id and entities; runs AQL traversals; returns `graph_results` (e.g. alternative lanes, carrier options) |
| 8 | **Orchestrator** | **Vector**: Calls **Vector DB** `POST /api/vector/collections/rate_sheets/query` with query_texts=[email_content], n_results=limit; filters by metadata organization_id → `vector_results` |
| 9 | **Orchestrator** | Merges sql_results, graph_results, vector_results; returns to Rate Sheet Service `{ intent, results: { sql_results, graph_results, vector_results }, engines_used }` |
| 10 | Rate Sheet Service | Calls **Decision Engine** `POST /verify-and-decide` (or equivalent) with intent_result and orchestration_results |
| 11 | **Decision Engine** | Runs validity checks (e.g. has routes, dates valid); computes **confidence_score** from intent confidence + data quality + coverage; decides **decision**: auto_send | review_required | escalate; generates **reasoning**; returns `{ confidence_score, validity_checks, decision, reasoning, verified_data }` |
| 12 | Rate Sheet Service | Calls **AI Service** to generate final draft: builds prompt with email content, subject, from_email, and **verified_data** (routes, rates, surcharges); gets **subject** and **body** and **confidence_note** |
| 13 | Rate Sheet Service | Returns `{ draft: { subject, body, to, cc, bcc }, intent, decision, confidence_score, action, engines_used, rate_sheets_found, skipped? }` to caller |
| 14 | (If caller is Email Service) | Email Service updates the email document in **Vector DB** with `drafted_response` = this draft payload |

---

### 5.7 User & Organization Processes

#### 5.7.1 Create organization

| Step | Actor | Action |
|------|--------|--------|
| 1 | Frontend | `POST /api/user/organizations` with Bearer token and body `{ name, domain, admin_email, ... }` |
| 2 | User Service | Validates token via **Authentication** `GET /api/auth/me`; gets or creates **user_profile** in **PostgreSQL (user_service_db)** linked to auth user |
| 3 | User Service | Creates **Organization** row (name, slug, domain, admin_email, industry_type, timezone, default_currency, status, auto_send_threshold, manual_review_threshold, ...); creates **UserOrganization** linking user_profile to organization with role (e.g. admin) |
| 4 | User Service | Returns organization payload |

#### 5.7.2 Get / update organization

| Step | Actor | Action |
|------|--------|--------|
| 1 | Frontend | `GET /api/user/organizations/<id>` or `PATCH /api/user/organizations/<id>` with Bearer token |
| 2 | User Service | Validates token; verifies user belongs to organization (via user_organizations); reads or updates **organizations** table; for PATCH may update email_settings (auto_send_threshold, manual_review_threshold, etc.) |
| 3 | User Service | Returns organization payload |

#### 5.7.3 Get user organizations

| Step | Actor | Action |
|------|--------|--------|
| 1 | Frontend | `GET /api/user/organizations` with Bearer token |
| 2 | User Service | Validates token; gets user_profile; queries **user_organizations** + **organizations** for that user; returns list of organizations with role |

#### 5.7.4 User profile get / update

| Step | Actor | Action |
|------|--------|--------|
| 1 | Frontend | `GET /api/user/profiles/me` or `PATCH /api/user/profiles/<id>` with Bearer token |
| 2 | User Service | Validates token; gets or updates **user_profiles** (first_name, last_name, department, signature, is_enabled); returns profile |

#### 5.7.5 Create invitation / accept invitation

| Step | Actor | Action |
|------|--------|--------|
| 1 | Admin | `POST /api/user/organizations/<id>/invitations` with body `{ email, role_id }`; User Service creates **invitations** row (organization_id, email, token, role_id, expires_at) and returns invite link or token |
| 2 | Invitee | `GET /api/user/invitations/<token>` or similar to load invite; `POST` to accept; User Service creates **user_profile** if needed, creates **UserOrganization** with role_id; marks invitation is_accepted |

---

### 5.8 Vector DB Operations (As Used by Other Flows)

- **Create collection**: `POST /api/vector/collections` with `{ name }` → creates new pickle-backed collection (e.g. `emails`, `rate_sheets`).
- **Add documents**: `POST /api/vector/collections/<name>/documents` with `documents`, `metadatas`, `ids` → BGE embeddings generated for each document; appended to collection and saved to pickle.
- **Query**: `POST /api/vector/collections/<name>/query` with `query_texts`, `n_results` → query embedded with BGE (with retrieval prefix); cosine similarity over collection; returns ids, documents, metadatas, distances.
- **Get document**: `GET /api/vector/collections/<name>/documents/<doc_id>` → returns single document + metadata.
- **Update metadata**: `PATCH /api/vector/collections/<name>/documents/<doc_id>` with `metadata` → updates only metadata for that id; saves pickle.
- **Delete document**: `DELETE /api/vector/collections/<name>/documents/<doc_id>` → removes from in-memory lists and embeddings array; saves pickle.
- **List collections / get collection info**: `GET /api/vector/collections` or `GET /api/vector/collections/<name>` → list .pkl files or count for one collection.

---

### 5.9 AI Service Operations (As Used by Other Flows)

- **Chat**: `POST /api/ai/chat` – `message` + `conversation_history` → OpenAI completion → `{ response }`.
- **Analyze email**: `POST /api/ai/analyze-email` – `content`, `subject`, `from` → structured analysis (summary, sentiment, priority, etc.).
- **Generate email response**: `POST /api/ai/generate-email-response` – `content`, `subject`, `tone` → draft body text.
- **Analyze spreadsheet**: `POST /api/ai/analyze-spreadsheet` – `data`, `context` → analysis.
- **Analyze document**: `POST /api/ai/analyze-document` – `content`, `title` → analysis.
- **Analyze rate sheet**: `POST /api/ai/analyze-rate-sheet` – `parsed_data`, `file_name`, `existing_rate_sheets?`, `prompt?` → structured RateSheet (routes, pricing_tiers, surcharges, validity, carrier_name). Used by Rate Sheet Service during upload.

---

### 5.10 Admin Processes

- **Admin dashboard**: `GET /api/auth/admin` (Bearer, staff/superuser) → Auth aggregates counts (users, orgs) and returns dashboard payload.
- **Admin users**: List/create/update/delete users via `GET/POST/PATCH/DELETE /api/auth/admin/users`; Auth reads/writes **PostgreSQL users**.
- **Admin schema**: `GET /api/auth/admin/schema` → introspects Auth DB and returns schema description; may also describe User/Rate Sheet/Email/Vector models from config.
- **Admin ChromaDB**: `GET /api/auth/admin/chromadb` → Auth calls Vector DB to list collections and sample documents for debugging.
- **Admin emails**: `GET /api/email/admin/all`, `GET /api/email/admin/stats` – Email Service queries Vector DB without user_id filter; returns all emails or stats (staff/superuser only).
- **Admin rate sheets**: `GET /api/rate-sheets/admin/all`, `GET /api/rate-sheets/admin/stats` – Rate Sheet Service queries Vector DB without organization filter; returns all rate sheets or stats (staff/superuser only).

---

## 6. API Gateway Routing

| Path prefix           | Target service   | Port |
|-----------------------|------------------|------|
| /api/auth/*           | Authentication   | 8001 |
| /api/constants/*      | Constants       | 8002 |
| /api/ai/*             | AI Service      | 8003 |
| /api/vector/*         | Vector DB       | 8004 |
| /api/email/*          | Email Service   | 8005 |
| /api/user/*           | User Service    | 8006 |
| /api/rate-sheets, /api/rate-sheets/* | Rate Sheet Service | 8010 |

Special behavior:

- **Root (GET/POST /)**  
  If body looks like Pub/Sub (e.g. `message`, `subscription`), gateway forwards to `AUTH_SERVICE_URL/api/auth/gmail/webhook` so webhook still works if subscription points at `/`.
- **Timeouts**  
  Webhook and upload routes use longer timeouts (e.g. 180s webhook, 600s upload) via shared constants.

---

## 7. Multi-Tenancy and Isolation

- **Organizations (User Service)**  
  Organizations own rate sheets and settings. Users are linked via `user_organizations` and roles.

- **Rate sheets**  
  Always scoped by **organization_id**. Stored in PostgreSQL (`rate_sheet_structured_data`, routes, pricing_tiers, surcharges) and in Vector DB collection `rate_sheets` with `organization_id` in metadata. List/search filter by organization.

- **Emails**  
  Always scoped by **user_id**. Stored only in Vector DB collection `emails` with `user_id` in metadata. Users only see their own emails; no org-wide email sharing.

- **Admin**  
  Auth and some services expose admin endpoints (e.g. list all users, all organizations, all emails, all rate sheets) guarded by `is_staff` / `is_superuser` (JWT/token validation).

---

## 8. Configuration and Deployment

- **Environment**  
  Central `.env` in `microservices/`; services read DB URLs, service URLs, JWT secret, Google OAuth, Gmail Pub/Sub topic, webhook URL, OpenAI key, etc.

- **Docker Compose**  
  `docker-compose.yml` defines:
  - postgres (with init script for multiple DBs), chromadb, arangodb
  - All application services and api_gateway
  - Volumes: postgres_data, chroma_data, arango_data, vector_db_data, rate_sheet_uploads
  - Network: freight_network

- **Service discovery**  
  Service-to-service calls use fixed hostnames (e.g. `http://authentication:8001`, `http://rate_sheet_service:8010`) and env vars for URLs.

---

## 9. File Layout (Summary)

```
microservices/
├── api_gateway/          # Proxy and CORS
├── authentication/       # Auth, OAuth, Gmail webhook, admin
├── constants/            # Static constants/FAQs
├── ai_service/           # OpenAI integration
├── vector_db/            # ChromaDB-like + BGE (pickle)
├── email_service/        # Email CRUD + Vector DB + draft trigger
├── user_service/        # Orgs, profiles, roles, invitations
├── rate_sheet_service/  # Upload, pipeline, PG + Chroma + graph, draft/send
├── knowledge_graph_service/  # ArangoDB graph
├── intent_classifier_service/
├── orchestrator_service/
├── decision_engine/
├── shared/               # constants, logging, error_handlers
├── docker-compose.yml
├── init-multiple-dbs.sh
└── .env
```

---

This architecture document reflects the implementation as of the current codebase. For runbooks and API details, see `README.md` and each service’s routes and config.
