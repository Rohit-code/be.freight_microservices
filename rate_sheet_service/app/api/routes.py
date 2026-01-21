from fastapi import APIRouter, Depends, UploadFile, File, HTTPException, Query, Request, Header
from typing import List, Optional
import logging

from app.services.rate_sheet_service import RateSheetService
from app.services.email_response_service import EmailResponseService

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
        logger.error(f"Error uploading rate sheet: {e}")
        raise HTTPException(status_code=500, detail=f"Error processing rate sheet: {str(e)}")


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


@router.get("/")
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
        # New format with answer
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
    
    # Simple pagination (though we're already returning top 3, pagination is minimal)
    start = (page - 1) * limit
    end = start + limit
    paginated_sheets = rate_sheets[start:end]
    
    response = {
        "rate_sheets": paginated_sheets,
        "total": total_returned,
        "page": page,
        "page_size": limit
    }
    
    # Add answer if available
    if answer:
        response["answer"] = answer
    
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
        
        service = EmailResponseService()
        result = await service.draft_email_response(
            email_query=email_query,
            organization_id=organization_id,
            original_email_subject=original_email_subject,
            original_email_from=original_email_from,
            limit=limit
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
