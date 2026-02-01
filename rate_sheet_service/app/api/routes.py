from fastapi import APIRouter, Depends, UploadFile, File, HTTPException, Query, Request, Header, BackgroundTasks
from typing import List, Optional
import logging

from app.services.rate_sheet_service import RateSheetService
from app.services.email_response_service_v2 import EmailResponseServiceV2

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/rate-sheets", tags=["rate-sheets"])

"""
IMPORTANT: Multi-Tenant Data Isolation (B2B SaaS)

All endpoints enforce organization-level data isolation:
- Each organization has its own rate sheets
- Users within an organization can see ALL rate sheets from their organization
- Users from different organizations CANNOT see each other's rate sheets
- organization_id is REQUIRED for all operations

This ensures complete data separation between organizations (multi-tenant SaaS model).
"""


@router.post("/upload", status_code=201)
async def upload_rate_sheet(
    file: UploadFile = File(...),
    organization_id: int = Query(...),
    user_id: int = Query(...)
):
    """
    Upload and process a rate sheet file
    
    - **file**: Excel/CSV file (.xlsx, .xls, .csv)
    - **organization_id**: Organization ID
    - **user_id**: User ID who uploaded
    
    The file will be:
    1. Parsed to extract raw data
    2. Analyzed by AI to understand structure
    3. Stored in ChromaDB with BGE embeddings
    4. Relationships detected if applicable
    5. Ready for semantic search
    """
    # Validate file type
    allowed_extensions = ['.xlsx', '.xls', '.csv']
    file_ext = '.' + file.filename.split('.')[-1].lower() if '.' in file.filename else ''
    
    if file_ext not in allowed_extensions:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid file type. Allowed: {', '.join(allowed_extensions)}"
        )
    
    # Read file content
    try:
        file_content = await file.read()
        
        # Validate file size (50MB max)
        max_size = 50 * 1024 * 1024  # 50MB
        if len(file_content) > max_size:
            raise HTTPException(
                status_code=400,
                detail=f"File too large. Maximum size: 50MB"
            )
        
        # Process rate sheet (stores in ChromaDB with BGE embeddings)
        service = RateSheetService()
        rate_sheet = await service.upload_rate_sheet(
            file_content=file_content,
            file_name=file.filename,
            organization_id=organization_id,
            user_id=user_id
        )
        
        return rate_sheet
    
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        error_details = str(e) if str(e) else repr(e)
        logger.error(f"Error uploading rate sheet: {error_details}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error processing rate sheet: {error_details}")


@router.post("/upload-async", status_code=202)
async def upload_rate_sheet_async(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    organization_id: int = Query(...),
    user_id: int = Query(...)
):
    """
    Upload a rate sheet file asynchronously (non-blocking).
    
    Returns immediately with a rate_sheet_id and status='pending'.
    The file is processed in the background.
    
    Use GET /api/rate-sheets/{id}/status to poll for completion.
    
    - **file**: Excel/CSV file (.xlsx, .xls, .csv)
    - **organization_id**: Organization ID
    - **user_id**: User ID who uploaded
    
    Returns:
        - id: Rate sheet ID for polling
        - status: 'pending' (will change to 'processed' or 'failed')
        - message: Status message
    """
    # Validate file type
    allowed_extensions = ['.xlsx', '.xls', '.csv']
    file_ext = '.' + file.filename.split('.')[-1].lower() if '.' in file.filename else ''
    
    if file_ext not in allowed_extensions:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid file type. Allowed: {', '.join(allowed_extensions)}"
        )
    
    try:
        file_content = await file.read()
        
        # Validate file size (50MB max)
        max_size = 50 * 1024 * 1024
        if len(file_content) > max_size:
            raise HTTPException(
                status_code=400,
                detail=f"File too large. Maximum size: 50MB"
            )
        
        # Create pending record (fast, returns immediately)
        service = RateSheetService()
        result = await service.upload_rate_sheet(
            file_content=file_content,
            file_name=file.filename,
            organization_id=organization_id,
            user_id=user_id,
            async_mode=True  # Return immediately
        )
        
        # Queue background processing
        rate_sheet_id = result["id"]
        background_tasks.add_task(
            _process_rate_sheet_background,
            rate_sheet_id
        )
        
        logger.info(f"📋 Queued rate sheet {rate_sheet_id} for background processing")
        
        return result
    
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        error_details = str(e) if str(e) else repr(e)
        logger.error(f"Error uploading rate sheet (async): {error_details}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error uploading rate sheet: {error_details}")


@router.post("/upload-multiple", status_code=202)
async def upload_rate_sheets_multiple(
    background_tasks: BackgroundTasks,
    files: List[UploadFile] = File(..., description="One or more Excel/CSV files"),
    organization_id: int = Query(...),
    user_id: int = Query(...)
):
    """
    Upload multiple rate sheet files at once (async).
    
    Each file is validated, a pending record is created, and processing runs in the background.
    Poll GET /api/rate-sheets/{id}/status for each returned id to check completion.
    
    - **files**: One or more .xlsx, .xls, or .csv files (max 50MB each)
    - **organization_id**: Organization ID
    - **user_id**: User ID who uploaded
    
    Returns:
        - uploaded: List of { id, file_name, status, message? }
        - total: Number of files accepted
    """
    allowed_extensions = [".xlsx", ".xls", ".csv"]
    max_size = 50 * 1024 * 1024  # 50MB per file
    max_files = 20  # Limit concurrent uploads per request
    if len(files) == 0:
        raise HTTPException(status_code=400, detail="At least one file is required")
    if len(files) > max_files:
        raise HTTPException(
            status_code=400,
            detail=f"Maximum {max_files} files per request. Got {len(files)}."
        )
    results = []
    service = RateSheetService()
    for f in files:
        file_ext = "." + f.filename.split(".")[-1].lower() if "." in f.filename else ""
        if file_ext not in allowed_extensions:
            results.append({
                "id": None,
                "file_name": f.filename,
                "status": "rejected",
                "message": f"Invalid file type. Allowed: {', '.join(allowed_extensions)}"
            })
            continue
        try:
            file_content = await f.read()
            if len(file_content) > max_size:
                results.append({
                    "id": None,
                    "file_name": f.filename,
                    "status": "rejected",
                    "message": "File too large (max 50MB)"
                })
                continue
            result = await service.upload_rate_sheet(
                file_content=file_content,
                file_name=f.filename,
                organization_id=organization_id,
                user_id=user_id,
                async_mode=True,
            )
            rate_sheet_id = result["id"]
            background_tasks.add_task(_process_rate_sheet_background, rate_sheet_id)
            results.append({
                "id": rate_sheet_id,
                "file_name": f.filename,
                "status": result.get("status", "pending"),
                "message": result.get("message"),
            })
        except Exception as e:
            error_details = str(e) if str(e) else repr(e)
            logger.warning(f"Upload failed for {f.filename}: {error_details}")
            results.append({
                "id": None,
                "file_name": f.filename,
                "status": "failed",
                "message": error_details,
            })
    return {"uploaded": results, "total": len(results)}


async def _process_rate_sheet_background(rate_sheet_id: str):
    """Background task to process a rate sheet"""
    try:
        service = RateSheetService()
        await service.process_rate_sheet_background(rate_sheet_id)
    except Exception as e:
        import traceback
        error_details = str(e) if str(e) else repr(e)
        logger.error(f"Background processing failed for {rate_sheet_id}: {error_details}", exc_info=True)


@router.get("/{rate_sheet_id}/status")
async def get_rate_sheet_status(
    rate_sheet_id: str,
    organization_id: int = Query(...)
):
    """
    Get the processing status of a rate sheet.
    
    Use this endpoint to poll for completion after async upload.
    
    Returns:
        - id: Rate sheet ID
        - status: 'pending', 'processing', 'processed', or 'failed'
        - processing_error: Error message if status='failed'
        - carrier_name: Carrier name (if processed)
        - version: Version number
    """
    service = RateSheetService()
    status = await service.get_rate_sheet_status(rate_sheet_id, organization_id)
    
    if not status:
        raise HTTPException(status_code=404, detail="Rate sheet not found")
    
    return status


@router.get("/{rate_sheet_id}")
async def get_rate_sheet(
    rate_sheet_id: str,
    organization_id: int = Query(...)
):
    """Get rate sheet by ID from ChromaDB"""
    service = RateSheetService()
    rate_sheet = await service.get_rate_sheet(
        rate_sheet_id=rate_sheet_id,
        organization_id=organization_id
    )
    
    if not rate_sheet:
        raise HTTPException(status_code=404, detail="Rate sheet not found")
    
    return rate_sheet


@router.get("", summary="List/search rate sheets (no trailing slash)")
@router.get("/", summary="List/search rate sheets (with trailing slash)")
async def list_rate_sheets(
    organization_id: int = Query(..., description="Organization ID (REQUIRED for multi-tenant isolation)"),
    query: Optional[str] = Query(None, description="Natural language search query"),
    carrier_name: Optional[str] = Query(None, description="Filter by carrier name"),
    origin_code: Optional[str] = Query(None, description="Filter by origin port code"),
    destination_code: Optional[str] = Query(None, description="Filter by destination port code"),
    container_type: Optional[str] = Query(None, description="Filter by container type"),
    limit: int = Query(50, ge=1, le=100, description="Maximum number of results"),
    page: int = Query(1, ge=1, description="Page number")
):
    """
    Search and list rate sheets using semantic search (BGE embeddings)
    
    IMPORTANT: Returns ONLY rate sheets belonging to the specified organization_id.
    Users can only see rate sheets from their own organization (multi-tenant isolation).
    
    Supports:
    - Semantic search via query parameter (searches in ChromaDB)
    - Filter by carrier, origin, destination, container type
    - All results are automatically filtered by organization_id
    """
    service = RateSheetService()
    search_result = await service.search_rate_sheets(
        organization_id=organization_id,
        query=query,
        carrier_name=carrier_name,
        origin_code=origin_code,
        destination_code=destination_code,
        container_type=container_type,
        limit=limit
    )
    
    # Check if search_result is a dict with answer and results, or just a list
    if isinstance(search_result, dict) and "results" in search_result:
        # New format with answer (agentic: may include intent, engines_used, exact_rates, route_alternatives)
        rate_sheets = search_result.get("results", [])
        answer = search_result.get("answer", "")
        total_found = search_result.get("total_found", len(rate_sheets))
        total_returned = search_result.get("total_returned", len(rate_sheets))
    else:
        # Old format (list) - backward compatibility
        rate_sheets = search_result if isinstance(search_result, list) else []
        answer = ""
        total_found = len(rate_sheets)
        total_returned = len(rate_sheets)
    
    # Simple pagination (though we're already returning top N, pagination is minimal)
    start = (page - 1) * limit
    end = start + limit
    paginated_sheets = rate_sheets[start:end]
    
    response = {
        "rate_sheets": paginated_sheets,
        "total": total_returned,
        "page": page,
        "page_size": limit
    }
    
    # Only include answer and agentic fields when this was a search (query present), not a plain list
    if query and query.strip():
        if answer:
            response["answer"] = answer
        if isinstance(search_result, dict):
            if search_result.get("intent") is not None:
                response["intent"] = search_result["intent"]
            if search_result.get("engines_used") is not None:
                response["engines_used"] = search_result["engines_used"]
            if search_result.get("exact_rates") is not None:
                response["exact_rates"] = search_result["exact_rates"]
            if search_result.get("route_alternatives") is not None:
                response["route_alternatives"] = search_result["route_alternatives"]
    
    return response


@router.delete("/{rate_sheet_id}", status_code=204)
async def delete_rate_sheet(
    rate_sheet_id: str,
    organization_id: int = Query(...)
):
    """Delete a rate sheet from ChromaDB"""
    service = RateSheetService()
    success = await service.delete_rate_sheet(
        rate_sheet_id=rate_sheet_id,
        organization_id=organization_id
    )
    
    if not success:
        raise HTTPException(status_code=404, detail="Rate sheet not found")
    
    return None


@router.post("/query-routes", status_code=200)
async def query_routes(
    request: Request,
    organization_id: int = Query(...)
):
    """
    Query routes from structured data (PostgreSQL)
    Used by orchestrator service for SQL retrieval
    
    Body should contain:
    - origin_port: (optional) Origin port code
    - destination_port: (optional) Destination port code
    - container_type: (optional) Container type
    - valid_date: (optional) ISO format date string
    """
    try:
        from app.core.database import AsyncSessionLocal
        from app.services.structured_data_service import StructuredDataService
        from datetime import datetime
        
        body_data = await request.json()
        origin_port = body_data.get("origin_port")
        destination_port = body_data.get("destination_port")
        container_type = body_data.get("container_type")
        valid_date_str = body_data.get("valid_date")
        
        valid_date = None
        if valid_date_str:
            try:
                valid_date = datetime.fromisoformat(valid_date_str.replace('Z', '+00:00'))
            except Exception:
                pass
        
        async with AsyncSessionLocal() as session:
            service = StructuredDataService()
            routes = await service.query_routes(
                session=session,
                organization_id=organization_id,
                origin_port=origin_port,
                destination_port=destination_port,
                container_type=container_type,
                valid_date=valid_date
            )
            return {"routes": routes, "count": len(routes)}
    
    except Exception as e:
        logger.error(f"Error querying routes: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/draft-email-response", status_code=200)
async def draft_email_response(
    request: Request,
    organization_id: int = Query(...)
):
    """
    Draft an email response based on rate sheet query
    
    Body should contain:
    - email_query: The email content/question to search for
    - original_email_subject: (optional) Original email subject
    - original_email_from: (optional) Original email sender
    - limit: (optional) Max rate sheets to include (default: 5)
    
    Returns drafted email with confidence scores
    """
    try:
        body_data = await request.json()
        email_query = body_data.get("email_query", "")
        original_email_subject = body_data.get("original_email_subject")
        original_email_from = body_data.get("original_email_from")
        limit = body_data.get("limit", 5)
        
        if not email_query:
            raise HTTPException(
                status_code=400,
                detail="Missing required field: email_query"
            )
        
        service = EmailResponseServiceV2()
        result = await service.draft_email_response(
            organization_id=organization_id,
            email_content=email_query,
            subject=original_email_subject,
            from_email=original_email_from
        )
        
        return result
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error drafting email response: {e}")
        raise HTTPException(status_code=500, detail=f"Error drafting email: {str(e)}")


@router.post("/send-email-response", status_code=200)
async def send_email_response(
    request: Request,
    organization_id: int = Query(...),
    user_id: int = Query(...),
    authorization: Optional[str] = Header(None, alias="Authorization")
):
    """
    Send the drafted email response
    
    Body should contain:
    - drafted_email: The drafted email (subject, body, confidence_note)
    - to_email: Recipient email address
    - cc_email: (optional) CC email
    - bcc_email: (optional) BCC email
    
    Headers:
    - Authorization: Bearer token (required)
    
    Returns send result
    """
    try:
        # Get authorization token from header
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(
                status_code=401,
                detail="Missing or invalid Authorization header. Use 'Bearer <token>'"
            )
        
        auth_token = authorization.replace("Bearer ", "").strip()
        
        body_data = await request.json()
        drafted_email = body_data.get("drafted_email")
        to_email = body_data.get("to_email")
        
        if not drafted_email:
            raise HTTPException(
                status_code=400,
                detail="Missing required field: drafted_email"
            )
        
        if not to_email:
            raise HTTPException(
                status_code=400,
                detail="Missing required field: to_email"
            )
        
        service = EmailResponseService()
        result = await service.send_email_response(
            drafted_email=drafted_email,
            to_email=to_email,
            user_id=user_id,
            organization_id=organization_id,
            authorization_token=auth_token,
            cc_email=body_data.get("cc_email"),
            bcc_email=body_data.get("bcc_email")
        )
        
        if not result.get("success"):
            raise HTTPException(
                status_code=500,
                detail=result.get("error", "Failed to send email")
            )
        
        return result
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error sending email response: {e}")
        raise HTTPException(status_code=500, detail=f"Error sending email: {str(e)}")


@router.get("/health", status_code=200)
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "service": "rate_sheet_service"}


async def verify_admin_access(token: str) -> bool:
    """Verify if user has admin access"""
    import httpx
    from app.core.config import settings
    try:
        async with httpx.AsyncClient() as client:
            auth_response = await client.get(
                f"{settings.AUTH_SERVICE_URL}/api/auth/admin",
                headers={"Authorization": f"Bearer {token}"},
                timeout=10.0
            )
            return auth_response.status_code == 200
    except Exception as e:
        logger.error(f"Error verifying admin access: {str(e)}")
        return False


@router.get("/admin/all")
async def admin_list_all_rate_sheets(
    authorization: str = Header(default=""),
    limit: int = Query(default=1000, ge=1, le=10000),
    offset: int = Query(default=0, ge=0),
):
    """
    Admin endpoint: List ALL rate sheets across ALL organizations (admin only)
    
    IMPORTANT: This endpoint bypasses organization-level isolation for admin access.
    Only users with is_staff=True or is_superuser=True can access this.
    """
    if not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=403,
            detail="Authorization header missing or invalid",
        )
    
    token = authorization.replace("Bearer ", "")
    
    # Verify admin access
    if not await verify_admin_access(token):
        raise HTTPException(
            status_code=403,
            detail="Admin access required. Only staff or superuser accounts can access this endpoint."
        )
    
    try:
        import httpx
        from app.core.config import settings
        
        # Query vector DB directly to get all rate sheets (bypass organization filter)
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{settings.VECTOR_DB_SERVICE_URL}/api/vector/collections/rate_sheets/query",
                json={
                    "query_texts": ["rate sheet"],
                    "n_results": limit + offset  # Get enough to paginate
                },
                timeout=60.0
            )
            
            if response.status_code != 200:
                raise HTTPException(
                    status_code=500,
                    detail="Failed to query vector DB"
                )
            
            data = response.json()
            results = data.get("results", {})
            ids = results.get("ids", [[]])[0]
            metadatas = results.get("metadatas", [[]])[0]
            documents = results.get("documents", [[]])[0]
            
            # Build rate sheet list
            all_rate_sheets = []
            for i, meta in enumerate(metadatas):
                rate_sheet_data = {
                    "id": ids[i],
                    "file_name": meta.get("file_name", ""),
                    "carrier_name": meta.get("carrier_name", ""),
                    "title": meta.get("title", ""),
                    "rate_sheet_type": meta.get("rate_sheet_type", ""),
                    "status": meta.get("status", ""),
                    "organization_id": meta.get("organization_id"),
                    "user_id": meta.get("user_id"),
                    "uploaded_at": meta.get("uploaded_at"),
                    "metadata": meta,
                    "document_preview": documents[i][:500] if documents else "",  # Truncate for list view
                }
                all_rate_sheets.append(rate_sheet_data)
            
            # Sort by uploaded_at (newest first)
            all_rate_sheets.sort(key=lambda x: x.get("uploaded_at") or "", reverse=True)
            
            # Apply pagination
            paginated_sheets = all_rate_sheets[offset:offset + limit]
            
            return {
                "rate_sheets": paginated_sheets,
                "total": len(all_rate_sheets),
                "limit": limit,
                "offset": offset,
                "returned": len(paginated_sheets)
            }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to list all rate sheets (admin): {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to list all rate sheets: {str(e)}",
        )


@router.get("/admin/stats")
async def admin_rate_sheet_stats(
    authorization: str = Header(default="")
):
    """
    Admin endpoint: Get rate sheet statistics across all organizations (admin only)
    """
    if not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=403,
            detail="Authorization header missing or invalid",
        )
    
    token = authorization.replace("Bearer ", "")
    
    # Verify admin access
    if not await verify_admin_access(token):
        raise HTTPException(
            status_code=403,
            detail="Admin access required. Only staff or superuser accounts can access this endpoint."
        )
    
    try:
        import httpx
        from app.core.config import settings
        
        # Get collection info to get total count
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{settings.VECTOR_DB_SERVICE_URL}/api/vector/collections/rate_sheets",
                timeout=10.0
            )
            
            total_rate_sheets = 0
            unique_organizations = set()
            
            if response.status_code == 200:
                collection_info = response.json()
                total_rate_sheets = collection_info.get("count", 0)
                
                # Get sample to calculate org stats
                sample_response = await client.post(
                    f"{settings.VECTOR_DB_SERVICE_URL}/api/vector/collections/rate_sheets/query",
                    json={
                        "query_texts": ["rate sheet"],
                        "n_results": min(1000, total_rate_sheets)
                    },
                    timeout=30.0
                )
                
                if sample_response.status_code == 200:
                    sample_data = sample_response.json()
                    results = sample_data.get("results", {})
                    metadatas = results.get("metadatas", [[]])[0]
                    
                    for meta in metadatas:
                        org_id = meta.get("organization_id")
                        if org_id:
                            unique_organizations.add(str(org_id))
            
            return {
                "total_rate_sheets": total_rate_sheets,
                "unique_organizations": len(unique_organizations),
                "average_per_organization": total_rate_sheets / len(unique_organizations) if unique_organizations else 0
            }
            
    except Exception as e:
        logger.error(f"Failed to get rate sheet stats (admin): {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get rate sheet stats: {str(e)}",
        )


@router.post("/{rate_sheet_id}/reprocess", status_code=200)
async def reprocess_rate_sheet(
    rate_sheet_id: str,
    organization_id: int = Query(...)
):
    """
    Reprocess a rate sheet that failed AI extraction.
    
    Use this to retry extraction for rate sheets stuck in 'pending' or 'failed' status.
    
    This will:
    1. Re-read the stored file
    2. Re-parse the Excel data
    3. Re-run AI extraction
    4. Update the structured data
    
    Returns the updated rate sheet data.
    """
    try:
        service = RateSheetService()
        result = await service.reprocess_rate_sheet(
            rate_sheet_id=rate_sheet_id,
            organization_id=organization_id
        )
        
        if not result:
            raise HTTPException(status_code=404, detail="Rate sheet not found or not owned by this organization")
        
        return result
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error reprocessing rate sheet {rate_sheet_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error reprocessing rate sheet: {str(e)}")


@router.post("/reprocess-all-pending", status_code=200)
async def reprocess_all_pending(
    organization_id: int = Query(...),
    background_tasks: BackgroundTasks = None
):
    """
    Reprocess ALL rate sheets in 'pending' or 'failed' status for an organization.
    
    This runs in the background and returns immediately with a list of rate sheets being reprocessed.
    """
    try:
        from app.core.database import AsyncSessionLocal
        from app.models import RateSheetStructuredData
        from sqlalchemy import select, or_
        
        # Find all pending/failed rate sheets
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(RateSheetStructuredData).where(
                    RateSheetStructuredData.organization_id == organization_id,
                    or_(
                        RateSheetStructuredData.status == 'pending',
                        RateSheetStructuredData.status == 'failed'
                    )
                )
            )
            pending_sheets = result.scalars().all()
        
        if not pending_sheets:
            return {
                "message": "No pending or failed rate sheets to reprocess",
                "count": 0,
                "rate_sheet_ids": []
            }
        
        # Queue background reprocessing for each
        rate_sheet_ids = [sheet.rate_sheet_id for sheet in pending_sheets]
        
        for rate_sheet_id in rate_sheet_ids:
            if background_tasks:
                background_tasks.add_task(
                    _reprocess_rate_sheet_background,
                    rate_sheet_id,
                    organization_id
                )
        
        return {
            "message": f"Queued {len(rate_sheet_ids)} rate sheets for reprocessing",
            "count": len(rate_sheet_ids),
            "rate_sheet_ids": rate_sheet_ids
        }
    
    except Exception as e:
        logger.error(f"Error queuing rate sheets for reprocessing: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error queuing reprocessing: {str(e)}")


async def _reprocess_rate_sheet_background(rate_sheet_id: str, organization_id: int):
    """Background task to reprocess a rate sheet"""
    try:
        service = RateSheetService()
        await service.reprocess_rate_sheet(rate_sheet_id, organization_id)
        logger.info(f"✅ Reprocessed rate sheet {rate_sheet_id}")
    except Exception as e:
        logger.error(f"❌ Failed to reprocess rate sheet {rate_sheet_id}: {e}")


@router.post("/reprocess-all", status_code=200)
async def reprocess_all_rate_sheets(
    organization_id: int = Query(...)
):
    """
    Reprocess ALL rate sheets for an organization with the improved AI extraction.
    
    This will:
    1. Get all rate sheets from PostgreSQL
    2. Re-run AI extraction on each file with improved prompts
    3. Update the normalized tables with correct port names and pricing
    
    Use this after AI extraction improvements to fix previously extracted data.
    
    NOTE: This is a synchronous operation that may take several minutes.
    """
    try:
        service = RateSheetService()
        result = await service.reprocess_all_rate_sheets(organization_id=organization_id)
        return result
    except Exception as e:
        logger.error(f"Error reprocessing all rate sheets: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error reprocessing rate sheets: {str(e)}")


@router.post("/sync-chromadb", status_code=200)
async def sync_rate_sheets_to_chromadb(
    organization_id: int = Query(...)
):
    """
    Sync all rate sheets from PostgreSQL to ChromaDB.
    
    This is useful when rate sheets exist in PostgreSQL but are missing from ChromaDB.
    It will check each rate sheet and add it to ChromaDB if missing.
    """
    from app.core.database import AsyncSessionLocal
    from app.models import RateSheetStructuredData
    from sqlalchemy import select
    from app.services.embedding_service import EmbeddingService
    
    try:
        embedding_service = EmbeddingService()
        
        # Get all rate sheets from PostgreSQL
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(RateSheetStructuredData).where(
                    RateSheetStructuredData.organization_id == organization_id,
                    RateSheetStructuredData.status == 'processed'
                )
            )
            rate_sheets = result.scalars().all()
        
        synced = 0
        already_exists = 0
        failed = 0
        
        for rs in rate_sheets:
            try:
                # Check if exists in ChromaDB
                chromadb_doc = await embedding_service.get_rate_sheet_by_id(rs.rate_sheet_id)
                if chromadb_doc:
                    already_exists += 1
                    continue
                
                # Build structured_data from JSONB columns
                structured_data = {
                    "routes": rs.routes_json or [],
                    "pricing_tiers": rs.pricing_tiers_json or [],
                    "surcharges": rs.surcharges_json or [],
                    "additional_charges": rs.additional_charges or [],
                    "carrier_name": rs.carrier_name or "",
                    "rate_sheet_type": rs.rate_sheet_type or "ocean_freight",
                    "title": rs.title or "",
                    "validity": {
                        "valid_from": rs.valid_from.isoformat() if rs.valid_from else None,
                        "valid_to": rs.valid_to.isoformat() if rs.valid_to else None,
                        "effective_date": rs.effective_date.isoformat() if rs.effective_date else None
                    },
                    "relationships": {
                        "is_related": rs.is_related == "true",
                        "relationship_type": rs.relationship_type or "",
                        "related_to_rate_sheets": rs.related_rate_sheet_ids or []
                    }
                }
                
                # Not in ChromaDB - sync it
                from datetime import datetime
                now = datetime.utcnow()
                metadata = {
                    "organization_id": organization_id,
                    "user_id": rs.user_id,
                    "file_name": rs.file_name or "",
                    "file_path": rs.file_path or "",
                    "file_size_bytes": 0,
                    "file_type": rs.file_name.split('.')[-1] if rs.file_name else "",
                    "status": "processed",
                    "created_at": rs.created_at.isoformat() if rs.created_at else now.isoformat(),
                    "updated_at": now.isoformat(),
                    "processed_at": now.isoformat(),
                }
                await embedding_service.store_rate_sheet(
                    rate_sheet_id=rs.rate_sheet_id,
                    rate_sheet_data=structured_data,
                    parsed_data={},
                    metadata=metadata
                )
                synced += 1
                logger.info(f"✅ Synced {rs.rate_sheet_id} to ChromaDB")
            except Exception as e:
                failed += 1
                logger.error(f"❌ Failed to sync {rs.rate_sheet_id}: {e}")
        
        return {
            "message": f"ChromaDB sync complete",
            "total": len(rate_sheets),
            "synced": synced,
            "already_exists": already_exists,
            "failed": failed
        }
    except Exception as e:
        logger.error(f"Error syncing to ChromaDB: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error syncing to ChromaDB: {str(e)}")
