"""CROWD 조회 API 응답 모델.

숫자를 낼 수 없는 셀은 값을 채우지 않고 `data_status`로 알린다(원칙 8):
- `ok` — 예측·배율 모두 정상
- `no_lookup` — 학습 구간에 없는 요일유형×역×시간대라 기준선 자체가 없음
- `no_calibration` — 배율표가 없는 셀(2호선 지선 방향 체계, 1~8호선 공휴일, 결번 역)
- `no_data` — 그 날짜의 예측 표가 아직 생성되지 않음(배치 미실행)
"""

from __future__ import annotations

from datetime import date as date_type

from pydantic import BaseModel, Field


class SlotCongestion(BaseModel):
    time_slot_30min: str = Field(description="30분 슬롯 시작 시각, 예: '08:30'")
    direction: str = Field(description="상선/하선 또는 내선/외선(2호선)")
    congestion_pct: float | None = Field(
        description="보정 혼잡도(%). 정원 100% 기준, 결측이면 null"
    )
    grade: int | None = Field(
        description="등급 0..N (임계치는 meta.grade_thresholds). 결측이면 null"
    )
    data_status: str


class StationCongestionResponse(BaseModel):
    date: date_type
    station_no: int
    station_name: str | None
    line: str | None
    train_capacity: int | None
    predictor_version: str | None
    lag1d_available: bool | None = Field(
        description="전날 실측이 있었는지. False면 1주 전 시차만으로 예측"
    )
    slots: list[SlotCongestion]


class LineStationSnapshot(BaseModel):
    station_no: int
    station_name: str | None
    direction: str
    congestion_pct: float | None
    grade: int | None
    data_status: str


class LineCongestionResponse(BaseModel):
    date: date_type
    line: str
    time_slot_30min: str
    stations: list[LineStationSnapshot]


class CrowdMetaResponse(BaseModel):
    available_dates: list[date_type]
    grade_thresholds: list[float]
    predictor: str | None
    predictor_version: str | None
    generated_at: str | None
    status_counts: dict[str, int] | None
    topology_gaps: list[dict] | None
