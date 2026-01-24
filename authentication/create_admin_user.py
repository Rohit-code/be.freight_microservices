#!/usr/bin/env python3
"""Script to create an admin user directly in the database"""
import asyncio
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

from app.core.database import AsyncSessionLocal, init_db
from app.models.user import User
from sqlalchemy import select
from passlib.context import CryptContext

# Password hashing context
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


async def create_admin_user():
    """Create admin user if it doesn't exist"""
    # Initialize database tables
    await init_db()
    
    async with AsyncSessionLocal() as session:
        # Check if admin user already exists
        result = await session.execute(
            select(User).where(User.email == "admin@example.com")
        )
        existing_user = result.scalar_one_or_none()
        
        if existing_user:
            print(f"ℹ️  Admin user 'admin@example.com' already exists.")
            print(f"   User ID: {existing_user.id}")
            print(f"   Is Staff: {existing_user.is_staff}")
            print(f"   Is Superuser: {existing_user.is_superuser}")
            
            # Update to ensure admin privileges
            if not existing_user.is_staff or not existing_user.is_superuser:
                existing_user.is_staff = True
                existing_user.is_superuser = True
                existing_user.is_active = True
                await session.commit()
                print(f"✅ Updated user to have admin privileges")
            else:
                print(f"✅ User already has admin privileges")
            return
        
        # Create new admin user
        admin_user = User(
            email="admin@example.com",
            username="admin",
            password_hash=pwd_context.hash("123"),
            first_name="Admin",
            last_name="User",
            is_active=True,
            is_staff=True,
            is_superuser=True,
        )
        
        session.add(admin_user)
        await session.commit()
        await session.refresh(admin_user)
        
        print(f"✅ Admin user created successfully!")
        print(f"   Email: {admin_user.email}")
        print(f"   Username: {admin_user.username}")
        print(f"   Password: 123")
        print(f"   User ID: {admin_user.id}")
        print(f"   Is Staff: {admin_user.is_staff}")
        print(f"   Is Superuser: {admin_user.is_superuser}")


if __name__ == "__main__":
    try:
        asyncio.run(create_admin_user())
        sys.exit(0)
    except Exception as e:
        print(f"❌ Error creating admin user: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
