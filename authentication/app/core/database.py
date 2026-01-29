from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import declarative_base
from app.core.config import settings

# Create async engine
# Set echo=False to suppress SQLAlchemy query logs (they're too verbose)
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,  # Disable SQL query logging for cleaner logs
    future=True,
)

# Create async session factory
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)

# Base class for models
Base = declarative_base()


async def get_db() -> AsyncSession:
    """Dependency to get database session"""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


async def init_db():
    """Initialize database - create all tables"""
    import logging
    logger = logging.getLogger(__name__)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("✅ Database tables initialized successfully")
    except Exception as e:
        logger.error(f"❌ Database initialization failed: {e}", exc_info=True)
        # Don't raise - let the service start even if tables already exist
        # This allows the service to run if tables were created manually or via migrations
        logger.warning("⚠️  Continuing despite database initialization error (tables may already exist)")


async def close_db():
    """Close database connections"""
    await engine.dispose()
