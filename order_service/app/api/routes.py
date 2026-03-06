from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.deps import get_current_user_id, get_current_user_id_or_customer_id, get_current_user_id_and_staff, verify_internal_api_key
from app.models import Order, OrderTrackingEvent, Container
from app.schemas import (
    OrderCreate,
    OrderCreateForUser,
    OrderResponse,
    OrderListResponse,
    OrderTrackingEventCreate,
    OrderTrackingEventUpdate,
    OrderTrackingEventResponse,
    ContainerCreate,
    ContainerUpdate,
    ContainerResponse,
)

router = APIRouter(prefix="/api/orders", tags=["orders"])


@router.get("", response_model=list[OrderListResponse])
async def list_orders(
    user_id_and_customer_id: tuple[int | None, int | None] = Depends(get_current_user_id_or_customer_id),
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
):
    """List orders for the authenticated user (NVOCC) or customer (portal)."""
    user_id, customer_id = user_id_and_customer_id
    if customer_id is not None:
        result = await db.execute(
            select(Order)
            .where(Order.customer_id == customer_id)
            .order_by(Order.updated_at.desc())
            .offset((page - 1) * limit)
            .limit(limit)
        )
    else:
        result = await db.execute(
            select(Order)
            .where(Order.user_id == user_id)
            .order_by(Order.updated_at.desc())
            .offset((page - 1) * limit)
            .limit(limit)
        )
    orders = result.scalars().all()
    return orders


@router.get("/{order_id}", response_model=OrderResponse)
async def get_order(
    order_id: int,
    user_id_and_customer_id: tuple[int | None, int | None] = Depends(get_current_user_id_or_customer_id),
    db: AsyncSession = Depends(get_db),
):
    """Get one order with tracking events. Allowed if order belongs to current user (NVOCC) or current customer (portal)."""
    user_id, customer_id = user_id_and_customer_id
    result = await db.execute(select(Order).where(Order.id == order_id))
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    if customer_id is not None:
        if order.customer_id != customer_id:
            raise HTTPException(status_code=404, detail="Order not found")
    elif order.user_id != user_id:
        raise HTTPException(status_code=404, detail="Order not found")
    # Load tracking_events and containers
    await db.refresh(order, ["tracking_events", "containers"])
    events = sorted(order.tracking_events, key=lambda e: e.occurred_at or e.created_at)
    return OrderResponse(
        id=order.id,
        user_id=order.user_id,
        customer_id=order.customer_id,
        reference_number=order.reference_number,
        status=order.status,
        origin_port=order.origin_port,
        destination_port=order.destination_port,
        carrier=order.carrier,
        created_at=order.created_at,
        updated_at=order.updated_at,
        tracking_events=[
            OrderTrackingEventResponse(
                id=e.id,
                order_id=e.order_id,
                event_type=e.event_type,
                description=e.description,
                location=e.location,
                occurred_at=e.occurred_at,
                created_at=e.created_at,
            )
            for e in events
        ],
        containers=[ContainerResponse.model_validate(c) for c in order.containers],
    )


@router.post("", status_code=201, response_model=OrderListResponse)
async def create_order(
    body: OrderCreate,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Create an order for the authenticated user."""
    existing = await db.execute(
        select(Order).where(Order.reference_number == body.reference_number)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=400,
            detail=f"Order with reference {body.reference_number} already exists",
        )
    order = Order(
        user_id=user_id,
        customer_id=body.customer_id,
        reference_number=body.reference_number,
        status=body.status,
        origin_port=body.origin_port,
        destination_port=body.destination_port,
        carrier=body.carrier,
    )
    db.add(order)
    await db.commit()
    await db.refresh(order)
    return order


@router.post("/internal/create-for-user", status_code=201, response_model=OrderListResponse)
async def create_order_for_user(
    body: OrderCreateForUser,
    _: None = Depends(verify_internal_api_key),
    db: AsyncSession = Depends(get_db),
):
    """Internal API: create an order on behalf of a user (e.g. when customer accepts quote via email)."""
    existing = await db.execute(
        select(Order).where(Order.reference_number == body.reference_number)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=400,
            detail=f"Order with reference {body.reference_number} already exists",
        )
    order = Order(
        user_id=body.user_id,
        customer_id=body.customer_id,
        reference_number=body.reference_number,
        status=body.status,
        origin_port=body.origin_port,
        destination_port=body.destination_port,
        carrier=body.carrier,
    )
    db.add(order)
    await db.commit()
    await db.refresh(order)
    return order


@router.post("/{order_id}/tracking", status_code=201, response_model=OrderTrackingEventResponse)
async def add_tracking_event(
    order_id: int,
    body: OrderTrackingEventCreate,
    user_id_and_staff: tuple[int, bool] = Depends(get_current_user_id_and_staff),
    db: AsyncSession = Depends(get_db),
):
    """Add a tracking event. Allowed if current user is order owner or staff."""
    user_id, is_staff = user_id_and_staff
    result = await db.execute(select(Order).where(Order.id == order_id))
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    if order.user_id != user_id and not is_staff:
        raise HTTPException(status_code=403, detail="Not allowed to add tracking to this order")
    occurred_at = body.occurred_at
    if occurred_at is None:
        from datetime import datetime, timezone
        occurred_at = datetime.now(timezone.utc)
    event = OrderTrackingEvent(
        order_id=order_id,
        event_type=body.event_type,
        description=body.description,
        location=body.location,
        occurred_at=occurred_at,
    )
    db.add(event)
    await db.commit()
    await db.refresh(event)
    return event


@router.patch("/{order_id}/tracking/{event_id}", response_model=OrderTrackingEventResponse)
async def update_tracking_event(
    order_id: int,
    event_id: int,
    body: OrderTrackingEventUpdate,
    user_id_and_staff: tuple[int, bool] = Depends(get_current_user_id_and_staff),
    db: AsyncSession = Depends(get_db),
):
    """Update a tracking event. Allowed if current user is order owner or staff."""
    user_id, is_staff = user_id_and_staff
    result = await db.execute(select(Order).where(Order.id == order_id))
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    if order.user_id != user_id and not is_staff:
        raise HTTPException(status_code=403, detail="Not allowed to update tracking for this order")
    event_result = await db.execute(
        select(OrderTrackingEvent).where(
            OrderTrackingEvent.id == event_id,
            OrderTrackingEvent.order_id == order_id,
        )
    )
    event = event_result.scalar_one_or_none()
    if not event:
        raise HTTPException(status_code=404, detail="Tracking event not found")
    if body.event_type is not None:
        event.event_type = body.event_type
    if body.description is not None:
        event.description = body.description
    if body.location is not None:
        event.location = body.location
    if body.occurred_at is not None:
        event.occurred_at = body.occurred_at
    await db.commit()
    await db.refresh(event)
    return event


@router.get("/{order_id}/containers", response_model=list[ContainerResponse])
async def list_containers(
    order_id: int,
    user_id_and_customer_id: tuple[int | None, int | None] = Depends(get_current_user_id_or_customer_id),
    db: AsyncSession = Depends(get_db),
):
    """List containers for an order. Allowed if order belongs to current user (NVOCC) or current customer (portal)."""
    user_id, customer_id = user_id_and_customer_id
    result = await db.execute(select(Order).where(Order.id == order_id))
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    if customer_id is not None:
        if order.customer_id != customer_id:
            raise HTTPException(status_code=404, detail="Order not found")
    elif order.user_id != user_id:
        raise HTTPException(status_code=404, detail="Order not found")
    await db.refresh(order, ["containers"])
    return [ContainerResponse.model_validate(c) for c in order.containers]


@router.post("/{order_id}/containers", status_code=201, response_model=ContainerResponse)
async def create_container(
    order_id: int,
    body: ContainerCreate,
    user_id_and_staff: tuple[int, bool] = Depends(get_current_user_id_and_staff),
    db: AsyncSession = Depends(get_db),
):
    """Add a container to an order. Allowed if current user is order owner or staff."""
    user_id, is_staff = user_id_and_staff
    result = await db.execute(select(Order).where(Order.id == order_id))
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    if order.user_id != user_id and not is_staff:
        raise HTTPException(status_code=403, detail="Not allowed to add containers to this order")
    container = Container(
        order_id=order_id,
        container_number=body.container_number.strip(),
        container_type=body.container_type.strip() if body.container_type else None,
    )
    db.add(container)
    await db.commit()
    await db.refresh(container)
    return container


@router.patch("/{order_id}/containers/{container_id}", response_model=ContainerResponse)
async def update_container(
    order_id: int,
    container_id: int,
    body: ContainerUpdate,
    user_id_and_staff: tuple[int, bool] = Depends(get_current_user_id_and_staff),
    db: AsyncSession = Depends(get_db),
):
    """Update a container. Allowed if current user is order owner or staff."""
    user_id, is_staff = user_id_and_staff
    result = await db.execute(select(Order).where(Order.id == order_id))
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    if order.user_id != user_id and not is_staff:
        raise HTTPException(status_code=403, detail="Not allowed to update containers for this order")
    c_result = await db.execute(
        select(Container).where(
            Container.id == container_id,
            Container.order_id == order_id,
        )
    )
    container = c_result.scalar_one_or_none()
    if not container:
        raise HTTPException(status_code=404, detail="Container not found")
    if body.container_number is not None:
        container.container_number = body.container_number.strip()
    if body.container_type is not None:
        container.container_type = body.container_type.strip() or None
    await db.commit()
    await db.refresh(container)
    return container


@router.delete("/{order_id}/containers/{container_id}", status_code=204)
async def delete_container(
    order_id: int,
    container_id: int,
    user_id_and_staff: tuple[int, bool] = Depends(get_current_user_id_and_staff),
    db: AsyncSession = Depends(get_db),
):
    """Delete a container. Allowed if current user is order owner or staff."""
    user_id, is_staff = user_id_and_staff
    result = await db.execute(select(Order).where(Order.id == order_id))
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    if order.user_id != user_id and not is_staff:
        raise HTTPException(status_code=403, detail="Not allowed to delete containers for this order")
    c_result = await db.execute(
        select(Container).where(
            Container.id == container_id,
            Container.order_id == order_id,
        )
    )
    container = c_result.scalar_one_or_none()
    if not container:
        raise HTTPException(status_code=404, detail="Container not found")
    await db.delete(container)
    await db.commit()
