from fastapi import APIRouter, Header, HTTPException, status, Request, Response, Query
from fastapi.responses import RedirectResponse
from typing import Optional
import uuid
import json
from ..schemas import (
    AuthResponse,
    LoginRequest,
    SignupRequest,
    GoogleCredentialRequest,
    LogoutResponse,
    AdminDashboardResponse,
    AdminUsersResponse,
    AdminUserCreate,
    AdminUserUpdate,
    AdminUserOut,
)
from ..services.auth_service import auth_service


router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=AuthResponse)
async def login(payload: LoginRequest):
    return await auth_service.login(payload)


@router.post("/signup", response_model=AuthResponse)
async def signup(payload: SignupRequest):
    return await auth_service.signup(payload)


@router.get("/google")
def google_oauth_initiate(request: Request):
    """Initiate Google OAuth flow - redirects to Google"""
    return auth_service.initiate_google_oauth(request)


@router.get("/google/callback")
async def google_oauth_callback(request: Request):
    """Handle Google OAuth callback - receives code and exchanges for token"""
    return await auth_service.handle_google_callback(request)


@router.post("/google/verify", response_model=AuthResponse)
async def google_verify(payload: GoogleCredentialRequest):
    return await auth_service.verify_google(payload)


@router.get("/me", response_model=AuthResponse)
async def me(authorization: str = Header(default="")):
    if not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Authorization header missing or invalid",
        )
    token = authorization.replace("Bearer ", "")
    return await auth_service.get_current_user(token)


@router.post("/logout", response_model=LogoutResponse)
def logout():
    return auth_service.logout()


@router.get("/admin", response_model=AdminDashboardResponse)
async def admin_dashboard(authorization: str = Header(default="")):
    """Admin dashboard data"""
    if not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Authorization header missing or invalid",
        )
    token = authorization.replace("Bearer ", "")
    return await auth_service.get_admin_dashboard(token)


@router.get("/admin/users", response_model=AdminUsersResponse)
async def admin_list_users(
    authorization: str = Header(default=""),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    search: Optional[str] = Query(default=None),
):
    if not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Authorization header missing or invalid",
        )
    token = authorization.replace("Bearer ", "")
    return await auth_service.list_admin_users(token, limit=limit, offset=offset, search=search)


@router.post("/admin/users", response_model=AdminUserOut)
async def admin_create_user(
    payload: AdminUserCreate,
    authorization: str = Header(default=""),
):
    if not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Authorization header missing or invalid",
        )
    token = authorization.replace("Bearer ", "")
    return await auth_service.create_admin_user(token, payload)


@router.patch("/admin/users/{user_id}", response_model=AdminUserOut)
async def admin_update_user(
    user_id: int,
    payload: AdminUserUpdate,
    authorization: str = Header(default=""),
):
    if not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Authorization header missing or invalid",
        )
    token = authorization.replace("Bearer ", "")
    return await auth_service.update_admin_user(token, user_id, payload)


@router.delete("/admin/users/{user_id}")
async def admin_delete_user(
    user_id: int,
    authorization: str = Header(default=""),
):
    if not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Authorization header missing or invalid",
        )
    token = authorization.replace("Bearer ", "")
    return await auth_service.delete_admin_user(token, user_id)


@router.get("/admin/schema")
async def admin_get_schema(
    authorization: str = Header(default=""),
):
    """
    Admin endpoint: Get database schema information (models and relationships)
    For developers to understand the data model structure
    """
    if not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Authorization header missing or invalid",
        )
    token = authorization.replace("Bearer ", "")
    
    # Verify admin access
    try:
        from ..core.database import AsyncSessionLocal
        async with AsyncSessionLocal() as session:
            await auth_service._get_admin_user(session, token)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    
    # Dynamically introspect SQLAlchemy models
    from sqlalchemy import inspect as sqlalchemy_inspect
    from ..models.user import User
    
    def get_model_info(model_class):
        """Introspect a SQLAlchemy model to get schema information dynamically"""
        try:
            mapper = sqlalchemy_inspect(model_class)
            table = mapper.tables[0] if mapper.tables else None
            
            if not table:
                return None
            
            fields = []
            for column in table.columns:
                col_info = {
                    "name": column.name,
                    "type": str(column.type),
                    "primary_key": column.primary_key,
                    "unique": column.unique,
                    "indexed": column.index,
                    "nullable": column.nullable,
                }
                
                # Get default value
                if column.default is not None:
                    if hasattr(column.default, 'arg'):
                        col_info["default"] = str(column.default.arg)
                    elif hasattr(column.default, 'value'):
                        col_info["default"] = str(column.default.value)
                    else:
                        col_info["default"] = None
                else:
                    col_info["default"] = None
                
                # Get docstring or description from column comment if available
                if hasattr(column, 'comment') and column.comment:
                    col_info["description"] = column.comment
                else:
                    col_info["description"] = None
                
                fields.append(col_info)
            
            # Get relationships
            relationships = []
            for rel_name, rel in mapper.relationships.items():
                rel_info = {
                    "name": rel_name,
                    "type": "many-to-one" if rel.direction.name == "MANYTOONE" else "one-to-many" if rel.direction.name == "ONETOMANY" else "many-to-many",
                    "target": rel.entity.class_.__name__ if hasattr(rel.entity, 'class_') else str(rel.entity),
                    "description": f"Relationship: {rel_name}"
                }
                relationships.append(rel_info)
            
            # Get constraints
            constraints = []
            for constraint in table.constraints:
                if constraint.name and constraint.name.startswith('uq_'):
                    constraints.append({
                        "type": "unique",
                        "name": constraint.name,
                        "fields": [col.name for col in constraint.columns] if hasattr(constraint, 'columns') else [],
                        "description": f"Unique constraint: {constraint.name}"
                    })
            
            return {
                "name": model_class.__name__,
                "table": table.name,
                "description": model_class.__doc__.strip() if model_class.__doc__ else f"{model_class.__name__} model",
                "fields": fields,
                "relationships": relationships,
                "constraints": constraints,
            }
        except Exception as e:
            # Log error but don't fail - fallback to static
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"Failed to introspect model {model_class.__name__}: {e}")
            return None
    
    # Get authentication service models dynamically
    auth_models = []
    try:
        user_info = get_model_info(User)
        if user_info:
            auth_models.append(user_info)
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.warning(f"Failed to introspect User model: {e}")
        auth_models = []  # Will use static fallback
    
    # Define schema information (with dynamic introspection where possible)
    schema_info = {
        "services": {
            "authentication": {
                "database": "PostgreSQL",
                "models": auth_models if auth_models else [
                    {
                        "name": "User",
                        "table": "users",
                        "description": "User authentication and Google OAuth data",
                        "fields": [
                            {"name": "id", "type": "Integer", "primary_key": True, "description": "Primary key"},
                            {"name": "email", "type": "String(255)", "unique": True, "indexed": True, "description": "User email address"},
                            {"name": "username", "type": "String(150)", "unique": True, "indexed": True, "description": "Username"},
                            {"name": "password_hash", "type": "String(255)", "nullable": True, "description": "Bcrypt password hash (nullable for Google OAuth users)"},
                            {"name": "first_name", "type": "String(150)", "nullable": True},
                            {"name": "last_name", "type": "String(150)", "nullable": True},
                            {"name": "google_id", "type": "String(255)", "unique": True, "nullable": True, "description": "Google OAuth user ID"},
                            {"name": "is_google_user", "type": "Boolean", "default": False, "description": "True if user signed up via Google OAuth"},
                            {"name": "google_access_token", "type": "Text", "nullable": True, "description": "Google OAuth access token"},
                            {"name": "google_refresh_token", "type": "Text", "nullable": True, "description": "Google OAuth refresh token"},
                            {"name": "gmail_connected", "type": "Boolean", "default": False, "description": "Gmail integration status"},
                            {"name": "drive_connected", "type": "Boolean", "default": False, "description": "Google Drive integration status"},
                            {"name": "is_active", "type": "Boolean", "default": True, "description": "Account active status"},
                            {"name": "is_staff", "type": "Boolean", "default": False, "description": "Staff/admin access"},
                            {"name": "is_superuser", "type": "Boolean", "default": False, "description": "Superuser access"},
                            {"name": "created_at", "type": "DateTime(timezone=True)", "description": "Account creation timestamp"},
                            {"name": "updated_at", "type": "DateTime(timezone=True)", "description": "Last update timestamp"},
                            {"name": "last_login", "type": "DateTime(timezone=True)", "nullable": True, "description": "Last login timestamp"},
                        ],
                        "relationships": [],
                        "notes": "Core user authentication model. Links to UserProfile in user_service via auth_user_id."
                    }
                ],
                "introspection_status": "dynamic" if auth_models else "static_fallback"
            },
            "user_service": {
                "database": "PostgreSQL",
                "models": [
                    {
                        "name": "UserProfile",
                        "table": "user_profiles",
                        "description": "Extended user profile linked to auth service User",
                        "fields": [
                            {"name": "id", "type": "Integer", "primary_key": True},
                            {"name": "auth_user_id", "type": "Integer", "unique": True, "indexed": True, "description": "Foreign key to authentication.users.id"},
                            {"name": "email", "type": "String(255)", "indexed": True, "description": "Denormalized email for quick access"},
                            {"name": "first_name", "type": "String(150)", "nullable": True},
                            {"name": "last_name", "type": "String(150)", "nullable": True},
                            {"name": "department", "type": "Enum", "nullable": True, "values": ["ops", "sales", "admin"]},
                            {"name": "signature", "type": "Text", "nullable": True, "description": "Email footer signature"},
                            {"name": "is_enabled", "type": "Boolean", "default": True, "description": "Enable/disable user"},
                            {"name": "deleted_at", "type": "DateTime(timezone=True)", "nullable": True, "description": "Soft delete timestamp"},
                        ],
                        "relationships": [
                            {"type": "one-to-many", "target": "UserOrganization", "description": "User can belong to multiple organizations"}
                        ]
                    },
                    {
                        "name": "Organization",
                        "table": "organizations",
                        "description": "Company/Organization model for multi-tenant isolation",
                        "fields": [
                            {"name": "id", "type": "Integer", "primary_key": True},
                            {"name": "name", "type": "String(255)", "indexed": True},
                            {"name": "slug", "type": "String(255)", "unique": True, "indexed": True, "description": "URL-friendly identifier"},
                            {"name": "domain", "type": "String(255)", "indexed": True, "description": "Company domain (required)"},
                            {"name": "admin_email", "type": "String(255)", "indexed": True, "description": "Organization admin email"},
                            {"name": "industry_type", "type": "Enum", "nullable": True, "values": ["freight_forwarder", "cha", "exporter"]},
                            {"name": "timezone", "type": "String(100)", "default": "UTC"},
                            {"name": "default_currency", "type": "String(10)", "default": "USD"},
                            {"name": "status", "type": "Enum", "default": "active", "values": ["active", "suspended"]},
                            {"name": "emails_per_day_limit", "type": "Integer", "nullable": True, "description": "Daily email limit"},
                            {"name": "ai_usage_limit", "type": "Integer", "nullable": True, "description": "AI API calls per day"},
                            {"name": "auto_send_threshold", "type": "Integer", "default": 95, "description": "Confidence threshold for auto-send"},
                            {"name": "manual_review_threshold", "type": "Integer", "default": 70, "description": "Confidence threshold for manual review"},
                        ],
                        "relationships": [
                            {"type": "one-to-many", "target": "UserOrganization", "description": "Organization has many users"},
                            {"type": "one-to-many", "target": "Invitation", "description": "Organization has many invitations"}
                        ]
                    },
                    {
                        "name": "UserOrganization",
                        "table": "user_organizations",
                        "description": "Many-to-many relationship between UserProfile and Organization with Role",
                        "fields": [
                            {"name": "id", "type": "Integer", "primary_key": True},
                            {"name": "user_profile_id", "type": "Integer", "foreign_key": "user_profiles.id", "indexed": True},
                            {"name": "organization_id", "type": "Integer", "foreign_key": "organizations.id", "indexed": True},
                            {"name": "role_id", "type": "Integer", "foreign_key": "roles.id", "indexed": True},
                            {"name": "is_active", "type": "Boolean", "default": True},
                            {"name": "joined_at", "type": "DateTime(timezone=True)", "description": "When user joined organization"},
                        ],
                        "relationships": [
                            {"type": "many-to-one", "target": "UserProfile", "description": "Belongs to UserProfile"},
                            {"type": "many-to-one", "target": "Organization", "description": "Belongs to Organization"},
                            {"type": "many-to-one", "target": "Role", "description": "Has a Role"}
                        ],
                        "constraints": [
                            {"type": "unique", "fields": ["user_profile_id", "organization_id"], "description": "One user can only have one role per organization"}
                        ]
                    },
                    {
                        "name": "Role",
                        "table": "roles",
                        "description": "Role model - admin, employee, manager",
                        "fields": [
                            {"name": "id", "type": "Integer", "primary_key": True},
                            {"name": "name", "type": "String(100)", "unique": True, "indexed": True, "description": "admin, employee, manager"},
                            {"name": "display_name", "type": "String(150)", "description": "Admin, Employee, Manager"},
                            {"name": "description", "type": "Text", "nullable": True},
                        ],
                        "relationships": [
                            {"type": "one-to-many", "target": "UserOrganization", "description": "Role assigned to users in organizations"},
                            {"type": "one-to-many", "target": "RolePermission", "description": "Role has permissions"}
                        ]
                    },
                    {
                        "name": "Invitation",
                        "table": "invitations",
                        "description": "Invitation model for inviting users to organizations",
                        "fields": [
                            {"name": "id", "type": "Integer", "primary_key": True},
                            {"name": "organization_id", "type": "Integer", "foreign_key": "organizations.id", "indexed": True},
                            {"name": "invited_by_user_id", "type": "Integer", "indexed": True, "description": "UserProfile ID who sent invitation"},
                            {"name": "email", "type": "String(255)", "indexed": True, "description": "Invited email address"},
                            {"name": "token", "type": "String(255)", "unique": True, "indexed": True, "description": "Unique invitation token"},
                            {"name": "role_id", "type": "Integer", "foreign_key": "roles.id", "description": "Role to assign when accepted"},
                            {"name": "is_accepted", "type": "Boolean", "default": False, "indexed": True},
                            {"name": "expires_at", "type": "DateTime(timezone=True)", "indexed": True, "description": "Invitation expiry"},
                        ],
                        "relationships": [
                            {"type": "many-to-one", "target": "Organization", "description": "Belongs to Organization"},
                            {"type": "many-to-one", "target": "Role", "description": "Has a Role"}
                        ]
                    }
                ],
                "notes": "Multi-tenant SaaS model. Organizations isolate data. UserProfile links to authentication.users via auth_user_id."
            },
            "rate_sheet_service": {
                "database": "PostgreSQL",
                "models": [
                    {
                        "name": "RateSheetStructuredData",
                        "table": "rate_sheet_structured_data",
                        "description": "Structured rate sheet data for precise querying (complements ChromaDB)",
                        "fields": [
                            {"name": "rate_sheet_id", "type": "String(36)", "primary_key": True, "description": "Links to ChromaDB document ID"},
                            {"name": "organization_id", "type": "Integer", "indexed": True, "description": "Multi-tenant isolation"},
                            {"name": "user_id", "type": "Integer", "description": "User who uploaded"},
                            {"name": "file_name", "type": "String(500)", "description": "Original file name"},
                            {"name": "carrier_name", "type": "String(255)", "indexed": True, "nullable": True},
                            {"name": "rate_sheet_type", "type": "String(50)", "nullable": True, "description": "ocean_freight, air_freight, etc."},
                            {"name": "routes", "type": "JSON", "description": "Array of route objects"},
                            {"name": "pricing_tiers", "type": "JSON", "nullable": True, "description": "Array of pricing tier objects"},
                            {"name": "surcharges", "type": "JSON", "nullable": True, "description": "Array of surcharge objects"},
                            {"name": "valid_from", "type": "DateTime(timezone=True)", "indexed": True, "nullable": True},
                            {"name": "valid_to", "type": "DateTime(timezone=True)", "indexed": True, "nullable": True},
                        ],
                        "relationships": [],
                        "notes": "Hybrid storage: ChromaDB (semantic search) + PostgreSQL (structured queries). rate_sheet_id links to ChromaDB document."
                    }
                ]
            },
            "email_service": {
                "database": "ChromaDB (Vector DB)",
                "models": [
                    {
                        "name": "Email",
                        "collection": "emails",
                        "description": "Email model stored in ChromaDB with BGE embeddings",
                        "storage": {
                            "type": "Vector Database (ChromaDB)",
                            "embedding_model": "BAAI/bge-base-en-v1.5",
                            "storage_format": "Pickle files (.pkl) in vector_db directory"
                        },
                        "fields": [
                            {"name": "id", "type": "String (UUID)", "description": "ChromaDB document ID"},
                            {"name": "user_id", "type": "Integer", "description": "Reference to authentication.users.id"},
                            {"name": "gmail_message_id", "type": "String", "description": "Gmail API message ID"},
                            {"name": "gmail_thread_id", "type": "String", "nullable": True, "description": "Gmail thread ID"},
                            {"name": "subject", "type": "String", "nullable": True},
                            {"name": "from_email", "type": "String", "nullable": True},
                            {"name": "to_email", "type": "String", "nullable": True},
                            {"name": "body_html", "type": "String", "nullable": True, "description": "Full HTML email body"},
                            {"name": "body_plain", "type": "String", "nullable": True, "description": "Plain text email body"},
                            {"name": "snippet", "type": "String", "nullable": True, "description": "Email preview snippet"},
                            {"name": "is_read", "type": "Boolean", "default": False},
                            {"name": "is_processed", "type": "Boolean", "default": False, "description": "AI processing status"},
                            {"name": "is_rate_sheet", "type": "Boolean", "default": False, "description": "Detected as rate sheet"},
                            {"name": "drafted_response", "type": "JSON", "nullable": True, "description": "Auto-drafted AI response"},
                        ],
                        "relationships": [
                            {"type": "many-to-one", "target": "User (auth service)", "description": "Emails belong to users (user-level privacy)"}
                        ],
                        "notes": "Emails are USER-SPECIFIC and PRIVATE. Unlike rate sheets (org-wide), emails are NOT shared within organizations."
                    }
                ]
            },
            "rate_sheet_service_vector": {
                "database": "ChromaDB (Vector DB)",
                "models": [
                    {
                        "name": "RateSheet",
                        "collection": "rate_sheets",
                        "description": "Rate sheet documents stored in ChromaDB with BGE embeddings",
                        "storage": {
                            "type": "Vector Database (ChromaDB)",
                            "embedding_model": "BAAI/bge-base-en-v1.5",
                            "storage_format": "Pickle files (.pkl) in vector_db directory"
                        },
                        "fields": [
                            {"name": "id", "type": "String (UUID)", "description": "ChromaDB document ID"},
                            {"name": "organization_id", "type": "Integer", "description": "Multi-tenant isolation (REQUIRED)"},
                            {"name": "user_id", "type": "Integer", "description": "User who uploaded"},
                            {"name": "file_name", "type": "String", "description": "Original file name"},
                            {"name": "carrier_name", "type": "String", "nullable": True},
                            {"name": "document", "type": "String", "description": "Full raw rate sheet content"},
                            {"name": "metadata", "type": "JSON", "description": "Structured metadata (carrier, routes, etc.)"},
                        ],
                        "relationships": [
                            {"type": "many-to-one", "target": "Organization (user service)", "description": "Rate sheets belong to organizations (org-level isolation)"}
                        ],
                        "notes": "Rate sheets are ORGANIZATION-WIDE. Users within an organization can see ALL rate sheets from their organization."
                    }
                ]
            }
        },
        "data_isolation": {
            "emails": {
                "level": "user",
                "description": "Emails are user-private. Users can only see their own emails, even within the same organization."
            },
            "rate_sheets": {
                "level": "organization",
                "description": "Rate sheets are organization-wide. Users within an organization share access to all rate sheets."
            }
        },
        "architecture_notes": [
            "Authentication Service: Manages user authentication, Google OAuth, and Gmail webhooks",
            "User Service: Manages organizations, user profiles, roles, and permissions (multi-tenant SaaS)",
            "Email Service: Stores emails in ChromaDB with semantic search capabilities",
            "Rate Sheet Service: Hybrid storage - ChromaDB for semantic search, PostgreSQL for structured queries",
            "Vector DB Service: Provides ChromaDB functionality using Sentence Transformers (BGE model)",
            "AI Service: Provides OpenAI GPT-4o-mini for re-ranking and email drafting",
            "Data flows: Gmail Webhook → Auth Service → Email Service → Vector DB → ChromaDB",
            "Rate Sheet Upload → Rate Sheet Service → ChromaDB (embeddings) + PostgreSQL (structured data)"
        ],
        "introspection_info": {
            "authentication_service": "dynamic" if auth_models else "static_fallback",
            "note": "Schema is automatically generated from SQLAlchemy models. Changes to models will be reflected automatically."
        }
    }
    
    return schema_info


@router.get("/admin/chromadb")
async def admin_get_chromadb_info(
    authorization: str = Header(default=""),
    collection: Optional[str] = Query(None, description="Specific collection name (emails, rate_sheets)"),
    sample_size: int = Query(default=5, ge=1, le=50, description="Number of sample documents to return"),
):
    """
    Admin endpoint: Get ChromaDB collection structure and sample data
    For developers to understand how data is stored in ChromaDB
    """
    if not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Authorization header missing or invalid",
        )
    token = authorization.replace("Bearer ", "")
    
    # Verify admin access
    try:
        from ..core.database import AsyncSessionLocal
        async with AsyncSessionLocal() as session:
            await auth_service._get_admin_user(session, token)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    
    import httpx
    from ..core.config import settings
    
    # Vector DB service URL (default if not in config)
    vector_db_url = getattr(settings, 'VECTOR_DB_SERVICE_URL', 'http://localhost:8004')
    
    collections_to_check = [collection] if collection else ["emails", "rate_sheets"]
    chromadb_info = {}
    
    async with httpx.AsyncClient() as client:
        for coll_name in collections_to_check:
            try:
                # Get collection info
                info_response = await client.get(
                    f"{vector_db_url}/api/vector/collections/{coll_name}",
                    timeout=10.0
                )
                
                collection_info = {}
                if info_response.status_code == 200:
                    info_data = info_response.json()
                    collection_info = {
                        "exists": True,
                        "count": info_data.get("count", 0),
                        "name": coll_name,
                    }
                    
                    # Get sample documents
                    if info_data.get("count", 0) > 0:
                        sample_response = await client.post(
                            f"{vector_db_url}/api/vector/collections/{coll_name}/query",
                            json={
                                "query_texts": ["sample"],
                                "n_results": min(sample_size, info_data.get("count", 0))
                            },
                            timeout=30.0
                        )
                        
                        if sample_response.status_code == 200:
                            sample_data = sample_response.json()
                            results = sample_data.get("results", {})
                            ids = results.get("ids", [[]])[0]
                            metadatas = results.get("metadatas", [[]])[0]
                            documents = results.get("documents", [[]])[0]
                            
                            samples = []
                            for i in range(min(len(ids), sample_size)):
                                sample_doc = {
                                    "id": ids[i],
                                    "metadata": metadatas[i] if i < len(metadatas) else {},
                                    "document_preview": (documents[i][:500] if documents and i < len(documents) else "") + ("..." if documents and i < len(documents) and len(documents[i]) > 500 else ""),
                                    "document_length": len(documents[i]) if documents and i < len(documents) else 0,
                                }
                                samples.append(sample_doc)
                            
                            collection_info["samples"] = samples
                            collection_info["sample_count"] = len(samples)
                else:
                    collection_info = {
                        "exists": False,
                        "name": coll_name,
                        "error": f"Collection not found or error: {info_response.status_code}"
                    }
                
                chromadb_info[coll_name] = collection_info
                
            except Exception as e:
                chromadb_info[coll_name] = {
                    "exists": False,
                    "name": coll_name,
                    "error": str(e)
                }
    
    return {
        "chromadb_info": chromadb_info,
        "storage_location": vector_db_url,
        "embedding_model": "BAAI/bge-base-en-v1.5",
        "storage_format": "Pickle files (.pkl) in vector_db directory",
        "notes": [
            "ChromaDB collections are stored as pickle files (.pkl) in the vector_db directory",
            "Each collection contains: documents (text), metadatas (JSON), ids (UUIDs), and embeddings (numpy arrays)",
            "Embeddings are generated using BGE (BAAI/bge-base-en-v1.5) model for semantic search",
            "emails collection: User-private emails with full content and metadata",
            "rate_sheets collection: Organization-wide rate sheets with full document content and metadata"
        ]
    }


# ========== GMAIL API ENDPOINTS ==========

@router.get("/gmail/list")
async def gmail_list(
    authorization: str = Header(default=""),
    max_results: int = Query(default=20, ge=1, le=100),
    page_token: Optional[str] = Query(default=None)
):
    """Get list of Gmail messages with pagination"""
    if not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Authorization header missing or invalid",
        )
    token = authorization.replace("Bearer ", "")
    
    try:
        import asyncio
        from ..utils.google_api import get_user_from_token
        from ..services.gmail_service import list_emails
        
        user = await get_user_from_token(token)
        
        if not user.google_access_token:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Google OAuth tokens not found. Please log in with Google.",
            )
        
        result = await asyncio.wait_for(
            list_emails(user, max_results, page_token),
            timeout=60,
        )
        return result
        
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
        )
    except asyncio.TimeoutError:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="Gmail list request timed out. Please try again.",
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch emails: {str(e)}",
        )


@router.get("/gmail/detail")
async def gmail_detail(
    authorization: str = Header(default=""),
    message_id: Optional[str] = Query(default=None)
):
    """Get Gmail message details"""
    if not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Authorization header missing or invalid",
        )
    
    if not message_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing required parameter: message_id",
        )
    
    token = authorization.replace("Bearer ", "")
    
    try:
        import asyncio
        from ..utils.google_api import get_user_from_token
        from ..services.gmail_service import get_email_detail
        
        user = await get_user_from_token(token)
        
        if not user.google_access_token:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Google OAuth tokens not found. Please log in with Google.",
            )
        
        result = await asyncio.wait_for(
            get_email_detail(user, message_id),
            timeout=60,
        )
        return result
        
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
        )
    except asyncio.TimeoutError:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="Gmail detail request timed out. Please try again.",
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch email details: {str(e)}",
        )


@router.get("/gmail/attachment")
async def gmail_attachment(
    authorization: str = Header(default=""),
    message_id: Optional[str] = Query(default=None),
    attachment_id: Optional[str] = Query(default=None),
    filename: Optional[str] = Query(default=None)
):
    """Download Gmail attachment"""
    if not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Authorization header missing or invalid",
        )
    
    if not message_id or not attachment_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing required parameters: message_id, attachment_id",
        )
    
    token = authorization.replace("Bearer ", "")
    
    try:
        from ..utils.google_api import get_user_from_token
        from ..services.gmail_service import download_attachment
        from fastapi.responses import Response
        
        user = await get_user_from_token(token)
        
        if not user.google_access_token:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Google OAuth tokens not found. Please log in with Google.",
            )
        
        file_data = await download_attachment(user, message_id, attachment_id)
        
        return Response(
            content=file_data,
            media_type="application/octet-stream",
            headers={
                "Content-Disposition": f'attachment; filename="{filename or "attachment"}"'
            }
        )
        
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to download attachment: {str(e)}",
        )


@router.post("/gmail/send")
async def gmail_send(
    authorization: str = Header(default=""),
    request: Request = None
):
    """Send email via Gmail"""
    if not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Authorization header missing or invalid",
        )
    
    token = authorization.replace("Bearer ", "")
    
    try:
        from ..utils.google_api import get_user_from_token
        from ..services.gmail_service import send_email
        import json
        
        body_data = await request.json()
        to = body_data.get('to')
        subject = body_data.get('subject')
        body = body_data.get('body')
        include_signature = body_data.get('include_signature', True)
        
        if not to or not subject or not body:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Missing required fields: to, subject, body",
            )
        
        user = await get_user_from_token(token)
        
        if not user.google_access_token:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Google OAuth tokens not found. Please log in with Google.",
            )
        
        result = await send_email(user, to, subject, body, include_signature, token)
        return result
        
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to send email: {str(e)}",
        )


# ========== GOOGLE DRIVE API ENDPOINTS ==========

@router.get("/drive/list")
async def drive_list(
    authorization: str = Header(default=""),
    max_results: int = Query(default=50, ge=1, le=100),
    page_token: Optional[str] = Query(default=None),
    mime_type: Optional[str] = Query(default=None)
):
    """List Google Drive files"""
    if not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Authorization header missing or invalid",
        )
    
    token = authorization.replace("Bearer ", "")
    
    try:
        import asyncio
        from ..utils.google_api import get_user_from_token
        from ..services.drive_service import list_drive_files
        
        user = await get_user_from_token(token)
        
        if not user.google_access_token:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Google OAuth tokens not found. Please log in with Google.",
            )
        
        result = await asyncio.wait_for(
            list_drive_files(user, max_results, page_token, mime_type),
            timeout=25,
        )
        return result
        
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
        )
    except HTTPException:
        raise
    except asyncio.TimeoutError:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="Drive list request timed out. Please try again.",
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list Drive files: {str(e)}",
        )


# ========== AI API ENDPOINTS ==========

@router.get("/ai/status")
async def ai_status(authorization: str = Header(default="")):
    """Check if AI service is available"""
    if not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Authorization header missing or invalid",
        )
    
    from ..services.ai_service import is_ai_available
    return {'available': is_ai_available()}


@router.post("/ai/chat")
async def ai_chat(authorization: str = Header(default=""), request: Request = None):
    """General AI chat endpoint"""
    if not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Authorization header missing or invalid",
        )
    
    try:
        from ..services.ai_service import is_ai_available, general_chat
        import json
        
        if not is_ai_available():
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="AI service is not configured. Please add OPENAI_API_KEY to environment variables.",
            )
        
        body_data = await request.json()
        message = body_data.get('message')
        conversation_history = body_data.get('conversation_history', [])
        
        if not message:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Missing required field: message",
            )
        
        response = general_chat(message, conversation_history)
        return {'response': response}
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to process chat request: {str(e)}",
        )


@router.post("/ai/analyze-email")
async def ai_analyze_email(authorization: str = Header(default=""), request: Request = None):
    """Analyze email with AI"""
    if not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Authorization header missing or invalid",
        )
    
    try:
        from ..services.ai_service import is_ai_available, analyze_email
        import json
        
        if not is_ai_available():
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="AI service is not configured",
            )
        
        body_data = await request.json()
        email_content = body_data.get('content', '')
        subject = body_data.get('subject', '')
        from_sender = body_data.get('from', '')
        
        if not email_content:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Missing required field: content",
            )
        
        analysis = analyze_email(email_content, subject, from_sender)
        return analysis
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to analyze email: {str(e)}",
        )


@router.post("/ai/generate-email-response")
async def ai_generate_email_response(authorization: str = Header(default=""), request: Request = None):
    """Generate email response with AI"""
    if not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Authorization header missing or invalid",
        )
    
    try:
        from ..services.ai_service import is_ai_available, generate_email_response
        import json
        
        if not is_ai_available():
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="AI service is not configured",
            )
        
        body_data = await request.json()
        email_content = body_data.get('content', '')
        subject = body_data.get('subject', '')
        tone = body_data.get('tone', 'professional')
        
        if not email_content:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Missing required field: content",
            )
        
        response = generate_email_response(email_content, subject, tone)
        return {'response': response}
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate email response: {str(e)}",
        )


@router.post("/ai/analyze-spreadsheet")
async def ai_analyze_spreadsheet(authorization: str = Header(default=""), request: Request = None):
    """Analyze spreadsheet with AI"""
    if not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Authorization header missing or invalid",
        )
    
    try:
        from ..services.ai_service import is_ai_available, analyze_spreadsheet_data
        import json
        
        if not is_ai_available():
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="AI service is not configured",
            )
        
        body_data = await request.json()
        data = body_data.get('data', [])
        context = body_data.get('context', '')
        
        if not data:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Missing required field: data",
            )
        
        analysis = analyze_spreadsheet_data(data, context)
        return analysis
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to analyze spreadsheet: {str(e)}",
        )


@router.post("/ai/analyze-document")
async def ai_analyze_document(authorization: str = Header(default=""), request: Request = None):
    """Analyze document with AI"""
    if not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Authorization header missing or invalid",
        )
    
    try:
        from ..services.ai_service import is_ai_available, analyze_document
        import json
        
        if not is_ai_available():
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="AI service is not configured",
            )
        
        body_data = await request.json()
        content = body_data.get('content', '')
        title = body_data.get('title', '')
        
        if not content:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Missing required field: content",
            )
        
        analysis = analyze_document(content, title)
        return analysis
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to analyze document: {str(e)}",
        )


# ========== INTERNAL APIs FOR EMAIL SERVICE ==========
# These endpoints are for internal service-to-service communication

@router.get("/internal/gmail-users")
async def get_gmail_connected_users():
    """
    Internal API: Get all users with Gmail connected.
    Used by email service scheduler to know which users to check.
    """
    try:
        return await auth_service.get_gmail_connected_users()
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get Gmail users: {str(e)}",
        )


@router.get("/internal/gmail/{user_id}/list")
async def internal_gmail_list(
    user_id: int,
    max_results: int = Query(default=20, ge=1, le=100),
):
    """
    Internal API: Fetch Gmail messages for a user by user_id.
    Uses stored refresh token - no JWT required.
    """
    try:
        return await auth_service.fetch_gmail_for_user(user_id, max_results)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch Gmail: {str(e)}",
        )


@router.get("/internal/gmail/{user_id}/detail/{message_id}")
async def internal_gmail_detail(
    user_id: int,
    message_id: str,
):
    """
    Internal API: Get Gmail message detail for a user by user_id.
    Uses stored refresh token - no JWT required.
    """
    try:
        return await auth_service.get_gmail_detail_for_user(user_id, message_id)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get Gmail detail: {str(e)}",
        )


# ========== GMAIL WEBHOOK (PUB/SUB PUSH NOTIFICATIONS) ==========

@router.get("/gmail/webhook/test")
async def gmail_webhook_test():
    """Test endpoint to verify webhook endpoint is accessible"""
    import logging
    logger = logging.getLogger(__name__)
    logger.info("✅ Webhook test endpoint called - webhook endpoint is accessible!")
    return {
        "status": "ok",
        "message": "Webhook endpoint is accessible",
        "endpoint": "/api/auth/gmail/webhook",
        "note": "This confirms the endpoint is reachable. Use POST method for actual webhooks."
    }


@router.post("/gmail/webhook/test-manual")
async def gmail_webhook_test_manual(request: Request):
    """
    Manual test endpoint to simulate Pub/Sub webhook.
    Use this to test the webhook handler with a real payload format.
    
    Body should contain:
    {
        "email_address": "your-email@company.com",
        "history_id": "123456"
    }
    """
    import base64
    import json
    import logging
    
    logger = logging.getLogger(__name__)
    
    try:
        body_data = await request.json()
        email_address = body_data.get('email_address')
        history_id = body_data.get('history_id', '123456')
        
        if not email_address:
            return {
                "status": "error",
                "message": "Missing email_address in body"
            }
        
        # Create a Pub/Sub-like payload
        notification_data = {
            "emailAddress": email_address,
            "historyId": history_id
        }
        
        # Encode to base64 (like Pub/Sub does)
        import base64
        data_b64 = base64.b64encode(json.dumps(notification_data).encode()).decode()
        
        # Create Pub/Sub message format
        pubsub_payload = {
            "message": {
                "data": data_b64,
                "messageId": "test-manual-123",
                "publishTime": "2024-01-21T10:00:00Z"
            },
            "subscription": "projects/test/subscriptions/gmail-notifications-sub"
        }
        
        logger.info("🧪 Manual webhook test - simulating Pub/Sub payload")
        logger.info(f"Email: {email_address}, HistoryId: {history_id}")
        
        # Call the actual webhook handler
        await auth_service.handle_gmail_notification(email_address, history_id)
        
        return {
            "status": "ok",
            "message": "Manual webhook test completed",
            "email_address": email_address,
            "history_id": history_id,
            "note": "Check server logs for processing details"
        }
        
    except Exception as e:
        logger.error(f"Error in manual webhook test: {e}", exc_info=True)
        return {
            "status": "error",
            "message": str(e)
        }


@router.post("/gmail/webhook")
async def gmail_webhook(request: Request):
    """
    Webhook endpoint for Gmail push notifications via Pub/Sub.
    Called by Google when a user receives a new email.
    """
    import base64
    import json
    import httpx
    import logging
    
    logger = logging.getLogger(__name__)
    
    # Log webhook received with full details
    logger.info("=" * 80)
    logger.info("GMAIL WEBHOOK RECEIVED")
    logger.info(f"Request method: {request.method}")
    logger.info(f"Request URL: {request.url}")
    logger.info(f"Request headers: {dict(request.headers)}")
    
    try:
        body = await request.json()
        logger.info(f"Webhook body received: {json.dumps(body)[:500]}")
        
        # Extract the Pub/Sub message
        message = body.get('message', {})
        if not message:
            logger.warning("⚠️  No message in webhook payload")
            logger.warning(f"Full body: {json.dumps(body)}")
            return {"status": "ok", "message": "No message"}
        
        logger.info(f"Pub/Sub message extracted: {json.dumps(message)[:300]}")
        
        # Decode the data (base64 encoded)
        data_b64 = message.get('data', '')
        if not data_b64:
            logger.warning("⚠️  No data field in Pub/Sub message")
            return {"status": "ok", "message": "No data"}
        
        logger.info(f"Decoding base64 data (length: {len(data_b64)})")
        data = json.loads(base64.b64decode(data_b64).decode('utf-8'))
        email_address = data.get('emailAddress')
        history_id = data.get('historyId')
        
        logger.info(f"✅ Decoded notification - Email: {email_address}, HistoryId: {history_id}")
        
        if not email_address:
            logger.error("❌ No emailAddress in decoded data")
            return {"status": "ok", "message": "No email address"}
        
        if not history_id:
            logger.error("❌ No historyId in decoded data")
            return {"status": "ok", "message": "No history ID"}
        
        logger.info(f"🚀 Calling handle_gmail_notification for {email_address}")
        # Find user by email and trigger email fetch
        await auth_service.handle_gmail_notification(email_address, history_id)
        logger.info("✅ handle_gmail_notification completed")
        
        # Always return 200 to acknowledge receipt
        logger.info("=" * 80)
        return {"status": "ok"}
        
    except json.JSONDecodeError as e:
        # Log JSON decode error with context (no silent failure)
        error_id = str(uuid.uuid4())
        raw_body = await request.body()
        logger.error(
            f"[{error_id}] JSON decode error: {str(e)}",
            exc_info=True,
            extra={
                "error_id": error_id,
                "raw_body_preview": raw_body[:500] if raw_body else None,
                "exception_type": "JSONDecodeError"
            }
        )
        # Return 200 to prevent Pub/Sub retries (but log the error)
        return {"status": "error", "message": f"JSON decode error: {str(e)}", "error_id": error_id}
    except Exception as e:
        # Log webhook error with full context (no silent failure per BACKEND_REVIEW.md)
        error_id = str(uuid.uuid4())
        logger.error(
            f"[{error_id}] Gmail webhook error: {type(e).__name__}: {str(e)}",
            exc_info=True,
            extra={
                "error_id": error_id,
                "path": str(request.url.path),
                "method": request.method,
                "exception_type": type(e).__name__
            }
        )
        # Still return 200 to prevent Pub/Sub retries (but error is logged)
        logger.info("=" * 80)
        return {"status": "error", "message": str(e), "error_id": error_id}


@router.post("/gmail/watch/start")
async def start_gmail_watch(authorization: str = Header(default="")):
    """Start Gmail push notifications for the current user"""
    if not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Authorization header missing or invalid",
        )
    
    token = authorization.replace("Bearer ", "")
    
    try:
        return await auth_service.start_gmail_watch(token)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to start Gmail watch: {str(e)}",
        )


@router.post("/gmail/watch/stop")
async def stop_gmail_watch(authorization: str = Header(default="")):
    """Stop Gmail push notifications for the current user"""
    if not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Authorization header missing or invalid",
        )
    
    token = authorization.replace("Bearer ", "")
    
    try:
        return await auth_service.stop_gmail_watch(token)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to stop Gmail watch: {str(e)}",
        )


@router.post("/internal/gmail/watch/start-all")
async def start_gmail_watch_all_users():
    """
    Internal API: Start Gmail watch for all Gmail-connected users.
    Used to set up push notifications for everyone.
    """
    try:
        return await auth_service.start_gmail_watch_all_users()
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to start Gmail watch: {str(e)}",
        )
