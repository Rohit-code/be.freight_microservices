from fastapi import APIRouter, HTTPException, Request
from typing import Optional, List, Dict, Any
from ..services.ai_service import (
    is_ai_available,
    general_chat,
    analyze_email,
    generate_email_response,
    analyze_spreadsheet_data,
    analyze_document,
)

router = APIRouter(prefix="/api/ai", tags=["ai"])


@router.get("/status")
async def ai_status():
    """Check if AI service is available"""
    return {'available': is_ai_available()}


@router.post("/chat")
async def ai_chat(request: Request):
    """General AI chat endpoint"""
    if not is_ai_available():
        raise HTTPException(
            status_code=503,
            detail="AI service is not configured. Please add OPENAI_API_KEY to environment variables.",
        )
    
    body_data = await request.json()
    message = body_data.get('message')
    conversation_history = body_data.get('conversation_history', [])
    
    if not message:
        raise HTTPException(
            status_code=400,
            detail="Missing required field: message",
        )
    
    response = general_chat(message, conversation_history)
    return {'response': response}


@router.post("/analyze-email")
async def ai_analyze_email(request: Request):
    """Analyze email with AI"""
    if not is_ai_available():
        raise HTTPException(
            status_code=503,
            detail="AI service is not configured",
        )
    
    body_data = await request.json()
    email_content = body_data.get('content', '')
    subject = body_data.get('subject', '')
    from_sender = body_data.get('from', '')
    
    if not email_content:
        raise HTTPException(
            status_code=400,
            detail="Missing required field: content",
        )
    
    analysis = analyze_email(email_content, subject, from_sender)
    return analysis


@router.post("/generate-email-response")
async def ai_generate_email_response(request: Request):
    """Generate email response with AI"""
    if not is_ai_available():
        raise HTTPException(
            status_code=503,
            detail="AI service is not configured",
        )
    
    body_data = await request.json()
    email_content = body_data.get('content', '')
    subject = body_data.get('subject', '')
    tone = body_data.get('tone', 'professional')
    
    if not email_content:
        raise HTTPException(
            status_code=400,
            detail="Missing required field: content",
        )
    
    response = generate_email_response(email_content, subject, tone)
    return {'response': response}


@router.post("/analyze-spreadsheet")
async def ai_analyze_spreadsheet(request: Request):
    """Analyze spreadsheet with AI"""
    if not is_ai_available():
        raise HTTPException(
            status_code=503,
            detail="AI service is not configured",
        )
    
    body_data = await request.json()
    data = body_data.get('data', [])
    context = body_data.get('context', '')
    
    if not data:
        raise HTTPException(
            status_code=400,
            detail="Missing required field: data",
        )
    
    analysis = analyze_spreadsheet_data(data, context)
    return analysis


@router.post("/analyze-document")
async def ai_analyze_document(request: Request):
    """Analyze document with AI"""
    if not is_ai_available():
        raise HTTPException(
            status_code=503,
            detail="AI service is not configured",
        )
    
    body_data = await request.json()
    content = body_data.get('content', '')
    title = body_data.get('title', '')
    
    if not content:
        raise HTTPException(
            status_code=400,
            detail="Missing required field: content",
        )
    
    analysis = analyze_document(content, title)
    return analysis
