"""
API Routes for Decision Engine
"""
from fastapi import APIRouter, HTTPException, Body
from typing import Dict, Any
from app.services.decision_engine import DecisionEngine

router = APIRouter(prefix="/api/decision", tags=["decision-engine"])


@router.post("/verify")
async def verify_and_decide(
    intent_result: Dict[str, Any] = Body(...),
    orchestration_results: Dict[str, Any] = Body(...)
):
    """Verify results and make decision on next steps"""
    try:
        engine = DecisionEngine()
        result = await engine.verify_and_decide(intent_result, orchestration_results)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
