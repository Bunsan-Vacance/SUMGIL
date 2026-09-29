from fastapi import FastAPI

from app.BIKE.router import router as bike_router
from app.core.config import get_settings
from app.CROWD.router import router as crowd_router
from app.ROUTE.router import router as route_router
from app.TIME.router import router as time_router
from app.TIME.router import snapshot_age_sec

settings = get_settings()

app = FastAPI(title=settings.app_name)

app.include_router(crowd_router)
app.include_router(bike_router)
app.include_router(route_router)
app.include_router(time_router)


@app.get("/health")
def health() -> dict[str, object]:
    # 스냅샷(latest_stock.parquet)이 오래되면 재안내가 전부 unavailable이 되므로 외부 감시가
    # 볼 수 있게 나이만 노출한다 — 신선도 판정은 감시 쪽이 하고 status는 계속 ok다.
    return {"status": "ok", "snapshotAgeSec": snapshot_age_sec()}
