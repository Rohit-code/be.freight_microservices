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
