"""User profile service"""
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from typing import Optional, List
from datetime import datetime
from ..models import UserProfile
from ..core.database import AsyncSessionLocal
from ..models.user_profile import Department


async def get_or_create_user_profile(auth_user_id: int, email: str, first_name: Optional[str] = None,
                                     last_name: Optional[str] = None, department: Optional[str] = None,
                                     signature: Optional[str] = None) -> UserProfile:
    """Get or create user profile"""
    async with AsyncSessionLocal() as session:
        # Check if profile exists
        result = await session.execute(
            select(UserProfile).where(
                and_(
                    UserProfile.auth_user_id == auth_user_id,
                    UserProfile.deleted_at.is_(None)  # Exclude soft-deleted
                )
            )
        )
        profile = result.scalar_one_or_none()
        
        if profile:
            # Update fields if changed
            if profile.email != email:
                profile.email = email
            if first_name and profile.first_name != first_name:
                profile.first_name = first_name
            if last_name and profile.last_name != last_name:
                profile.last_name = last_name
            if department:
                try:
                    profile.department = Department(department.lower())
                except ValueError:
                    pass
            if signature is not None:
                profile.signature = signature
            await session.commit()
            await session.refresh(profile)
            return profile
        
        # Parse department enum if provided
        department_enum = None
        if department:
            try:
                department_enum = Department(department.lower())
            except ValueError:
                pass
        
        # Create new profile
        profile = UserProfile(
            auth_user_id=auth_user_id,
            email=email,
            first_name=first_name,
            last_name=last_name,
            department=department_enum,
            signature=signature,
            is_enabled=True,
        )
        session.add(profile)
        await session.commit()
        await session.refresh(profile)
        return profile


async def get_user_profile(auth_user_id: int, include_deleted: bool = False) -> Optional[UserProfile]:
    """Get user profile by auth user ID"""
    async with AsyncSessionLocal() as session:
        query = select(UserProfile).where(UserProfile.auth_user_id == auth_user_id)
        if not include_deleted:
            query = query.where(UserProfile.deleted_at.is_(None))
        result = await session.execute(query)
        return result.scalar_one_or_none()


async def get_user_profile_by_id(profile_id: int, include_deleted: bool = False) -> Optional[UserProfile]:
    """Get user profile by profile ID"""
    async with AsyncSessionLocal() as session:
        query = select(UserProfile).where(UserProfile.id == profile_id)
        if not include_deleted:
            query = query.where(UserProfile.deleted_at.is_(None))
        result = await session.execute(query)
        return result.scalar_one_or_none()


async def get_user_profile_by_email(email: str, include_deleted: bool = False) -> Optional[UserProfile]:
    """Get user profile by email"""
    async with AsyncSessionLocal() as session:
        query = select(UserProfile).where(UserProfile.email == email)
        if not include_deleted:
            query = query.where(UserProfile.deleted_at.is_(None))
        result = await session.execute(query)
        return result.scalar_one_or_none()


async def update_user_profile(profile_id: int, **kwargs) -> Optional[UserProfile]:
    """Update user profile"""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(UserProfile).where(
                and_(
                    UserProfile.id == profile_id,
                    UserProfile.deleted_at.is_(None)  # Can't update deleted users
                )
            )
        )
        profile = result.scalar_one_or_none()
        
        if not profile:
            return None
        
        # Update fields
        if 'first_name' in kwargs and kwargs['first_name'] is not None:
            profile.first_name = kwargs['first_name']
        if 'last_name' in kwargs and kwargs['last_name'] is not None:
            profile.last_name = kwargs['last_name']
        if 'phone' in kwargs and kwargs['phone'] is not None:
            profile.phone = kwargs['phone']
        if 'avatar_url' in kwargs and kwargs['avatar_url'] is not None:
            profile.avatar_url = kwargs['avatar_url']
        if 'bio' in kwargs and kwargs['bio'] is not None:
            profile.bio = kwargs['bio']
        if 'department' in kwargs and kwargs['department'] is not None:
            try:
                profile.department = Department(kwargs['department'].lower())
            except ValueError:
                raise ValueError(f"Invalid department: {kwargs['department']}")
        if 'signature' in kwargs and kwargs['signature'] is not None:
            profile.signature = kwargs['signature']
        if 'is_enabled' in kwargs and kwargs['is_enabled'] is not None:
            profile.is_enabled = kwargs['is_enabled']
        
        await session.commit()
        await session.refresh(profile)
        return profile


async def enable_user(profile_id: int) -> bool:
    """Enable a user"""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(UserProfile).where(
                and_(
                    UserProfile.id == profile_id,
                    UserProfile.deleted_at.is_(None)
                )
            )
        )
        profile = result.scalar_one_or_none()
        
        if not profile:
            return False
        
        profile.is_enabled = True
        await session.commit()
        return True


async def disable_user(profile_id: int) -> bool:
    """Disable a user"""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(UserProfile).where(
                and_(
                    UserProfile.id == profile_id,
                    UserProfile.deleted_at.is_(None)
                )
            )
        )
        profile = result.scalar_one_or_none()
        
        if not profile:
            return False
        
        profile.is_enabled = False
        await session.commit()
        return True


async def soft_delete_user(profile_id: int) -> bool:
    """Soft delete a user (audit-safe)"""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(UserProfile).where(UserProfile.id == profile_id)
        )
        profile = result.scalar_one_or_none()
        
        if not profile:
            return False
        
        profile.deleted_at = datetime.utcnow()
        profile.is_enabled = False  # Also disable when deleted
        await session.commit()
        return True


async def restore_user(profile_id: int) -> bool:
    """Restore a soft-deleted user"""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(UserProfile).where(UserProfile.id == profile_id)
        )
        profile = result.scalar_one_or_none()
        
        if not profile or profile.deleted_at is None:
            return False
        
        profile.deleted_at = None
        profile.is_enabled = True
        await session.commit()
        return True


async def list_user_profiles(organization_id: Optional[int] = None, include_deleted: bool = False) -> List[UserProfile]:
    """List user profiles, optionally filtered by organization"""
    from ..models import UserOrganization
    
    async with AsyncSessionLocal() as session:
        if organization_id:
            # Get users in organization
            result = await session.execute(
                select(UserProfile)
                .join(UserOrganization, UserProfile.id == UserOrganization.user_profile_id)
                .where(
                    and_(
                        UserOrganization.organization_id == organization_id,
                        UserOrganization.is_active == True
                    )
                )
            )
        else:
            # Get all users
            query = select(UserProfile)
            if not include_deleted:
                query = query.where(UserProfile.deleted_at.is_(None))
            result = await session.execute(query)
        
        return list(result.scalars().all())
