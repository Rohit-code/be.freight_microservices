"""Invitation service"""
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from typing import Optional, List
from datetime import datetime, timedelta
import httpx
from ..models import Invitation, Organization, UserProfile, Role, UserOrganization
from ..core.database import AsyncSessionLocal
from ..core.config import settings
from .user_profile_service import get_user_profile_by_email, get_or_create_user_profile
from .organization_service import add_user_to_organization
import logging

logger = logging.getLogger(__name__)


async def create_invitation(organization_id: int, invited_by_user_id: int, email: str, role_id: int) -> Invitation:
    """Create an invitation"""
    async with AsyncSessionLocal() as session:
        # Check if user already in organization
        invited_profile = await get_user_profile_by_email(email)
        if invited_profile:
            result = await session.execute(
                select(UserOrganization).where(
                    and_(
                        UserOrganization.user_profile_id == invited_profile.id,
                        UserOrganization.organization_id == organization_id,
                        UserOrganization.is_active == True
                    )
                )
            )
            if result.scalar_one_or_none():
                raise ValueError("User is already a member of this organization")
        
        # Check for existing pending invitation
        result = await session.execute(
            select(Invitation).where(
                and_(
                    Invitation.organization_id == organization_id,
                    Invitation.email == email,
                    Invitation.is_accepted == False,
                    Invitation.expires_at > datetime.utcnow()
                )
            )
        )
        existing = result.scalar_one_or_none()
        if existing:
            raise ValueError("An active invitation already exists for this email")
        
        # Create invitation
        invitation = Invitation(
            organization_id=organization_id,
            invited_by_user_id=invited_by_user_id,
            email=email,
            token=Invitation.generate_token(),
            role_id=role_id,
            expires_at=datetime.utcnow() + timedelta(days=7)  # 7 days expiry
        )
        
        session.add(invitation)
        await session.commit()
        await session.refresh(invitation)
        
        # Send invitation email
        await send_invitation_email(invitation)
        
        return invitation


async def get_invitation_by_token(token: str) -> Optional[Invitation]:
    """Get invitation by token"""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Invitation).where(Invitation.token == token)
        )
        return result.scalar_one_or_none()


async def accept_invitation(invitation_token: str, jwt_token: str) -> Invitation:
    """Accept an invitation"""
    async with AsyncSessionLocal() as session:
        invitation = await get_invitation_by_token(invitation_token)
        
        if not invitation:
            raise ValueError("Invalid invitation token")
        
        if invitation.is_accepted:
            raise ValueError("Invitation has already been accepted")
        
        if invitation.expires_at < datetime.utcnow():
            raise ValueError("Invitation has expired")
        
        # Get user from auth service using JWT token
        async with httpx.AsyncClient() as client:
            auth_response = await client.get(
                f"{settings.AUTH_SERVICE_URL}/api/auth/me",
                headers={"Authorization": f"Bearer {jwt_token}"},
                timeout=10.0
            )
            if auth_response.status_code != 200:
                raise ValueError("Invalid authentication")
            
            auth_data = auth_response.json()
            auth_user_id = int(auth_data['user']['id'])
            user_email = auth_data['user']['email']
        
        if invitation.email.lower() != user_email.lower():
            raise ValueError("Invitation email does not match your account email")
        
        # Get or create user profile
        user_profile = await get_or_create_user_profile(
            auth_user_id=auth_user_id,
            email=user_email,
        )
        
        # Check if user already belongs to an organization (users can only be in ONE organization)
        from .organization_service import get_user_organizations
        existing_orgs = await get_user_organizations(user_profile.id)
        if existing_orgs:
            raise ValueError("You already belong to an organization. Users can only be part of one organization.")
        
        # Add user to organization
        role = await session.get(Role, invitation.role_id)
        await add_user_to_organization(
            user_profile_id=user_profile.id,
            organization_id=invitation.organization_id,
            role_name=role.name
        )
        
        # Mark invitation as accepted
        invitation.is_accepted = True
        invitation.accepted_at = datetime.utcnow()
        invitation.accepted_by_user_id = user_profile.id
        
        await session.commit()
        await session.refresh(invitation)
        
        return invitation


async def send_invitation_email(invitation: Invitation):
    """Send invitation email via email service"""
    try:
        async with httpx.AsyncClient() as client:
            # Get organization details
            async with AsyncSessionLocal() as session:
                org = await session.get(Organization, invitation.organization_id)
                role = await session.get(Role, invitation.role_id)
            
            invitation_link = f"{settings.FRONTEND_URL}/invite/accept?token={invitation.token}"
            
            # For now, just log - email service integration will be added
            logger.info(f"Sending invitation email to {invitation.email}")
            logger.info(f"Invitation link: {invitation_link}")
            
            # Note: Email sending can be integrated with email service when needed
            # For now, invitation tokens are generated and can be sent via external email service
            # await client.post(
            #     f"{settings.EMAIL_SERVICE_URL}/api/email/send",
            #     json={
            #         "to": invitation.email,
            #         "subject": f"Invitation to join {org.name}",
            #         "body": f"You have been invited to join {org.name} as {role.display_name}. Click here to accept: {invitation_link}"
            #     }
            # )
            
    except Exception as e:
        logger.error(f"Error sending invitation email: {str(e)}")
        # Don't fail invitation creation if email fails


async def get_user_profile_by_email(email: str) -> Optional[UserProfile]:
    """Get user profile by email"""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(UserProfile).where(UserProfile.email == email)
        )
        return result.scalar_one_or_none()
