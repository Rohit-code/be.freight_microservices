from fastapi import HTTPException, status, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, or_
from passlib.context import CryptContext
from datetime import datetime
import asyncio
from ..schemas import (
    AuthResponse,
    LoginRequest,
    SignupRequest,
    GoogleCredentialRequest,
    UserOut,
    AdminDashboardResponse,
    AdminUserOut,
    AdminUsersResponse,
    AdminUserCreate,
    AdminUserUpdate,
)
from ..core.config import settings
from ..core.database import AsyncSessionLocal
from ..models import User
from ..utils.oauth import exchange_code_for_token
from ..utils.jwt import generate_jwt_token
import secrets
import logging

logger = logging.getLogger(__name__)

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


class AuthService:
    """
    Authentication service for user authentication and Gmail integration.
    Handles login, signup, Google OAuth, and Gmail webhook notifications.
    """

    async def login(self, payload: LoginRequest) -> AuthResponse:
        email = payload.email.lower().strip()
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(User).where(User.email == email)
            )
            user = result.scalar_one_or_none()
            if not user or not user.password_hash:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid email or password",
                )
            if not user.is_active:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="User account is inactive",
                )
            if not pwd_context.verify(payload.password, user.password_hash):
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid email or password",
                )

            user.last_login = datetime.utcnow()
            await session.commit()
            await session.refresh(user)

            token = generate_jwt_token(user.id, user.email)
            
            # Notify email service to fetch emails on login if Gmail is connected (non-blocking)
            if user.google_access_token and user.gmail_connected:
                try:
                    import httpx
                    async def trigger_email_fetch():
                        try:
                            async with httpx.AsyncClient() as client:
                                await client.post(
                                    "http://localhost:8005/api/email/fetch",
                                    json={"user_id": user.id},
                                    headers={"Authorization": f"Bearer {token}"},
                                    timeout=5.0
                                )
                        except Exception as e:
                            # Log but don't block login if email service is unavailable
                            logger.warning(f"Failed to trigger email fetch on login: {e}", exc_info=True)
                    asyncio.create_task(trigger_email_fetch())
                except Exception as e:
                    # Log but don't block login - email fetch is non-critical
                    logger.warning(f"Failed to schedule email fetch on login: {e}", exc_info=True)
            name = None
            if user.first_name or user.last_name:
                name = f"{user.first_name or ''} {user.last_name or ''}".strip()

            user_out = UserOut(
                id=str(user.id),
                email=user.email,
                name=name,
                picture=user.picture,
                is_google_user=user.is_google_user,
                has_google_connected=bool(user.google_access_token),
            )
            return AuthResponse(user=user_out, token=token)

    async def signup(self, payload: SignupRequest) -> AuthResponse:
        email = payload.email.lower().strip()
        base_username = (payload.username or email.split("@")[0]).strip()

        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(User).where(User.email == email)
            )
            existing_user = result.scalar_one_or_none()
            if existing_user:
                detail = "Email already registered"
                if existing_user.is_google_user and not existing_user.password_hash:
                    detail = "Account exists. Please sign in with Google."
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=detail,
                )

            username = None
            for attempt in range(5):
                candidate = base_username if attempt == 0 else f"{base_username}{secrets.token_hex(2)}"
                result = await session.execute(
                    select(User).where(User.username == candidate)
                )
                if not result.scalar_one_or_none():
                    username = candidate
                    break
            if not username:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Unable to generate unique username. Please try again.",
                )

            user = User(
                email=email,
                username=username,
                first_name=payload.first_name,
                last_name=payload.last_name,
                password_hash=pwd_context.hash(payload.password),
                is_google_user=False,
            )
            session.add(user)
            await session.commit()
            await session.refresh(user)

            token = generate_jwt_token(user.id, user.email)
            name = None
            if user.first_name or user.last_name:
                name = f"{user.first_name or ''} {user.last_name or ''}".strip()

            user_out = UserOut(
                id=str(user.id),
                email=user.email,
                name=name,
                picture=user.picture,
                is_google_user=user.is_google_user,
                has_google_connected=bool(user.google_access_token),
            )
            return AuthResponse(user=user_out, token=token)

    def initiate_google_oauth(self, request: Request) -> RedirectResponse:
        """Initiate Google OAuth flow - redirects to Google"""
        try:
            if not settings.google_client_id or not settings.google_client_secret:
                frontend_url = "http://localhost:3000/api/auth/google/callback"
                return RedirectResponse(
                    url=f"{frontend_url}?error=oauth_not_configured&details=Google_OAuth_not_configured",
                    status_code=302
                )

            # Generate state for CSRF protection
            state = secrets.token_urlsafe(32)

            # Build OAuth URL via google-auth-oauthlib flow (matches Django flow)
            from ..utils.oauth import get_google_oauth_flow
            flow = get_google_oauth_flow()
            authorization_url, _ = flow.authorization_url(
                access_type='offline',
                include_granted_scopes='false',
                state=state,
                prompt='consent'
            )

            response = RedirectResponse(url=authorization_url, status_code=302)
            response.set_cookie(
                key="oauth_state",
                value=state,
                httponly=True,
                secure=settings.environment == "production",
                samesite="lax",
                max_age=600
            )
            return response

        except Exception as e:
            frontend_url = "http://localhost:3000/api/auth/google/callback"
            error_message = str(e).replace(' ', '_').replace('=', '_')[:50]
            return RedirectResponse(
                url=f"{frontend_url}?error=oauth_init_failed&details={error_message}",
                status_code=302
            )

    async def handle_google_callback(self, request: Request) -> RedirectResponse:
        """Handle Google OAuth callback - receives code and exchanges for token"""
        code = request.query_params.get('code')
        state = request.query_params.get('state')
        error = request.query_params.get('error')
        
        frontend_url = "http://localhost:3000/api/auth/google/callback"
        
        if error:
            error_description = request.query_params.get('error_description', '')
            from urllib.parse import quote
            error_desc_encoded = quote(error_description) if error_description else ''
            return RedirectResponse(
                url=f"{frontend_url}?error={error}&details={error_desc_encoded}",
                status_code=302
            )
        
        if not code:
            return RedirectResponse(
                url=f"{frontend_url}?error=no_code",
                status_code=302
            )
        
        # Verify state (CSRF protection)
        cookie_state = request.cookies.get('oauth_state')
        if state != cookie_state:
            return RedirectResponse(
                url=f"{frontend_url}?error=state_mismatch",
                status_code=302
            )
        
        try:
            # Exchange code for token
            google_user_info = exchange_code_for_token(code)
            
            # Get or create user
            async with AsyncSessionLocal() as session:
                # Check if user exists by email
                result = await session.execute(
                    select(User).where(User.email == google_user_info['email'])
                )
                user = result.scalar_one_or_none()
                
                if user:
                    # Update existing user
                    if not user.google_id:
                        user.google_id = google_user_info['google_id']
                        user.is_google_user = True
                    if google_user_info.get('picture') and not user.picture:
                        user.picture = google_user_info['picture']
                    if google_user_info.get('access_token'):
                        user.google_access_token = google_user_info['access_token']
                    if google_user_info.get('refresh_token'):
                        user.google_refresh_token = google_user_info['refresh_token']
                    if google_user_info.get('token_expiry'):
                        user.google_token_expiry = google_user_info['token_expiry']
                    user.gmail_connected = True
                    user.drive_connected = True
                else:
                    # Create new user
                    name_parts = google_user_info.get('name', '').split()
                    first_name = name_parts[0] if name_parts else ''
                    last_name = ' '.join(name_parts[1:]) if len(name_parts) > 1 else ''
                    username = google_user_info['email'].split('@')[0]
                    
                    user = User(
                        email=google_user_info['email'],
                        username=username,
                        first_name=first_name,
                        last_name=last_name,
                        picture=google_user_info.get('picture', ''),
                        google_id=google_user_info['google_id'],
                        is_google_user=True,
                        google_access_token=google_user_info.get('access_token', ''),
                        google_refresh_token=google_user_info.get('refresh_token', ''),
                        google_token_expiry=google_user_info.get('token_expiry'),
                        gmail_connected=True,
                        drive_connected=True,
                    )
                    session.add(user)
                
                await session.commit()
                await session.refresh(user)
                
                # Generate JWT token
                token = generate_jwt_token(user.id, user.email)
                
                # Notify email service to fetch emails on Google OAuth login if Gmail is connected (non-blocking)
                if user.google_access_token and user.gmail_connected:
                    try:
                        import httpx
                        async def trigger_email_fetch():
                            try:
                                async with httpx.AsyncClient() as client:
                                    await client.post(
                                        "http://localhost:8005/api/email/fetch",
                                        json={"user_id": user.id},
                                        headers={"Authorization": f"Bearer {token}"},
                                        timeout=5.0
                                    )
                            except Exception as e:
                                # Log but don't block login if email service is unavailable
                                logger.warning(f"Failed to trigger email fetch on login: {e}", exc_info=True)
                        asyncio.create_task(trigger_email_fetch())
                    except Exception as e:
                        # Log but don't block login - email fetch is non-critical
                        logger.warning(f"Failed to schedule email fetch on login: {e}", exc_info=True)
                
                # Clear state cookie
                response = RedirectResponse(
                    url=f"{frontend_url}?token={token}&success=true",
                    status_code=302
                )
                response.delete_cookie("oauth_state")
                return response
                
        except Exception as e:
            import traceback
            traceback.print_exc()
            error_message = str(e).replace(' ', '_').replace('=', '_')[:50]
            return RedirectResponse(
                url=f"{frontend_url}?error=auth_failed&details={error_message}",
                status_code=302
            )

    async def verify_google(self, payload: GoogleCredentialRequest) -> AuthResponse:
        """Verify Google ID token and return app JWT"""
        try:
            from google.oauth2 import id_token
            from google.auth.transport import requests
            
            if not settings.google_client_id:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Google Client ID not configured",
                )
            
            # Verify Google ID token
            idinfo = id_token.verify_oauth2_token(
                payload.credential,
                requests.Request(),
                settings.google_client_id,
            )
            
            if idinfo.get("iss") not in ["accounts.google.com", "https://accounts.google.com"]:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid token issuer",
                )
            
            email = idinfo.get("email")
            google_id = idinfo.get("sub")
            name = idinfo.get("name", "")
            picture = idinfo.get("picture", "")
            
            if not email or not google_id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid Google token payload",
                )
            
            # Get or create user
            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(User).where(User.email == email)
                )
                user = result.scalar_one_or_none()
                
                if user:
                    if not user.google_id:
                        user.google_id = google_id
                        user.is_google_user = True
                    if picture and not user.picture:
                        user.picture = picture
                else:
                    name_parts = name.split()
                    first_name = name_parts[0] if name_parts else ""
                    last_name = " ".join(name_parts[1:]) if len(name_parts) > 1 else ""
                    username = email.split("@")[0]
                    
                    user = User(
                        email=email,
                        username=username,
                        first_name=first_name,
                        last_name=last_name,
                        picture=picture,
                        google_id=google_id,
                        is_google_user=True,
                    )
                    session.add(user)
                
                await session.commit()
                await session.refresh(user)
                
                token = generate_jwt_token(user.id, user.email)
                
                user_out = UserOut(
                    id=str(user.id),
                    email=user.email,
                    name=f"{user.first_name or ''} {user.last_name or ''}".strip() or None,
                    picture=user.picture,
                    is_google_user=user.is_google_user,
                    has_google_connected=bool(user.google_access_token),
                )
                
                return AuthResponse(user=user_out, token=token)
        
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Invalid Google token: {str(e)}",
            )

    async def get_current_user(self, token: str) -> AuthResponse:
        """Get current user from JWT token"""
        try:
            from ..utils.jwt import verify_jwt_token
            
            # Verify JWT token
            payload = verify_jwt_token(token)
            user_id = payload.get('user_id')
            email = payload.get('email')
            
            if not user_id:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid token payload",
                )
            
            # Get user from database
            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(User).where(User.id == user_id)
                )
                user = result.scalar_one_or_none()
                
                if not user:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail="User not found",
                    )
                
                # Build user response
                name = None
                if user.first_name or user.last_name:
                    name = f"{user.first_name or ''} {user.last_name or ''}".strip()
                
                user_out = UserOut(
                    id=str(user.id),
                    email=user.email,
                    name=name,
                    picture=user.picture,
                    is_google_user=user.is_google_user,
                    has_google_connected=bool(user.google_access_token),
                )
                
                return AuthResponse(
                    user=user_out,
                    token=token,  # Return the same token
                )
                
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=str(e),
            )
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Error getting current user: {str(e)}",
            )

    async def _get_admin_user(self, session: AsyncSession, token: str) -> User:
        from ..utils.jwt import verify_jwt_token

        payload = verify_jwt_token(token)
        user_id = payload.get("user_id")
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token payload",
            )

        result = await session.execute(
            select(User).where(User.id == user_id)
        )
        admin_user = result.scalar_one_or_none()
        if not admin_user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found",
            )
        if not (admin_user.is_staff or admin_user.is_superuser):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Admin access required",
            )
        return admin_user

    def _to_admin_user(self, user: User) -> AdminUserOut:
        name = None
        if user.first_name or user.last_name:
            name = f"{user.first_name or ''} {user.last_name or ''}".strip()
        return AdminUserOut(
            id=str(user.id),
            email=user.email,
            username=user.username,
            name=name,
            is_active=user.is_active,
            is_staff=user.is_staff,
            is_superuser=user.is_superuser,
            is_google_user=user.is_google_user,
            has_google_connected=bool(user.google_access_token),
            gmail_connected=user.gmail_connected,
            drive_connected=user.drive_connected,
            last_login=user.last_login,
            created_at=user.created_at,
        )

    async def get_admin_dashboard(self, token: str) -> AdminDashboardResponse:
        """Admin dashboard data for staff/superusers"""
        try:
            async with AsyncSessionLocal() as session:
                await self._get_admin_user(session, token)

                total_users = await session.scalar(
                    select(func.count()).select_from(User)
                )
                active_users = await session.scalar(
                    select(func.count()).select_from(User).where(User.is_active.is_(True))
                )
                google_connected_users = await session.scalar(
                    select(func.count()).select_from(User).where(User.google_access_token.isnot(None))
                )
                gmail_connected_users = await session.scalar(
                    select(func.count()).select_from(User).where(User.gmail_connected.is_(True))
                )
                drive_connected_users = await session.scalar(
                    select(func.count()).select_from(User).where(User.drive_connected.is_(True))
                )

                admin_results = await session.execute(
                    select(User).where(
                        (User.is_staff.is_(True)) | (User.is_superuser.is_(True))
                    ).order_by(User.created_at.desc())
                )
                admin_users = admin_results.scalars().all()

                recent_results = await session.execute(
                    select(User).order_by(User.created_at.desc()).limit(50)
                )
                recent_users = recent_results.scalars().all()

                return AdminDashboardResponse(
                    total_users=total_users or 0,
                    active_users=active_users or 0,
                    google_connected_users=google_connected_users or 0,
                    gmail_connected_users=gmail_connected_users or 0,
                    drive_connected_users=drive_connected_users or 0,
                    admin_users=[self._to_admin_user(u) for u in admin_users],
                    recent_users=[self._to_admin_user(u) for u in recent_users],
                )

        except HTTPException:
            raise
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=str(e),
            )
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Error loading admin dashboard: {str(e)}",
            )

    async def list_admin_users(
        self,
        token: str,
        limit: int = 50,
        offset: int = 0,
        search: str | None = None,
    ) -> AdminUsersResponse:
        try:
            async with AsyncSessionLocal() as session:
                await self._get_admin_user(session, token)

                query = select(User)
                count_query = select(func.count()).select_from(User)

                if search:
                    search_value = f"%{search.strip().lower()}%"
                    filter_clause = or_(
                        func.lower(User.email).like(search_value),
                        func.lower(User.username).like(search_value),
                    )
                    query = query.where(filter_clause)
                    count_query = count_query.where(filter_clause)

                total = await session.scalar(count_query)
                result = await session.execute(
                    query.order_by(User.created_at.desc()).offset(offset).limit(limit)
                )
                users = result.scalars().all()

                return AdminUsersResponse(
                    total=total or 0,
                    users=[self._to_admin_user(u) for u in users],
                )
        except HTTPException:
            raise
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=str(e),
            )
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Error loading users: {str(e)}",
            )

    async def create_admin_user(self, token: str, payload: AdminUserCreate) -> AdminUserOut:
        try:
            async with AsyncSessionLocal() as session:
                await self._get_admin_user(session, token)

                email = payload.email.lower().strip()
                username = (payload.username or email.split("@")[0]).strip()

                existing = await session.execute(select(User).where(User.email == email))
                if existing.scalar_one_or_none():
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Email already registered",
                    )

                username_result = await session.execute(
                    select(User).where(User.username == username)
                )
                if username_result.scalar_one_or_none():
                    username = f"{username}{secrets.token_hex(2)}"

                user = User(
                    email=email,
                    username=username,
                    first_name=payload.first_name,
                    last_name=payload.last_name,
                    password_hash=pwd_context.hash(payload.password),
                    is_active=payload.is_active,
                    is_staff=payload.is_staff,
                    is_superuser=payload.is_superuser,
                )
                session.add(user)
                await session.commit()
                await session.refresh(user)
                return self._to_admin_user(user)
        except HTTPException:
            raise
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=str(e),
            )
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Error creating user: {str(e)}",
            )

    async def update_admin_user(
        self, token: str, user_id: int, payload: AdminUserUpdate
    ) -> AdminUserOut:
        try:
            async with AsyncSessionLocal() as session:
                await self._get_admin_user(session, token)

                result = await session.execute(select(User).where(User.id == user_id))
                user = result.scalar_one_or_none()
                if not user:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail="User not found",
                    )

                if payload.email is not None:
                    email = payload.email.lower().strip()
                    if email != user.email:
                        existing = await session.execute(
                            select(User).where(User.email == email)
                        )
                        if existing.scalar_one_or_none():
                            raise HTTPException(
                                status_code=status.HTTP_400_BAD_REQUEST,
                                detail="Email already registered",
                            )
                        user.email = email

                if payload.username is not None:
                    username = payload.username.strip()
                    if username and username != user.username:
                        existing = await session.execute(
                            select(User).where(User.username == username)
                        )
                        if existing.scalar_one_or_none():
                            raise HTTPException(
                                status_code=status.HTTP_400_BAD_REQUEST,
                                detail="Username already taken",
                            )
                        user.username = username

                if payload.first_name is not None:
                    user.first_name = payload.first_name
                if payload.last_name is not None:
                    user.last_name = payload.last_name
                if payload.is_active is not None:
                    user.is_active = payload.is_active
                if payload.is_staff is not None:
                    user.is_staff = payload.is_staff
                if payload.is_superuser is not None:
                    user.is_superuser = payload.is_superuser
                if payload.password:
                    user.password_hash = pwd_context.hash(payload.password)

                await session.commit()
                await session.refresh(user)
                return self._to_admin_user(user)
        except HTTPException:
            raise
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=str(e),
            )
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Error updating user: {str(e)}",
            )

    async def delete_admin_user(self, token: str, user_id: int) -> dict:
        try:
            async with AsyncSessionLocal() as session:
                admin_user = await self._get_admin_user(session, token)

                if admin_user.id == user_id:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Cannot delete your own account",
                    )

                result = await session.execute(select(User).where(User.id == user_id))
                user = result.scalar_one_or_none()
                if not user:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail="User not found",
                    )
                await session.delete(user)
                await session.commit()
                return {"message": "User deleted"}
        except HTTPException:
            raise
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=str(e),
            )
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Error deleting user: {str(e)}",
            )

    def logout(self) -> dict:
        return {"message": "Successfully logged out"}

    # ========== INTERNAL METHODS FOR EMAIL SERVICE ==========
    
    async def get_gmail_connected_users(self) -> dict:
        """Get all users with Gmail connected - for background email fetching"""
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(User).where(
                    User.gmail_connected == True,
                    User.google_refresh_token.isnot(None),
                    User.is_active == True
                )
            )
            users = result.scalars().all()
            
            return {
                "users": [
                    {
                        "id": user.id,
                        "email": user.email,
                        "gmail_connected": user.gmail_connected,
                        "has_refresh_token": bool(user.google_refresh_token),
                    }
                    for user in users
                ],
                "total": len(users)
            }
    
    async def fetch_gmail_for_user(self, user_id: int, max_results: int = 20) -> dict:
        """Fetch Gmail messages for a user by user_id using refresh token"""
        from .gmail_service import list_emails
        
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(User).where(User.id == user_id)
            )
            user = result.scalar_one_or_none()
            
            if not user:
                raise ValueError(f"User {user_id} not found")
            
            if not user.gmail_connected:
                raise ValueError(f"User {user_id} does not have Gmail connected")
            
            if not user.google_refresh_token:
                raise ValueError(f"User {user_id} does not have a refresh token")
            
            # list_emails will automatically refresh token if needed
            return await list_emails(user, max_results=max_results)
    
    async def get_gmail_detail_for_user(self, user_id: int, message_id: str) -> dict:
        """Get Gmail message detail for a user by user_id using refresh token"""
        from .gmail_service import get_email_detail
        
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(User).where(User.id == user_id)
            )
            user = result.scalar_one_or_none()
            
            if not user:
                raise ValueError(f"User {user_id} not found")
            
            if not user.gmail_connected:
                raise ValueError(f"User {user_id} does not have Gmail connected")
            
            if not user.google_refresh_token:
                raise ValueError(f"User {user_id} does not have a refresh token")
            
            # get_email_detail will automatically refresh token if needed
            return await get_email_detail(user, message_id)

    # ========== GMAIL PUSH NOTIFICATIONS ==========
    
    async def start_gmail_watch(self, token: str) -> dict:
        """Start Gmail push notifications for a user"""
        from ..utils.google_api import get_user_from_token
        from .gmail_service import setup_gmail_watch
        
        user = await get_user_from_token(token)
        
        if not user.gmail_connected:
            raise ValueError("Gmail not connected")
        
        result = await setup_gmail_watch(user)
        
        # Store the historyId for future reference
        async with AsyncSessionLocal() as session:
            db_result = await session.execute(
                select(User).where(User.id == user.id)
            )
            db_user = db_result.scalar_one()
            # We could add a gmail_history_id column, but for now just log it
            await session.commit()
        
        return {
            "message": "Gmail watch started - you will receive instant notifications",
            "historyId": result.get('historyId'),
            "expiration": result.get('expiration'),
            "note": "Watch expires in ~7 days and needs renewal"
        }
    
    async def stop_gmail_watch(self, token: str) -> dict:
        """Stop Gmail push notifications for a user"""
        from ..utils.google_api import get_user_from_token
        from .gmail_service import stop_gmail_watch
        
        user = await get_user_from_token(token)
        
        if not user.gmail_connected:
            raise ValueError("Gmail not connected")
        
        await stop_gmail_watch(user)
        
        return {"message": "Gmail watch stopped"}
    
    async def start_gmail_watch_all_users(self) -> dict:
        """Start Gmail watch for all Gmail-connected users"""
        from .gmail_service import setup_gmail_watch
        import logging
        
        logger = logging.getLogger(__name__)
        results = []
        
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(User).where(
                    User.gmail_connected == True,
                    User.google_refresh_token.isnot(None),
                    User.is_active == True
                )
            )
            users = result.scalars().all()
            
            for user in users:
                try:
                    watch_result = await setup_gmail_watch(user)
                    results.append({
                        "user_id": user.id,
                        "email": user.email,
                        "status": "success",
                        "historyId": watch_result.get('historyId'),
                        "expiration": watch_result.get('expiration')
                    })
                    logger.info(f"Gmail watch started for {user.email}")
                except Exception as e:
                    results.append({
                        "user_id": user.id,
                        "email": user.email,
                        "status": "error",
                        "error": str(e)
                    })
                    logger.error(f"Failed to start Gmail watch for {user.email}: {e}")
        
        return {
            "message": f"Gmail watch started for {len([r for r in results if r['status'] == 'success'])} users",
            "results": results
        }
    
    async def handle_gmail_notification(self, email_address: str, history_id: str):
        """
        Handle incoming Gmail push notification.
        Called when Pub/Sub sends us a notification about new emails.
        """
        import httpx
        import logging
        
        logger = logging.getLogger(__name__)
        
        # Import settings at function level to avoid circular imports
        from ..core.config import settings as auth_settings
        
        try:
            # Find user by email
            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(User).where(User.email == email_address)
                )
                user = result.scalar_one_or_none()
                
                if not user:
                    logger.warning(f"Gmail notification for unknown user: {email_address}")
                    return
                
                if not user.gmail_connected or not user.google_refresh_token:
                    logger.warning(f"User {email_address} Gmail not properly connected")
                    return
                
                user_id = user.id
            
            logger.info(f"📧 Processing Gmail notification for user {user_id} ({email_address})")
            
            # Get user's organization_id (for auto-drafting email responses)
            organization_id = None
            try:
                # Get organization_id from user service (internal endpoint)
                async with httpx.AsyncClient() as org_client:
                    org_url = f"{auth_settings.USER_SERVICE_URL}/api/user/internal/user/{user_id}/organization-id"
                    logger.info(f"🔍 Getting organization_id from user service: {org_url}")
                    org_response = await org_client.get(org_url, timeout=10.0)
                    
                    if org_response.status_code == 200:
                        org_data = org_response.json()
                        organization_id = org_data.get('organization_id')
                        if organization_id:
                            logger.info(f"✅ Got organization_id: {organization_id} for user {user_id}")
                        else:
                            logger.warning(f"⚠️  User {user_id} has no organization (message: {org_data.get('message')})")
                    else:
                        logger.warning(f"⚠️  Failed to get organization_id: HTTP {org_response.status_code}")
            except Exception as e:
                logger.warning(f"⚠️  Could not get organization_id for user {user_id}: {e}")
                # Continue without organization_id - email will still be stored, just no auto-draft
            
            logger.info(f"🔍 Fetching NEW emails since historyId {history_id} for user {user_id}")
            
            # Use Gmail history API to get only NEW emails since the historyId
            from ..services.gmail_service import get_history_since
            from ..models import User as UserModel
            
            # Get user object for history API
            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(UserModel).where(UserModel.id == user_id)
                )
                user_obj = result.scalar_one_or_none()
            
            if not user_obj:
                logger.error(f"User {user_id} not found")
                return
            
            # Get new emails since historyId
            # Note: The historyId in webhook is the NEW historyId after email was added
            # We need to get messages added since the PREVIOUS historyId
            # For now, we'll use the list API to get recent messages and filter duplicates
            new_message_ids = []
            try:
                # Try to get history, but if it fails or returns empty, fall back to list API
                # Get more messages from history (increased from 50 to 100)
                history_result = await get_history_since(user_obj, history_id, max_results=100)
                new_message_ids = history_result.get('newMessageIds', [])
                logger.info(f"✅ Found {len(new_message_ids)} new messages since historyId {history_id}")
                
                # If history API returns empty, it might mean historyId is too new or expired
                # Fall through to list API to get recent messages anyway
                if not new_message_ids:
                    logger.info("History API returned no new messages, will use list API to get recent messages")
                
            except Exception as e:
                logger.warning(f"Could not get history (may be expired), falling back to list API: {e}")
                new_message_ids = []
            
            # Trigger email fetch via email service internal API
            # Use longer timeout for Gmail API calls which can be slow
            async with httpx.AsyncClient(timeout=120.0) as client:
                # If we have specific message IDs from history, use those
                # Otherwise, fall back to listing recent messages
                if new_message_ids:
                    # Process all new messages from history (up to 50)
                    messages_to_process = [{"id": msg_id} for msg_id in new_message_ids[:50]]
                    logger.info(f"📬 Processing {len(messages_to_process)} new messages from history")
                else:
                    # Fallback: get recent messages (increase limit to check more emails)
                    gmail_list_url = f"http://localhost:8001/api/auth/internal/gmail/{user_id}/list"
                    logger.info(f"GET {gmail_list_url}?max_results=50")
                    try:
                        response = await client.get(
                            gmail_list_url,
                            params={"max_results": 50},  # Increased from 10 to 50
                            timeout=60.0  # Increased timeout for Gmail API calls
                        )
                        
                        logger.info(f"Gmail list response status: {response.status_code}")
                        
                        if response.status_code != 200:
                            logger.error(f"Failed to fetch emails: {response.status_code}")
                            return
                        
                        gmail_data = response.json()
                        messages_to_process = gmail_data.get('messages', [])
                    except (httpx.TimeoutException, httpx.ReadTimeout, httpx.ConnectTimeout) as e:
                        # Log timeout with context (no silent failure per BACKEND_REVIEW.md)
                        logger.warning(
                            f"⚠️  Timeout fetching Gmail list: {type(e).__name__}. Will retry on next webhook.",
                            extra={
                                "email_address": email_address,
                                "history_id": history_id,
                                "exception_type": type(e).__name__
                            }
                        )
                        return  # Return gracefully, will retry on next notification
                    except Exception as e:
                        # Log error with full context (no silent failure)
                        logger.error(
                            f"❌ Error fetching Gmail list: {type(e).__name__}: {str(e)}",
                            exc_info=True,
                            extra={
                                "email_address": email_address,
                                "history_id": history_id,
                                "exception_type": type(e).__name__
                            }
                        )
                        return  # Return gracefully (webhook should acknowledge receipt)
                
                logger.info(f"✅ Processing {len(messages_to_process)} messages")
                
                if not messages_to_process:
                    logger.warning("⚠️  No messages to process")
                    return
                
                # Store new emails via email service (with auto-draft enabled)
                processed_count = 0
                # Process all messages (up to 50) - increased from 10 to check more emails
                for msg in messages_to_process[:50]:
                    try:
                        msg_id = msg.get('id')
                        logger.info(f"📨 Processing message {msg_id}")
                        
                        # Get full email detail
                        detail_url = f"http://localhost:8001/api/auth/internal/gmail/{user_id}/detail/{msg_id}"
                        logger.info(f"GET {detail_url}")
                        detail_response = None
                        try:
                            detail_response = await client.get(
                                detail_url,
                                timeout=60.0  # Increased timeout for Gmail API calls
                            )
                            
                            logger.info(f"Email detail response status: {detail_response.status_code}")
                        except (httpx.TimeoutException, httpx.ReadTimeout, httpx.ConnectTimeout) as e:
                            logger.warning(f"⚠️  Timeout getting email detail for {msg_id}: {type(e).__name__}. Skipping this email and continuing...")
                            continue  # Skip this email and process the next one
                        except Exception as e:
                            logger.error(f"❌ Error getting email detail for {msg_id}: {e}. Skipping...")
                            continue  # Skip this email and process the next one
                        
                        if not detail_response:
                            logger.warning(f"⚠️  No detail response for {msg_id}, skipping...")
                            continue
                            
                        if detail_response.status_code == 200:
                            email_detail = detail_response.json()
                            subject = email_detail.get('subject', 'No Subject')
                            from_email = email_detail.get('from', 'Unknown')
                            logger.info(f"📧 Email: '{subject}' from {from_email}")
                            
                            # Store in email service with auto-draft enabled
                            store_url = "http://localhost:8005/api/email/store"
                            store_payload = {
                                "user_id": user_id,
                                "gmail_message_id": msg_id,
                                "gmail_thread_id": msg.get('threadId'),
                                "subject": email_detail.get('subject'),
                                "from_email": email_detail.get('from'),
                                "to_email": email_detail.get('to'),
                                "snippet": email_detail.get('snippet'),
                                "body_plain": email_detail.get('body') if '<' not in email_detail.get('body', '') else None,
                                "body_html": email_detail.get('body') if '<' in email_detail.get('body', '') else None,
                                "date": email_detail.get('date'),
                                "has_attachments": email_detail.get('attachmentCount', 0) > 0,
                                "attachment_count": email_detail.get('attachmentCount', 0),
                                "organization_id": organization_id,  # Pass org_id for auto-draft
                                "auto_draft": True,  # Enable auto-drafting
                            }
                            
                            logger.info(f"POST {store_url} (org_id: {organization_id}, auto_draft: True)")
                            # Email storage is now fast (drafting is async), but keep longer timeout for safety
                            try:
                                store_response = await client.post(
                                    store_url,
                                    json=store_payload,
                                    timeout=120.0  # 2 minutes - email stores quickly, but keep buffer
                                )
                                
                                logger.info(f"Store response status: {store_response.status_code}")
                                
                                if store_response.status_code == 200:
                                    store_data = store_response.json()
                                    if store_data.get('has_draft'):
                                        logger.info(f"✅ Stored email {msg_id} for user {user_id} with auto-drafted response")
                                    else:
                                        logger.info(f"✅ Stored email {msg_id} for user {user_id}")
                                    processed_count += 1
                                else:
                                    error_text = store_response.text[:500] if hasattr(store_response, 'text') else "No error text"
                                    logger.error(f"❌ Failed to store email {msg_id}: HTTP {store_response.status_code} - {error_text}")
                            except httpx.TimeoutException:
                                # Log timeout with context (no silent failure)
                                logger.warning(
                                    f"⚠️  Timeout storing email {msg_id} - email may still be stored (drafting is async). Continuing...",
                                    extra={
                                        "msg_id": msg_id,
                                        "user_id": user_id,
                                        "exception_type": "TimeoutException"
                                    }
                                )
                                # Don't fail the whole webhook if one email times out
                                # Email service should have stored it even if response timed out
                            except httpx.ReadTimeout:
                                # Log timeout with context (no silent failure)
                                logger.warning(
                                    f"⚠️  Read timeout storing email {msg_id} - email may still be stored (drafting is async). Continuing...",
                                    extra={
                                        "msg_id": msg_id,
                                        "user_id": user_id,
                                        "exception_type": "ReadTimeout"
                                    }
                                )
                                # Don't fail the whole webhook if one email times out
                        else:
                            error_text = detail_response.text[:500] if hasattr(detail_response, 'text') else "No error text"
                            logger.error(f"❌ Failed to get email detail {msg_id}: HTTP {detail_response.status_code} - {error_text}")
                            
                    except Exception as e:
                        # Log error with full context (no silent failure per BACKEND_REVIEW.md)
                        msg_id = msg.get('id', 'unknown')
                        logger.error(
                            f"❌ Error processing email {msg_id}: {type(e).__name__}: {str(e)}",
                            exc_info=True,
                            extra={
                                "msg_id": msg_id,
                                "user_id": user_id,
                                "email_address": email_address,
                                "exception_type": type(e).__name__
                            }
                        )
                        # Continue processing other emails (don't fail entire webhook)
                
                logger.info(f"✅ Gmail notification processed: {processed_count}/{len(messages_to_process)} emails stored")
                    
        except Exception as e:
            # Log top-level error with full context (no silent failure)
            logger.error(
                f"Error handling Gmail notification: {type(e).__name__}: {str(e)}",
                exc_info=True,
                extra={
                    "email_address": email_address,
                    "history_id": history_id,
                    "exception_type": type(e).__name__
                }
            )
            # Re-raise to let webhook handler decide (may want to return error to Pub/Sub)
            raise


auth_service = AuthService()
