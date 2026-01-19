from fastapi import FastAPI
from .api.routes import router as vector_router

app = FastAPI(
    title="Vector DB Microservice",
    version="0.1.0",
)

app.include_router(vector_router)


@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "vector_db"}
