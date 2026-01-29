"""
API Routes for Intent Classifier Service
"""
from fastapi import APIRouter, HTTPException, Body
from typing import Optional, Dict, Any
from app.services.intent_classifier import IntentClassifier

router = APIRouter(prefix="/api/intent", tags=["intent-classifier"])


@router.post("/classify")
async def classify_email_intent(
    email_content: str = Body(..., embed=True),
    subject: Optional[str] = Body(None, embed=True),
    from_email: Optional[str] = Body(None, embed=True)
):
    """Classify email intent and extract structured query parameters"""
    try:
        classifier = IntentClassifier()
        result = await classifier.classify_intent(
            email_content=email_content,
            subject=subject,
            from_email=from_email
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
