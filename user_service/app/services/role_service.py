"""Role service - initialize default roles"""
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from ..models import Role
from ..core.database import AsyncSessionLocal


async def initialize_default_roles():
    """Initialize default roles: admin, employee, manager"""
    async with AsyncSessionLocal() as session:
        roles_to_create = [
            {
                "name": "admin",
                "display_name": "Admin",
                "description": "Full access to organization settings and user management"
            },
            {
                "name": "manager",
                "display_name": "Manager",
                "description": "Can manage team members and view reports"
            },
            {
                "name": "employee",
                "display_name": "Employee",
                "description": "Standard team member with basic access"
            }
        ]
        
        for role_data in roles_to_create:
            result = await session.execute(
                select(Role).where(Role.name == role_data["name"])
            )
            existing_role = result.scalar_one_or_none()
            
            if not existing_role:
                role = Role(**role_data)
                session.add(role)
        
        await session.commit()
