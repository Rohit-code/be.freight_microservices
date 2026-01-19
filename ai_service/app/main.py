from fastapi import FastAPI
from .api.routes import router as ai_router

app = FastAPI(
    title="AI Microservice",
    version="0.1.0",
)

app.include_router(ai_router)


@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "ai"}
