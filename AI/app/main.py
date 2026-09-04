from fastapi import FastAPI

from app.BYC.router import router as byc_router
from app.core.config import get_settings
from app.CROWD.router import router as crowd_router
from app.RVSL.router import router as rvsl_router

settings = get_settings()

app = FastAPI(title=settings.app_name)

app.include_router(crowd_router)
app.include_router(byc_router)
app.include_router(rvsl_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
