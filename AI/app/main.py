import logging

from fastapi import FastAPI

from app.BIKE.router import router as bike_router
from app.core.config import get_settings
from app.CROWD.router import router as crowd_router
from app.ops.router import router as ops_router
from app.ROUTE.router import router as route_router
from app.TIME.router import router as time_router
from app.TIME.router import snapshot_age_sec

settings = get_settings()

# uvicorn은 자기 로거(uvicorn.*)만 설정하고 루트는 WARNING이라 app.* 의 INFO(예: TIME `reroute_check`
# 운영 로그)는 아무 데도 안 나간다. app 로거에만 stdout 핸들러를 달아 접근 로그와 같은 파일로 보낸다.
# 테스트·재import로 두 번 달리지 않게 핸들러 유무를 본다.
_app_log = logging.getLogger("app")
if not _app_log.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(levelname)s:     [%(name)s] %(message)s"))
    _app_log.addHandler(_handler)
    _app_log.setLevel(logging.INFO)

app = FastAPI(title=settings.app_name)

app.include_router(crowd_router)
app.include_router(bike_router)
app.include_router(route_router)
app.include_router(time_router)
app.include_router(ops_router)


@app.get("/health")
def health() -> dict[str, object]:
    # 스냅샷(latest_stock.parquet)이 오래되면 재안내가 전부 unavailable이 되므로 외부 감시가
    # 볼 수 있게 나이만 노출한다 — 신선도 판정은 감시 쪽이 하고 status는 계속 ok다.
    return {"status": "ok", "snapshotAgeSec": snapshot_age_sec()}
