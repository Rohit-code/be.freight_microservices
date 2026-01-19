from fastapi import APIRouter, HTTPException, Header, Query, Request
from typing import Optional, List
import httpx
import logging

logger = logging.getLogger(__name__)
from ..schemas import (
    OrganizationCreate,
    OrganizationUpdate,
    OrganizationOut,
    OrganizationWithUsers,
    InvitationCreate,
    InvitationOut,
    InvitationResponse,
    UserOrganizationOut,
    UserProfileOut,
    UserProfileUpdate,
    RoleOut,
    EmailSettingsUpdate,
)
from ..services.auth_service import verify_token_and_get_user, get_user_id_from_token
from ..services.organization_service import (
    create_organization,
    update_organization,
    get_organization,
    get_organization_by_slug,
    get_user_organizations,
    get_all_organizations,
    get_organization_users,
    is_user_admin,
    add_user_to_organization,
)
from ..services.user_profile_service import (
    get_or_create_user_profile,
    get_user_profile,
    get_user_profile_by_id,
    update_user_profile,
    enable_user,
    disable_user,
    soft_delete_user,
    restore_user,
    list_user_profiles,
)
from ..services.invitation_service import create_invitation, get_invitation_by_token, accept_invitation
from ..models import Role
from ..core.database import AsyncSessionLocal
from sqlalchemy import select
from ..core.config import settings

router = APIRouter(prefix="/api/user", tags=["user"])


async def get_current_user_profile(authorization: str):
    """Helper to get current user profile from token"""
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=403, detail="Authorization header missing or invalid")
    
    token = authorization.replace("Bearer ", "")
    auth_data = await verify_token_and_get_user(token)
    
    if not auth_data or not auth_data.get('user'):
        raise HTTPException(status_code=401, detail="Invalid authentication token")
    
    return auth_data['user']


# Organization Endpoints
@router.post("/organizations", response_model=OrganizationOut)
async def create_organization_endpoint(
    payload: OrganizationCreate,
    authorization: str = Header(default="")
):
    """Create a new organization - user can only belong to ONE organization"""
    user = await get_current_user_profile(authorization)
    auth_user_id = int(user['id'])
    
    # Create user profile if doesn't exist
    user_profile = await get_or_create_user_profile(
        auth_user_id=auth_user_id,
        email=user['email'],
        first_name=user.get('name', '').split()[0] if user.get('name') else None,
        last_name=' '.join(user.get('name', '').split()[1:]) if user.get('name') else None,
    )
    
    # Check if user already belongs to an organization
    existing_orgs = await get_user_organizations(user_profile.id)
    if existing_orgs:
        raise HTTPException(
            status_code=400, 
            detail="You already belong to an organization. Users can only be part of one organization."
        )
    
    # Create organization
    try:
        organization = await create_organization(
            name=payload.name,
            domain=payload.domain,
            admin_email=payload.admin_email,
            slug=payload.slug,
            description=payload.description,
            website=payload.website,
            industry_type=payload.industry_type.value if payload.industry_type else None,
            timezone=payload.timezone,
            default_currency=payload.default_currency,
            emails_per_day_limit=payload.emails_per_day_limit,
            ai_usage_limit=payload.ai_usage_limit,
            created_by_user_id=user_profile.id
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    return organization


@router.get("/organizations", response_model=List[OrganizationOut])
async def list_user_organizations(
    authorization: str = Header(default="")
):
    """Get all organizations for current user"""
    user = await get_current_user_profile(authorization)
    auth_user_id = int(user['id'])
    
    user_profile = await get_user_profile(auth_user_id)
    if not user_profile:
        return []
    
    user_orgs = await get_user_organizations(user_profile.id)
    return [uo.organization for uo in user_orgs]


@router.get("/admin/organizations", response_model=List[OrganizationOut])
async def list_all_organizations_admin(
    authorization: str = Header(default="")
):
    """Get all organizations (admin/superuser only)"""
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=403, detail="Authorization header missing or invalid")
    
    token = authorization.replace("Bearer ", "")
    
    # Verify admin status
    if not await verify_admin_access(token):
        raise HTTPException(
            status_code=403,
            detail="Admin access required. Only staff or superuser accounts can access this endpoint."
        )
    
    # Get all organizations
    all_orgs = await get_all_organizations()
    return all_orgs


async def verify_admin_access(token: str) -> bool:
    """Verify if user has admin access"""
    try:
        async with httpx.AsyncClient() as client:
            auth_response = await client.get(
                f"{settings.AUTH_SERVICE_URL}/api/auth/admin",
                headers={"Authorization": f"Bearer {token}"},
                timeout=10.0
            )
            if auth_response.status_code == 200:
                return True
            else:
                logger.warning(f"Admin check failed: {auth_response.status_code}")
                return False
    except httpx.RequestError as e:
        logger.error(f"Error verifying admin access: {str(e)}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error verifying admin access: {str(e)}")
        return False


@router.get("/organizations/{organization_id}", response_model=OrganizationWithUsers)
async def get_organization_endpoint(
    organization_id: int,
    authorization: str = Header(default="")
):
    """Get organization details with users"""
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=403, detail="Authorization header missing or invalid")
    
    token = authorization.replace("Bearer ", "")
    
    # Check if user is admin - if so, allow access to any organization
    is_admin = await verify_admin_access(token)
    
    organization = await get_organization(organization_id)
    if not organization:
        raise HTTPException(status_code=404, detail="Organization not found")
    
    # If admin, skip user profile checks and allow access
    if is_admin:
        # Admin can access any organization, proceed to get users
        pass
    else:
        # For non-admin users, verify they are members
        user = await get_current_user_profile(authorization)
        auth_user_id = int(user['id'])
        
        user_profile = await get_user_profile(auth_user_id)
        if not user_profile:
            raise HTTPException(status_code=404, detail="User profile not found")
        
        user_orgs = await get_user_organizations(user_profile.id)
        if not any(uo.organization_id == organization_id for uo in user_orgs):
            raise HTTPException(status_code=403, detail="You are not a member of this organization")
    
    # Get all users
    org_users = await get_organization_users(organization_id)
    
    # Convert user organizations to response format
    users_out = []
    for uo in org_users:
        user_org_out = UserOrganizationOut(
            id=uo.id,
            user_profile_id=uo.user_profile_id,
            organization_id=uo.organization_id,
            role_id=uo.role_id,
            is_active=uo.is_active,
            joined_at=uo.joined_at,
            created_at=uo.created_at,
            updated_at=uo.updated_at,
            user_profile=UserProfileOut(
                id=uo.user_profile.id,
                auth_user_id=uo.user_profile.auth_user_id,
                email=uo.user_profile.email,
                first_name=uo.user_profile.first_name,
                last_name=uo.user_profile.last_name,
                phone=uo.user_profile.phone,
                avatar_url=uo.user_profile.avatar_url,
                bio=uo.user_profile.bio,
                department=uo.user_profile.department.value if uo.user_profile.department else None,
                signature=uo.user_profile.signature,
                is_enabled=uo.user_profile.is_enabled,
                deleted_at=uo.user_profile.deleted_at,
                created_at=uo.user_profile.created_at,
                updated_at=uo.user_profile.updated_at,
            ) if uo.user_profile else None,
            role=RoleOut(
                id=uo.role.id,
                name=uo.role.name,
                display_name=uo.role.display_name,
                description=uo.role.description,
                created_at=uo.role.created_at,
                updated_at=uo.role.updated_at,
            ) if uo.role else None,
        )
        users_out.append(user_org_out)
    
    return OrganizationWithUsers(
        id=organization.id,
        name=organization.name,
        slug=organization.slug,
        description=organization.description,
        domain=organization.domain,
        admin_email=organization.admin_email,
        logo_url=organization.logo_url,
        website=organization.website,
        industry_type=organization.industry_type.value if organization.industry_type else None,
        timezone=organization.timezone,
        default_currency=organization.default_currency,
        status=organization.status.value if organization.status else "active",
        is_active=organization.is_active,
        emails_per_day_limit=organization.emails_per_day_limit,
        ai_usage_limit=organization.ai_usage_limit,
        auto_send_threshold=organization.auto_send_threshold,
        manual_review_threshold=organization.manual_review_threshold,
        vip_auto_review=organization.vip_auto_review,
        proactive_delay_notifications=organization.proactive_delay_notifications,
        created_at=organization.created_at,
        updated_at=organization.updated_at,
        users=users_out
    )


# Invitation Endpoints
@router.post("/organizations/{organization_id}/invitations", response_model=InvitationResponse)
async def invite_user(
    organization_id: int,
    payload: InvitationCreate,
    authorization: str = Header(default="")
):
    """Invite a user to organization (admin only)"""
    user = await get_current_user_profile(authorization)
    auth_user_id = int(user['id'])
    
    user_profile = await get_user_profile(auth_user_id)
    if not user_profile:
        raise HTTPException(status_code=404, detail="User profile not found")
    
    # Check if user is admin
    if not await is_user_admin(user_profile.id, organization_id):
        raise HTTPException(status_code=403, detail="Only admins can invite users")
    
    # Create invitation
    invitation = await create_invitation(
        organization_id=organization_id,
        invited_by_user_id=user_profile.id,
        email=payload.email,
        role_id=payload.role_id
    )
    
    invitation_link = f"{settings.FRONTEND_URL}/invite/accept?token={invitation.token}"
    
    return InvitationResponse(
        invitation=invitation,
        invitation_link=invitation_link,
        message=f"Invitation sent to {payload.email}"
    )


@router.get("/invitations/{token}", response_model=InvitationOut)
async def get_invitation(
    token: str
):
    """Get invitation details by token"""
    invitation = await get_invitation_by_token(token)
    if not invitation:
        raise HTTPException(status_code=404, detail="Invitation not found")
    
    return invitation


@router.post("/invitations/{token}/accept")
async def accept_invitation_endpoint(
    token: str,
    authorization: str = Header(default="")
):
    """Accept an invitation"""
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=403, detail="Authorization header missing or invalid")
    
    jwt_token = authorization.replace("Bearer ", "")
    
    invitation = await accept_invitation(token, jwt_token)
    
    return {
        "message": "Invitation accepted successfully",
        "organization_id": invitation.organization_id,
        "invitation": invitation
    }


# Role Endpoints
@router.get("/roles", response_model=List[RoleOut])
async def list_roles():
    """Get all available roles"""
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Role))
        roles = list(result.scalars().all())
        return roles


# User Organization Endpoints
@router.get("/organizations/{organization_id}/users", response_model=List[UserOrganizationOut])
async def list_organization_users(
    organization_id: int,
    authorization: str = Header(default="")
):
    """List all users in an organization"""
    user = await get_current_user_profile(authorization)
    auth_user_id = int(user['id'])
    
    user_profile = await get_user_profile(auth_user_id)
    if not user_profile:
        raise HTTPException(status_code=404, detail="User profile not found")
    
    # Check if user is member
    user_orgs = await get_user_organizations(user_profile.id)
    if not any(uo.organization_id == organization_id for uo in user_orgs):
        raise HTTPException(status_code=403, detail="You are not a member of this organization")
    
    org_users = await get_organization_users(organization_id)
    return org_users


# Organization Update Endpoint
@router.patch("/organizations/{organization_id}", response_model=OrganizationOut)
async def update_organization_endpoint(
    organization_id: int,
    payload: OrganizationUpdate,
    authorization: str = Header(default="")
):
    """Update organization settings (admin only)"""
    user = await get_current_user_profile(authorization)
    auth_user_id = int(user['id'])
    
    user_profile = await get_user_profile(auth_user_id)
    if not user_profile:
        raise HTTPException(status_code=404, detail="User profile not found")
    
    # Check if user is admin
    if not await is_user_admin(user_profile.id, organization_id):
        raise HTTPException(status_code=403, detail="Only admins can update organization settings")
    
    # Update organization
    update_data = payload.model_dump(exclude_unset=True)
    if 'industry_type' in update_data and update_data['industry_type']:
        update_data['industry_type'] = update_data['industry_type'].value if hasattr(update_data['industry_type'], 'value') else update_data['industry_type']
    if 'status' in update_data and update_data['status']:
        update_data['status'] = update_data['status'].value if hasattr(update_data['status'], 'value') else update_data['status']
    
    organization = await update_organization(organization_id, **update_data)
    if not organization:
        raise HTTPException(status_code=404, detail="Organization not found")
    
    return organization


@router.patch("/organizations/{organization_id}/email-settings")
async def update_email_settings_endpoint(
    organization_id: int,
    payload: EmailSettingsUpdate,
    authorization: str = Header(default="")
):
    """Update email settings for organization and user signature (admin only)"""
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=403, detail="Authorization header missing or invalid")
    
    token = authorization.replace("Bearer ", "")
    
    # Check if user is superuser admin (can manage any organization)
    is_superuser_admin = await verify_admin_access(token)
    
    user = await get_current_user_profile(authorization)
    auth_user_id = int(user['id'])
    
    user_profile = await get_user_profile(auth_user_id)
    
    # If no profile exists and user is superuser admin, auto-create one
    if not user_profile:
        if is_superuser_admin:
            user_email = user.get('email', '')
            user_name = user.get('name', '')
            first_name = None
            last_name = None
            if user_name:
                name_parts = user_name.split(maxsplit=1)
                first_name = name_parts[0] if name_parts else None
                last_name = name_parts[1] if len(name_parts) > 1 else None
            
            user_profile = await get_or_create_user_profile(
                auth_user_id=auth_user_id,
                email=user_email,
                first_name=first_name,
                last_name=last_name
            )
        else:
            raise HTTPException(status_code=404, detail="User profile not found")
    
    # Check if user is admin of organization OR superuser admin
    if not is_superuser_admin and not await is_user_admin(user_profile.id, organization_id):
        raise HTTPException(status_code=403, detail="Only admins can update email settings")
    
    # Extract email signature from payload
    email_signature = payload.email_signature
    update_data = payload.model_dump(exclude_unset=True, exclude={'email_signature'})
    
    # Update organization email settings
    organization = None
    if update_data:
        organization = await update_organization(organization_id, **update_data)
        if not organization:
            raise HTTPException(status_code=404, detail="Organization not found")
    else:
        organization = await get_organization(organization_id)
        if not organization:
            raise HTTPException(status_code=404, detail="Organization not found")
    
    # Update user signature if provided
    signature_updated = False
    if email_signature is not None:
        await update_user_profile(user_profile.id, signature=email_signature)
        signature_updated = True
    
    return {
        "message": "Email settings updated successfully",
        "organization": organization,
        "signature_updated": signature_updated
    }


# User Profile Endpoints
@router.get("/profiles/me", response_model=UserProfileOut)
async def get_my_profile(
    authorization: str = Header(default="")
):
    """Get current user's profile"""
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=403, detail="Authorization header missing or invalid")
    
    token = authorization.replace("Bearer ", "")
    
    # Check if user is admin
    is_admin = await verify_admin_access(token)
    
    user = await get_current_user_profile(authorization)
    auth_user_id = int(user['id'])
    
    user_profile = await get_user_profile(auth_user_id)
    
    # If no profile exists
    if not user_profile:
        # For admin users, auto-create a profile
        if is_admin:
            user_email = user.get('email', '')
            user_name = user.get('name', '')
            first_name = None
            last_name = None
            if user_name:
                name_parts = user_name.split(maxsplit=1)
                first_name = name_parts[0] if name_parts else None
                last_name = name_parts[1] if len(name_parts) > 1 else None
            
            user_profile = await get_or_create_user_profile(
                auth_user_id=auth_user_id,
                email=user_email,
                first_name=first_name,
                last_name=last_name
            )
        else:
            raise HTTPException(status_code=404, detail="User profile not found")
    
    return user_profile


@router.patch("/profiles/{profile_id}", response_model=UserProfileOut)
async def update_user_profile_endpoint(
    profile_id: int,
    payload: UserProfileUpdate,
    authorization: str = Header(default="")
):
    """Update user profile (admin or self)"""
    user = await get_current_user_profile(authorization)
    auth_user_id = int(user['id'])
    
    current_profile = await get_user_profile(auth_user_id)
    if not current_profile:
        raise HTTPException(status_code=404, detail="User profile not found")
    
    # Check if updating self or admin
    target_profile = await get_user_profile_by_id(profile_id)
    if not target_profile:
        raise HTTPException(status_code=404, detail="Target user profile not found")
    
    # Only allow self-update or admin update
    if current_profile.id != profile_id:
        # Check if current user is admin in any org that target user belongs to
        current_user_orgs = await get_user_organizations(current_profile.id)
        target_user_orgs = await get_user_organizations(target_profile.id)
        
        is_admin = False
        for uo in current_user_orgs:
            if await is_user_admin(current_profile.id, uo.organization_id):
                # Check if target user is in same org
                if any(tuo.organization_id == uo.organization_id for tuo in target_user_orgs):
                    is_admin = True
                    break
        
        if not is_admin:
            raise HTTPException(status_code=403, detail="Only admins can update other users")
    
    # Update profile
    update_data = payload.model_dump(exclude_unset=True)
    if 'department' in update_data and update_data['department']:
        update_data['department'] = update_data['department'].value if hasattr(update_data['department'], 'value') else update_data['department']
    
    updated_profile = await update_user_profile(profile_id, **update_data)
    if not updated_profile:
        raise HTTPException(status_code=404, detail="User profile not found")
    
    return updated_profile


@router.post("/profiles/{profile_id}/enable")
async def enable_user_endpoint(
    profile_id: int,
    authorization: str = Header(default="")
):
    """Enable a user (admin only)"""
    user = await get_current_user_profile(authorization)
    auth_user_id = int(user['id'])
    
    current_profile = await get_user_profile(auth_user_id)
    if not current_profile:
        raise HTTPException(status_code=404, detail="User profile not found")
    
    # Check if admin
    target_profile = await get_user_profile_by_id(profile_id)
    if not target_profile:
        raise HTTPException(status_code=404, detail="Target user profile not found")
    
    current_user_orgs = await get_user_organizations(current_profile.id)
    target_user_orgs = await get_user_organizations(target_profile.id)
    
    is_admin = False
    for uo in current_user_orgs:
        if await is_user_admin(current_profile.id, uo.organization_id):
            if any(tuo.organization_id == uo.organization_id for tuo in target_user_orgs):
                is_admin = True
                break
    
    if not is_admin:
        raise HTTPException(status_code=403, detail="Only admins can enable users")
    
    success = await enable_user(profile_id)
    if not success:
        raise HTTPException(status_code=404, detail="User profile not found")
    
    return {"message": "User enabled successfully", "profile_id": profile_id}


@router.post("/profiles/{profile_id}/disable")
async def disable_user_endpoint(
    profile_id: int,
    authorization: str = Header(default="")
):
    """Disable a user (admin only)"""
    user = await get_current_user_profile(authorization)
    auth_user_id = int(user['id'])
    
    current_profile = await get_user_profile(auth_user_id)
    if not current_profile:
        raise HTTPException(status_code=404, detail="User profile not found")
    
    # Check if admin
    target_profile = await get_user_profile_by_id(profile_id)
    if not target_profile:
        raise HTTPException(status_code=404, detail="Target user profile not found")
    
    current_user_orgs = await get_user_organizations(current_profile.id)
    target_user_orgs = await get_user_organizations(target_profile.id)
    
    is_admin = False
    for uo in current_user_orgs:
        if await is_user_admin(current_profile.id, uo.organization_id):
            if any(tuo.organization_id == uo.organization_id for tuo in target_user_orgs):
                is_admin = True
                break
    
    if not is_admin:
        raise HTTPException(status_code=403, detail="Only admins can disable users")
    
    success = await disable_user(profile_id)
    if not success:
        raise HTTPException(status_code=404, detail="User profile not found")
    
    return {"message": "User disabled successfully", "profile_id": profile_id}


@router.delete("/profiles/{profile_id}")
async def delete_user_endpoint(
    profile_id: int,
    authorization: str = Header(default="")
):
    """Soft delete a user (admin only, audit-safe)"""
    user = await get_current_user_profile(authorization)
    auth_user_id = int(user['id'])
    
    current_profile = await get_user_profile(auth_user_id)
    if not current_profile:
        raise HTTPException(status_code=404, detail="User profile not found")
    
    # Check if admin
    target_profile = await get_user_profile_by_id(profile_id)
    if not target_profile:
        raise HTTPException(status_code=404, detail="Target user profile not found")
    
    current_user_orgs = await get_user_organizations(current_profile.id)
    target_user_orgs = await get_user_organizations(target_profile.id)
    
    is_admin = False
    shared_organization_id = None
    for uo in current_user_orgs:
        if await is_user_admin(current_profile.id, uo.organization_id):
            if any(tuo.organization_id == uo.organization_id for tuo in target_user_orgs):
                is_admin = True
                shared_organization_id = uo.organization_id
                break
    
    if not is_admin:
        raise HTTPException(status_code=403, detail="Only admins can delete users")
    
    # Prevent deleting the last user in the organization
    if shared_organization_id:
        org_users = await get_organization_users(shared_organization_id)
        # Filter out soft-deleted users
        active_users = [
            uo for uo in org_users 
            if uo.user_profile and uo.user_profile.deleted_at is None
        ]
        
        if len(active_users) <= 1:
            raise HTTPException(
                status_code=400, 
                detail="Cannot delete the last user in the organization. Please invite another member first."
            )
    
    success = await soft_delete_user(profile_id)
    if not success:
        raise HTTPException(status_code=404, detail="User profile not found")
    
    return {"message": "User deleted successfully (soft delete)", "profile_id": profile_id}


@router.post("/profiles/{profile_id}/restore")
async def restore_user_endpoint(
    profile_id: int,
    authorization: str = Header(default="")
):
    """Restore a soft-deleted user (admin only)"""
    user = await get_current_user_profile(authorization)
    auth_user_id = int(user['id'])
    
    current_profile = await get_user_profile(auth_user_id)
    if not current_profile:
        raise HTTPException(status_code=404, detail="User profile not found")
    
    # Check if admin (need to check with include_deleted=True)
    target_profile = await get_user_profile_by_id(profile_id, include_deleted=True)
    if not target_profile:
        raise HTTPException(status_code=404, detail="Target user profile not found")
    
    current_user_orgs = await get_user_organizations(current_profile.id)
    target_user_orgs = await get_user_organizations(target_profile.id)
    
    is_admin = False
    for uo in current_user_orgs:
        if await is_user_admin(current_profile.id, uo.organization_id):
            if any(tuo.organization_id == uo.organization_id for tuo in target_user_orgs):
                is_admin = True
                break
    
    if not is_admin:
        raise HTTPException(status_code=403, detail="Only admins can restore users")
    
    success = await restore_user(profile_id)
    if not success:
        raise HTTPException(status_code=400, detail="User is not deleted or restore failed")
    
    return {"message": "User restored successfully", "profile_id": profile_id}


@router.get("/organizations/{organization_id}/profiles", response_model=List[UserProfileOut])
async def list_organization_profiles(
    organization_id: int,
    authorization: str = Header(default=""),
    include_deleted: bool = Query(default=False)
):
    """List all user profiles in an organization"""
    user = await get_current_user_profile(authorization)
    auth_user_id = int(user['id'])
    
    user_profile = await get_user_profile(auth_user_id)
    if not user_profile:
        raise HTTPException(status_code=404, detail="User profile not found")
    
    # Check if user is member
    user_orgs = await get_user_organizations(user_profile.id)
    if not any(uo.organization_id == organization_id for uo in user_orgs):
        raise HTTPException(status_code=403, detail="You are not a member of this organization")
    
    profiles = await list_user_profiles(organization_id=organization_id, include_deleted=include_deleted)
    return profiles
