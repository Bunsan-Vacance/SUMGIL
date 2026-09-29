"""BIKE 조회 API — 요청 검증·응답 변환만 하고 로직은 service로 위임한다.

`/meta`, `/stations/{id}/stock`은 배치(`pipeline/batch_predict.py`)가 만든 단일 최신
`bike_stock_pred_*.parquet`을 조회한다. 표가 아예 없으면(배치 미실행) 404, 존재하지
않는 대여소는 빈 `slots`로 200을 준다(CROWD와 동일한 구분 원칙). BE는 이 두 API를
호출하지 않고 같은 산출물을 자기 DB로 적재해서 쓴다(S15P21A104-115, -73과 같은
ETL 패턴) — 이 둘은 로컬 검증·시연(-83)용 병행 계층이다.

`/stations/{id}/eta-stock`은 다르다 — BE가 사용자 경로 조회 시점마다 실시간으로
호출하는 API다(S15P21A104-159/-160). 실시간 재고 + anchor+horizon LightGBM(v4_weather)이
직접 예측한 순증감으로 도착 시점 재고를 계산해서 즉시 반환한다 — 배치표는 이 경로에서
전혀 안 읽는다. 이 호출이 실패(404/503)하면 BE는 자체 DB의 배치 통계로 폴백한다 —
그래서 실패는 애매하게 감추지 않고 명확한 상태코드로 드러낸다.

**학습 시점에 없던 역(신규 개설 대여소 등)은 503이 아니다** — `service.py`가
`UnknownStation`을 잡아서 station 무관 전역 평균으로 200을 준다(`source:
lightgbm_global_fallback`). 503은 모델 아티팩트 파일 자체가 망가진 진짜 장애일 때만 난다.

`eta_minutes`가 학습 horizon 상한(30분)을 넘어도 거부하지 않는다 — `predictor_eta.round_horizon()`이
가장 가까운 학습 horizon(5·10·15·30)으로 근사해서 그대로 예측값을 낸다(30 초과는 전부 30으로 근사).
도착 시점 라벨(`arrival_dow_type`/`arrival_time_slot`)은 근사 없이 요청받은 `eta_minutes` 그대로
계산된다 — 근사되는 건 재고 예측치뿐이다. 상한 1440분(24시간)은 명백히 잘못된 입력만 걸러내는
용도다.

시연용 override: `time_debug_force_trigger_enabled`가 켜져 있고 `debug_empty_rental_ids`에
든 대여소는 정상 결과를 `service.apply_debug_override`가 고갈(`predicted_stock=0.0`,
`p_empty=1.0`, `source=debug_override`)로 덮어쓴다 — TIME 재안내 판단과 같은 게이트라 경로
카드와 팝업 숫자가 어긋나지 않는다. 운영(기본값)에서는 타지 않고, 404/503 예외 경로는 덮지 않는다.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from app.BIKE import service
from app.BIKE.schemas import BikeMetaResponse, EtaStockResponse, StationStockResponse
from app.core.config import get_settings

router = APIRouter(prefix="/bike", tags=["bike"])

DowTypeQ = Annotated[
    int | None, Query(ge=0, le=2, description="0 평일 / 1 토 / 2 일·공휴일. 생략 시 전부")
]

EtaMinutesQ = Annotated[
    int,
    Query(
        ge=0,
        le=1440,
        description="도착까지 예상 분. 30분 초과 요청은 30분 기준 예측값을 그대로 반환한다",
    ),
]


def _no_table() -> HTTPException:
    return HTTPException(
        status_code=404, detail="bike_stock_pred 표가 없다 — 배치 미실행 (GET /bike/meta 참고)"
    )


@router.get("/meta", response_model=BikeMetaResponse)
def get_meta() -> dict:
    return service.bike_meta()


@router.get("/stations/{rental_id}/stock", response_model=StationStockResponse)
def get_station_stock(rental_id: str, dow_type: DowTypeQ = None) -> dict:
    result = service.station_stock(rental_id, dow_type)
    if result is None:
        raise _no_table()
    return result


@router.get("/stations/{rental_id}/eta-stock", response_model=EtaStockResponse)
def get_eta_stock(rental_id: str, eta_minutes: EtaMinutesQ) -> dict:
    try:
        result = service.predict_eta_stock(rental_id, eta_minutes)
    except service.LiveStockMissing as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except service.ModelUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return service.apply_debug_override(result, get_settings())
