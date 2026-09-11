"""CROWD 조회 API — 요청 검증·응답 변환만 하고 로직은 service로 위임한다.

배치(`pipeline/batch_predict.py`)가 만든 날짜별 예측 표를 조회한다. 그 날짜 표가 없으면(배치 미실행)
404로 응답해 BE가 "역이 없다"와 구분할 수 있게 한다. 존재하지 않는 역은 빈 `slots`로 200을 준다
(역 목록은 BE가 별도로 가짐).
"""

from __future__ import annotations

from datetime import date as date_type
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from app.CROWD import service
from app.CROWD.schemas import CrowdMetaResponse, LineCongestionResponse, StationCongestionResponse

router = APIRouter(prefix="/crowd", tags=["crowd"])

DateQ = Annotated[date_type, Query(description="YYYY-MM-DD")]
DirectionQ = Annotated[str | None, Query(description="상선/하선/내선/외선. 생략 시 전부")]
TimeQ = Annotated[str, Query(alias="time", description="30분 슬롯 시작, 예: 08:30")]


def _no_table(date: date_type) -> HTTPException:
    return HTTPException(
        status_code=404, detail=f"{date} 예측 표가 없다 — 배치 미실행 (GET /crowd/meta 참고)"
    )


@router.get("/meta", response_model=CrowdMetaResponse)
def get_meta() -> dict:
    return service.crowd_meta()


@router.get("/stations/{station_no}/congestion", response_model=StationCongestionResponse)
def get_station_congestion(station_no: int, date: DateQ, direction: DirectionQ = None) -> dict:
    result = service.station_congestion(date, station_no, direction)
    if result is None:
        raise _no_table(date)
    return result


@router.get("/lines/{line}/congestion", response_model=LineCongestionResponse)
def get_line_congestion(line: str, date: DateQ, time_slot_30min: TimeQ) -> dict:
    result = service.line_congestion(date, line, time_slot_30min)
    if result is None:
        raise _no_table(date)
    return result
