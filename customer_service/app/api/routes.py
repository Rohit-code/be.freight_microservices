from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from passlib.context import CryptContext

from app.core.database import get_db
from app.deps import (
    get_current_user_id,
    get_current_user_id_and_organization_id,
    get_current_customer_id,
    verify_internal_api_key,
)
from app.models import Customer
from app.schemas import (
    CustomerCreate,
    CustomerUpdate,
    CustomerResponse,
    CustomerListResponse,
    CustomerLoginRequest,
    CustomerLoginResponse,
    CustomerPortalOut,
)
from app.utils.jwt_customer import generate_customer_token

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

router = APIRouter(prefix="/api/customers", tags=["customers"])


@router.post("/login", response_model=CustomerLoginResponse)
async def customer_login(
    body: CustomerLoginRequest,
    db: AsyncSession = Depends(get_db),
):
    """Customer portal login: email + password. Scoped by organization so the same email can be a customer of multiple orgs."""
    email = body.email.strip().lower()
    organization_id = body.organization_id
    if organization_id is None:
        raise HTTPException(
            status_code=400,
            detail="organization_id is required for customer portal login",
        )
    result = await db.execute(
        select(Customer).where(
            Customer.contact_email == email,
            Customer.organization_id == organization_id,
        ).limit(1)
    )
    customer = result.scalar_one_or_none()
    if not customer or not customer.password_hash:
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if not pwd_context.verify(body.password, customer.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    token = generate_customer_token(customer.id, customer.contact_email)
    return CustomerLoginResponse(
        token=token,
        customer=CustomerPortalOut(
            id=customer.id,
            company_name=customer.company_name,
            contact_email=customer.contact_email,
        ),
    )


@router.get("/me", response_model=CustomerPortalOut)
async def get_current_customer(
    customer_id: int = Depends(get_current_customer_id),
    db: AsyncSession = Depends(get_db),
):
    """Return current customer (for portal; requires customer JWT from login)."""
    result = await db.execute(select(Customer).where(Customer.id == customer_id))
    customer = result.scalar_one_or_none()
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    return CustomerPortalOut(
        id=customer.id,
        company_name=customer.company_name,
        contact_email=customer.contact_email,
    )


@router.get("/internal/by-email")
async def get_customer_by_email_internal(
    user_id: int = Query(...),
    email: str = Query(...),
    _: None = Depends(verify_internal_api_key),
    db: AsyncSession = Depends(get_db),
):
    """Internal API: resolve customer by user_id and contact_email (e.g. for quote acceptance)."""
    result = await db.execute(
        select(Customer).where(
            Customer.user_id == user_id,
            Customer.contact_email == email.strip().lower(),
        )
    )
    customer = result.scalar_one_or_none()
    if not customer:
        return {"customer_id": None, "found": False}
    return {
        "customer_id": customer.id,
        "found": True,
        "company_name": customer.company_name,
        "contact_email": customer.contact_email,
    }


@router.get("", response_model=list[CustomerListResponse])
async def list_customers(
    user_org: tuple[int, int | None] = Depends(get_current_user_id_and_organization_id),
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
):
    """List customers for the current user's organization. Platform has many orgs; each org has many customers."""
    user_id, organization_id = user_org
    if organization_id is None:
        raise HTTPException(
            status_code=403,
            detail="You must belong to an organization to list customers",
        )
    result = await db.execute(
        select(Customer)
        .where(Customer.organization_id == organization_id)
        .order_by(Customer.updated_at.desc())
        .offset((page - 1) * limit)
        .limit(limit)
    )
    customers = result.scalars().all()
    return customers


@router.get("/{customer_id}", response_model=CustomerResponse)
async def get_customer(
    customer_id: int,
    user_org: tuple[int, int | None] = Depends(get_current_user_id_and_organization_id),
    db: AsyncSession = Depends(get_db),
):
    """Get one customer. Only if customer belongs to your organization."""
    user_id, organization_id = user_org
    if organization_id is None:
        raise HTTPException(status_code=403, detail="You must belong to an organization")
    result = await db.execute(
        select(Customer).where(
            Customer.id == customer_id,
            Customer.organization_id == organization_id,
        )
    )
    customer = result.scalar_one_or_none()
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    return customer


@router.post("", status_code=201, response_model=CustomerResponse)
async def create_customer(
    body: CustomerCreate,
    user_org: tuple[int, int | None] = Depends(get_current_user_id_and_organization_id),
    db: AsyncSession = Depends(get_db),
):
    """Create a customer in your organization. Every organization has its own customers."""
    user_id, organization_id = user_org
    if organization_id is None:
        raise HTTPException(
            status_code=403,
            detail="You must belong to an organization to create customers",
        )
    customer = Customer(
        user_id=user_id,
        organization_id=organization_id,
        company_name=body.company_name,
        contact_email=body.contact_email,
        default_origin_port=body.default_origin_port,
        default_destination_port=body.default_destination_port,
        preferences=body.preferences,
    )
    db.add(customer)
    await db.commit()
    await db.refresh(customer)
    return customer


@router.put("/{customer_id}", response_model=CustomerResponse)
async def update_customer(
    customer_id: int,
    body: CustomerUpdate,
    user_org: tuple[int, int | None] = Depends(get_current_user_id_and_organization_id),
    db: AsyncSession = Depends(get_db),
):
    """Update a customer. Only if customer belongs to your organization."""
    user_id, organization_id = user_org
    if organization_id is None:
        raise HTTPException(status_code=403, detail="You must belong to an organization")
    result = await db.execute(
        select(Customer).where(
            Customer.id == customer_id,
            Customer.organization_id == organization_id,
        )
    )
    customer = result.scalar_one_or_none()
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    if body.company_name is not None:
        customer.company_name = body.company_name
    if body.contact_email is not None:
        customer.contact_email = body.contact_email
    if body.default_origin_port is not None:
        customer.default_origin_port = body.default_origin_port
    if body.default_destination_port is not None:
        customer.default_destination_port = body.default_destination_port
    if body.preferences is not None:
        customer.preferences = body.preferences
    if body.password is not None and body.password != "":
        customer.password_hash = pwd_context.hash(body.password)
    await db.commit()
    await db.refresh(customer)
    return customer


@router.delete("/{customer_id}", status_code=204)
async def delete_customer(
    customer_id: int,
    user_org: tuple[int, int | None] = Depends(get_current_user_id_and_organization_id),
    db: AsyncSession = Depends(get_db),
):
    """Delete a customer. Only if customer belongs to your organization."""
    user_id, organization_id = user_org
    if organization_id is None:
        raise HTTPException(status_code=403, detail="You must belong to an organization")
    result = await db.execute(
        select(Customer).where(
            Customer.id == customer_id,
            Customer.organization_id == organization_id,
        )
    )
    customer = result.scalar_one_or_none()
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    await db.delete(customer)
    await db.commit()
    return None
