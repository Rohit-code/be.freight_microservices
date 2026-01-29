"""
API Routes for Orchestrator Service
"""
from fastapi import APIRouter, HTTPException, Body, Query
from typing import Optional, Dict, Any
from app.services.orchestrator import AgentOrchestrator

router = APIRouter(prefix="/api/orchestrator", tags=["orchestrator"])


@router.post("/query")
async def orchestrate_query(
    organization_id: int = Query(...),
    email_content: str = Body(..., embed=True),
    subject: Optional[str] = Body(None, embed=True),
    from_email: Optional[str] = Body(None, embed=True)
):
    """Orchestrate query across SQL, Graph, and Vector engines"""
    try:
        orchestrator = AgentOrchestrator()
        result = await orchestrator.orchestrate_query(
            organization_id=organization_id,
            email_content=email_content,
            subject=subject,
            from_email=from_email
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
