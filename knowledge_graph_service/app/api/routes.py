"""
API Routes for Knowledge Graph Service
"""
from fastapi import APIRouter, HTTPException, Query, Body
from typing import Optional, List, Dict, Any
from datetime import datetime
from pydantic import BaseModel, Field

# Import with error handling
try:
    from app.services.graph_service import GraphService, ARANGO_AVAILABLE
except ImportError:
    ARANGO_AVAILABLE = False
    GraphService = None

router = APIRouter(prefix="/api/graph", tags=["knowledge-graph"])


def check_arango_available():
    """Check if ArangoDB is available"""
    if not ARANGO_AVAILABLE:
        raise HTTPException(
            status_code=503,
            detail="python-arango is not installed. Install with: pip install python-arango"
        )


# Pydantic models for request/response
class RouteData(BaseModel):
    """Route data structure"""
    origin_port: str = Field(..., description="Origin port code")
    destination_port: str = Field(..., description="Destination port code")
    container_type: Optional[str] = Field(None, description="Container type (e.g., 20ft, 40ft)")
    base_rate: Optional[float] = Field(None, description="Base rate for this route")
    transit_time: Optional[str] = Field(None, description="Transit time")


class CreateRateSheetGraphRequest(BaseModel):
    """Request body for creating rate sheet graph"""
    organization_id: int = Field(..., description="Organization ID")
    carrier_name: str = Field(..., description="Carrier name")
    routes: List[RouteData] = Field(..., description="List of routes")
    valid_from: Optional[str] = Field(None, description="Valid from date (ISO format)")
    valid_to: Optional[str] = Field(None, description="Valid to date (ISO format)")


@router.post("/rate-sheets/{rate_sheet_id}")
async def create_rate_sheet_graph(
    rate_sheet_id: str,
    request: CreateRateSheetGraphRequest = Body(...)
):
    """Create graph nodes and relationships for a rate sheet"""
    check_arango_available()
    try:
        graph_service = GraphService()
        await graph_service.initialize()
        
        valid_from_dt = datetime.fromisoformat(request.valid_from) if request.valid_from else None
        valid_to_dt = datetime.fromisoformat(request.valid_to) if request.valid_to else None
        
        # Convert Pydantic models to dicts
        routes_dict = [route.model_dump() for route in request.routes]
        
        await graph_service.create_rate_sheet_graph(
            rate_sheet_id=rate_sheet_id,
            organization_id=request.organization_id,
            carrier_name=request.carrier_name,
            routes=routes_dict,
            valid_from=valid_from_dt,
            valid_to=valid_to_dt
        )
        
        await graph_service.close()
        
        return {"status": "success", "rate_sheet_id": rate_sheet_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/routes/by-lane")
async def get_routes_by_lane(
    organization_id: int = Query(...),
    origin_port: str = Query(...),
    destination_port: str = Query(...),
    container_type: Optional[str] = None,
    valid_date: Optional[str] = None
):
    """Find routes matching a specific lane (origin -> destination)"""
    check_arango_available()
    try:
        graph_service = GraphService()
        await graph_service.initialize()
        
        valid_dt = datetime.fromisoformat(valid_date) if valid_date else None
        
        routes = await graph_service.find_routes_by_lane(
            organization_id=organization_id,
            origin_port=origin_port,
            destination_port=destination_port,
            container_type=container_type,
            valid_date=valid_dt
        )
        
        await graph_service.close()
        
        return {"routes": routes, "count": len(routes)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/routes/by-carrier")
async def get_routes_by_carrier(
    organization_id: int = Query(...),
    carrier_name: str = Query(...),
    valid_date: Optional[str] = None
):
    """Find all routes for a specific carrier"""
    check_arango_available()
    try:
        graph_service = GraphService()
        await graph_service.initialize()
        
        valid_dt = datetime.fromisoformat(valid_date) if valid_date else None
        
        routes = await graph_service.find_carrier_routes(
            organization_id=organization_id,
            carrier_name=carrier_name,
            valid_date=valid_dt
        )
        
        await graph_service.close()
        
        return {"routes": routes, "count": len(routes)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/routes/alternatives")
async def get_alternative_routes(
    organization_id: int = Query(...),
    origin_port: str = Query(...),
    destination_port: str = Query(...),
    max_hops: int = Query(2, ge=1, le=5),
    valid_date: Optional[str] = Query(None, description="Filter by validity date (ISO format)")
):
    """Find alternative routes via intermediate ports, optionally filtered by validity date"""
    check_arango_available()
    try:
        graph_service = GraphService()
        await graph_service.initialize()
        
        valid_dt = datetime.fromisoformat(valid_date) if valid_date else None
        
        alternatives = await graph_service.find_alternative_routes(
            organization_id=organization_id,
            origin_port=origin_port,
            destination_port=destination_port,
            max_hops=max_hops,
            valid_date=valid_dt
        )
        
        await graph_service.close()
        
        return {"alternatives": alternatives, "count": len(alternatives)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
