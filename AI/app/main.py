from fastapi import FastAPI

from app.BIKE.router import router as bike_router
from app.core.config import get_settings
from app.CROWD.router import router as crowd_router
from app.ROUTE.router import router as route_router

settings = get_settings()

app = FastAPI(title=settings.app_name)

app.include_router(crowd_router)
app.include_router(bike_router)
app.include_router(route_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
