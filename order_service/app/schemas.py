from pydantic import BaseModel
from datetime import datetime
from typing import Optional


class OrderCreate(BaseModel):
    reference_number: str
    status: str = "booked"
    origin_port: Optional[str] = None
    destination_port: Optional[str] = None
    carrier: Optional[str] = None
    customer_id: Optional[int] = None


class OrderCreateForUser(BaseModel):
    """Internal API: create order on behalf of a user (e.g. from quote acceptance)."""
    user_id: int
    reference_number: str
    status: str = "booked"
    origin_port: Optional[str] = None
    destination_port: Optional[str] = None
    carrier: Optional[str] = None
    customer_id: Optional[int] = None


class OrderTrackingEventCreate(BaseModel):
    event_type: str
    description: Optional[str] = None
    location: Optional[str] = None
    occurred_at: Optional[datetime] = None


class OrderTrackingEventUpdate(BaseModel):
    event_type: Optional[str] = None
    description: Optional[str] = None
    location: Optional[str] = None
    occurred_at: Optional[datetime] = None


class OrderTrackingEventResponse(BaseModel):
    id: int
    order_id: int
    event_type: str
    description: Optional[str] = None
    location: Optional[str] = None
    occurred_at: datetime
    created_at: datetime

    class Config:
        from_attributes = True


class OrderResponse(BaseModel):
    id: int
    user_id: int
    customer_id: Optional[int] = None
    reference_number: str
    status: str
    origin_port: Optional[str] = None
    destination_port: Optional[str] = None
    carrier: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    tracking_events: list[OrderTrackingEventResponse] = []
    containers: list["ContainerResponse"] = []

    class Config:
        from_attributes = True


class OrderListResponse(BaseModel):
    id: int
    user_id: int
    customer_id: Optional[int] = None
    reference_number: str
    status: str
    origin_port: Optional[str] = None
    destination_port: Optional[str] = None
    carrier: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ContainerCreate(BaseModel):
    container_number: str
    container_type: Optional[str] = None


class ContainerUpdate(BaseModel):
    container_number: Optional[str] = None
    container_type: Optional[str] = None


class ContainerResponse(BaseModel):
    id: int
    order_id: int
    container_number: str
    container_type: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


OrderResponse.model_rebuild()
