from fastapi import FastAPI
import sys
from pathlib import Path
from .api.routes import router as vector_router

# Try to import shared error handlers
SHARED_PATH = Path(__file__).parent.parent.parent.parent / "shared"
if str(SHARED_PATH) not in sys.path:
    sys.path.insert(0, str(SHARED_PATH))

try:
    from error_handlers import register_error_handlers
    ERROR_HANDLERS_AVAILABLE = True
except ImportError:
    ERROR_HANDLERS_AVAILABLE = False

app = FastAPI(
    title="Vector DB Microservice",
    version="0.1.0",
)

# Register error handlers if available
if ERROR_HANDLERS_AVAILABLE:
    register_error_handlers(app)

app.include_router(vector_router)


@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "vector_db"}
