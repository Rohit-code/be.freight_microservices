"""Organization service"""
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from sqlalchemy.orm import selectinload
from typing import List, Optional
from datetime import datetime, timedelta
from ..models import Organization, UserProfile, UserOrganization, Role, Invitation
from ..core.database import AsyncSessionLocal
import re
import logging

logger = logging.getLogger(__name__)


def slugify(text: str) -> str:
    """Convert text to URL-friendly slug"""
    text = text.lower().strip()
    text = re.sub(r'[^\w\s-]', '', text)
    text = re.sub(r'[-\s]+', '-', text)
    return text


async def create_organization(name: str, domain: str, admin_email: str, 
                             slug: Optional[str] = None, description: Optional[str] = None,
                             website: Optional[str] = None,
                             industry_type: Optional[str] = None,
                             timezone: Optional[str] = "UTC",
                             default_currency: Optional[str] = "USD",
                             emails_per_day_limit: Optional[int] = None,
                             ai_usage_limit: Optional[int] = None,
                             created_by_user_id: int = None) -> Organization:
    """Create a new organization"""
    from ..models.organization import IndustryType, OrganizationStatus
    
    async with AsyncSessionLocal() as session:
        # Check if organization with same domain already exists
        result = await session.execute(
            select(Organization).where(Organization.domain == domain.lower())
        )
        if result.scalar_one_or_none():
            raise ValueError(f"Organization with domain '{domain}' already exists")
        
        # Generate slug if not provided
        if not slug:
            base_slug = slugify(name)
            slug = base_slug
            counter = 1
            while True:
                result = await session.execute(
                    select(Organization).where(Organization.slug == slug)
                )
                if result.scalar_one_or_none() is None:
                    break
                slug = f"{base_slug}-{counter}"
                counter += 1
        
        # Check if slug already exists
        result = await session.execute(
            select(Organization).where(Organization.slug == slug)
        )
        if result.scalar_one_or_none():
            raise ValueError(f"Organization with slug '{slug}' already exists")
        
        # Parse industry_type enum if provided
        industry_type_enum = None
        if industry_type:
            try:
                industry_type_enum = IndustryType(industry_type.lower())
            except ValueError:
                raise ValueError(f"Invalid industry_type: {industry_type}. Must be one of: freight_forwarder, cha, exporter")
        
        organization = Organization(
            name=name,
            slug=slug,
            description=description,
            domain=domain.lower(),
            admin_email=admin_email.lower(),
            website=website,
            industry_type=industry_type_enum,
            timezone=timezone,
            default_currency=default_currency,
            status=OrganizationStatus.ACTIVE,
            is_active=True,
            emails_per_day_limit=emails_per_day_limit,
            ai_usage_limit=ai_usage_limit,
        )
        
        session.add(organization)
        await session.commit()
        await session.refresh(organization)
        
        # Add creator as admin if user_id provided
        if created_by_user_id:
            await add_user_to_organization(
                user_profile_id=created_by_user_id,
                organization_id=organization.id,
                role_name="admin"
            )
        
        return organization


async def update_organization(organization_id: int, **kwargs) -> Optional[Organization]:
    """Update organization settings"""
    from ..models.organization import IndustryType, OrganizationStatus
    
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Organization).where(Organization.id == organization_id)
        )
        organization = result.scalar_one_or_none()
        
        if not organization:
            return None
        
        # Update fields
        if 'name' in kwargs and kwargs['name'] is not None:
            organization.name = kwargs['name']
        if 'description' in kwargs and kwargs['description'] is not None:
            organization.description = kwargs['description']
        if 'website' in kwargs and kwargs['website'] is not None:
            organization.website = kwargs['website']
        if 'logo_url' in kwargs and kwargs['logo_url'] is not None:
            organization.logo_url = kwargs['logo_url']
        if 'industry_type' in kwargs and kwargs['industry_type'] is not None:
            try:
                organization.industry_type = IndustryType(kwargs['industry_type'].lower())
            except ValueError:
                raise ValueError(f"Invalid industry_type: {kwargs['industry_type']}")
        if 'timezone' in kwargs and kwargs['timezone'] is not None:
            organization.timezone = kwargs['timezone']
        if 'default_currency' in kwargs and kwargs['default_currency'] is not None:
            organization.default_currency = kwargs['default_currency']
        if 'status' in kwargs and kwargs['status'] is not None:
            try:
                organization.status = OrganizationStatus(kwargs['status'].lower())
                organization.is_active = (kwargs['status'].lower() == 'active')
            except ValueError:
                raise ValueError(f"Invalid status: {kwargs['status']}")
        if 'emails_per_day_limit' in kwargs:
            organization.emails_per_day_limit = kwargs['emails_per_day_limit']
        if 'ai_usage_limit' in kwargs:
            organization.ai_usage_limit = kwargs['ai_usage_limit']
        if 'auto_send_threshold' in kwargs and kwargs['auto_send_threshold'] is not None:
            organization.auto_send_threshold = kwargs['auto_send_threshold']
        if 'manual_review_threshold' in kwargs and kwargs['manual_review_threshold'] is not None:
            organization.manual_review_threshold = kwargs['manual_review_threshold']
        if 'vip_auto_review' in kwargs and kwargs['vip_auto_review'] is not None:
            organization.vip_auto_review = kwargs['vip_auto_review']
        if 'proactive_delay_notifications' in kwargs and kwargs['proactive_delay_notifications'] is not None:
            organization.proactive_delay_notifications = kwargs['proactive_delay_notifications']
        
        await session.commit()
        await session.refresh(organization)
        return organization


async def get_organization(organization_id: int) -> Optional[Organization]:
    """Get organization by ID"""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Organization).where(Organization.id == organization_id)
        )
        return result.scalar_one_or_none()


async def get_organization_by_slug(slug: str) -> Optional[Organization]:
    """Get organization by slug"""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Organization).where(Organization.slug == slug)
        )
        return result.scalar_one_or_none()


async def get_all_organizations() -> List[Organization]:
    """Get all organizations (admin only)"""
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Organization))
        organizations = result.scalars().all()
        return list(organizations)


async def get_user_organizations(user_profile_id: int) -> List[UserOrganization]:
    """Get all organizations for a user"""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(UserOrganization)
            .options(selectinload(UserOrganization.organization))
            .where(
                and_(
                    UserOrganization.user_profile_id == user_profile_id,
                    UserOrganization.is_active == True
                )
            )
        )
        return list(result.scalars().all())


async def get_all_organizations() -> List[Organization]:
    """Get all organizations (admin only)"""
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Organization))
        organizations = result.scalars().all()
        return list(organizations)


async def get_organization_users(organization_id: int) -> List[UserOrganization]:
    """Get all users in an organization"""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(UserOrganization)
            .options(
                selectinload(UserOrganization.user_profile),
                selectinload(UserOrganization.role)
            )
            .where(
                and_(
                    UserOrganization.organization_id == organization_id,
                    UserOrganization.is_active == True
                )
            )
        )
        return list(result.scalars().all())


async def get_user_role_in_organization(user_profile_id: int, organization_id: int) -> Optional[str]:
    """Get user's role name in an organization"""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(UserOrganization)
            .options(selectinload(UserOrganization.role))
            .where(
                and_(
                    UserOrganization.user_profile_id == user_profile_id,
                    UserOrganization.organization_id == organization_id,
                    UserOrganization.is_active == True
                )
            )
        )
        user_org = result.scalar_one_or_none()
        if user_org:
            return user_org.role.name
        return None


async def is_user_admin(user_profile_id: int, organization_id: int) -> bool:
    """Check if user is admin in organization"""
    role_name = await get_user_role_in_organization(user_profile_id, organization_id)
    return role_name == "admin"


async def add_user_to_organization(user_profile_id: int, organization_id: int, role_name: str) -> UserOrganization:
    """Add user to organization with a role"""
    async with AsyncSessionLocal() as session:
        # Get role
        result = await session.execute(
            select(Role).where(Role.name == role_name)
        )
        role = result.scalar_one_or_none()
        if not role:
            raise ValueError(f"Role '{role_name}' not found")
        
        # Check if user already in organization
        result = await session.execute(
            select(UserOrganization).where(
                and_(
                    UserOrganization.user_profile_id == user_profile_id,
                    UserOrganization.organization_id == organization_id
                )
            )
        )
        existing = result.scalar_one_or_none()
        
        if existing:
            # Update role
            existing.role_id = role.id
            existing.is_active = True
            await session.commit()
            await session.refresh(existing)
            return existing
        
        # Create new user-organization relationship
        user_org = UserOrganization(
            user_profile_id=user_profile_id,
            organization_id=organization_id,
            role_id=role.id,
        )
        session.add(user_org)
        await session.commit()
        await session.refresh(user_org)
        return user_org
