"""BIKE 조회 API — 요청 검증·응답 변환만 하고 로직은 service로 위임한다.

`/meta`, `/stations/{id}/stock`은 배치(`pipeline/batch_predict.py`)가 만든 단일 최신
`bike_stock_pred_*.parquet`을 조회한다. 표가 아예 없으면(배치 미실행) 404, 존재하지
않는 대여소는 빈 `slots`로 200을 준다(CROWD와 동일한 구분 원칙). BE는 이 두 API를
호출하지 않고 같은 산출물을 자기 DB로 적재해서 쓴다(S15P21A104-115, -73과 같은
ETL 패턴) — 이 둘은 로컬 검증·시연(-83)용 병행 계층이다.

`/stations/{id}/eta-stock`은 다르다 — BE가 사용자 경로 조회 시점마다 실시간으로
호출하는 API다(S15P21A104-159). 실시간 재고 + avg 표 델타로 도착 시점 재고를
계산해서 즉시 반환한다. 이 호출이 실패(404 등)하면 BE는 자체 DB의 배치 통계로
폴백한다 — 그래서 실패는 애매하게 감추지 않고 명확한 상태코드로 드러낸다.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from app.BIKE import service
from app.BIKE.schemas import BikeMetaResponse, EtaStockResponse, StationStockResponse

router = APIRouter(prefix="/bike", tags=["bike"])

DowTypeQ = Annotated[
    int | None, Query(ge=0, le=2, description="0 평일 / 1 토 / 2 일·공휴일. 생략 시 전부")
]

EtaMinutesQ = Annotated[int, Query(ge=0, le=30, description="도착까지 예상 분(0~30)")]


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
        return service.predict_eta_stock(rental_id, eta_minutes)
    except service.LiveStockMissing as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except service.AvgDataMissing as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
