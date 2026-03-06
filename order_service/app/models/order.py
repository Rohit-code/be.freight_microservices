from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.core.database import Base


class Order(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, nullable=False, index=True)
    customer_id = Column(Integer, nullable=True, index=True)  # Logical FK to customer_service.customers.id
    reference_number = Column(String(64), unique=True, nullable=False, index=True)
    status = Column(String(32), nullable=False, default="booked")
    origin_port = Column(String(128), nullable=True)
    destination_port = Column(String(128), nullable=True)
    carrier = Column(String(128), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    tracking_events = relationship("OrderTrackingEvent", back_populates="order", order_by="OrderTrackingEvent.occurred_at")
    containers = relationship("Container", back_populates="order", cascade="all, delete-orphan")


class OrderTrackingEvent(Base):
    __tablename__ = "order_tracking_events"

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True)
    event_type = Column(String(64), nullable=False)
    description = Column(Text, nullable=True)
    location = Column(String(256), nullable=True)
    occurred_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    order = relationship("Order", back_populates="tracking_events")


class Container(Base):
    __tablename__ = "containers"

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True)
    container_number = Column(String(64), nullable=False)
    container_type = Column(String(32), nullable=True)  # e.g. 20GP, 40HC
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    order = relationship("Order", back_populates="containers")
