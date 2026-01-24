#!/usr/bin/env python3
"""Script to verify admin user exists"""
import asyncio
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

from app.core.database import AsyncSessionLocal
from app.models.user import User
from sqlalchemy import select


async def verify_admin_user():
    """Verify admin user exists"""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(User).where(User.email == "admin@example.com")
        )
        admin_user = result.scalar_one_or_none()
        
        if admin_user:
            print(f"✅ Admin user found:")
            print(f"   ID: {admin_user.id}")
            print(f"   Email: {admin_user.email}")
            print(f"   Username: {admin_user.username}")
            print(f"   Is Active: {admin_user.is_active}")
            print(f"   Is Staff: {admin_user.is_staff}")
            print(f"   Is Superuser: {admin_user.is_superuser}")
            print(f"   Created At: {admin_user.created_at}")
            return True
        else:
            print(f"❌ Admin user not found!")
            return False


if __name__ == "__main__":
    try:
        success = asyncio.run(verify_admin_user())
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"❌ Error verifying admin user: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
