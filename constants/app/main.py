from fastapi import FastAPI
from .api.routes import router as constants_router


app = FastAPI(
    title="Constants Microservice",
    version="0.1.0",
)

app.include_router(constants_router)


@app.get("/health")
def health_check():
    return {"status": "ok"}
