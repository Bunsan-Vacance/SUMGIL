"""BIKE 조회 API 응답 모델.

BE `bike_stock_pred` 스키마(rental_id·dow_type·time_slot·exp_bikes·p_empty·p_full·source)와
동일한 필드를 쓴다. CROWD와 달리 날짜별 표가 아니라 **단일 최신 표**라 조회 파라미터에
날짜가 없다 — dow_type(0평일/1토/2일·공휴일)·time_slot(0~47, 30분)만으로 조회한다.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class StockSlot(BaseModel):
    dow_type: int = Field(description="0 평일 / 1 토 / 2 일·공휴일")
    time_slot: int = Field(description="30분 슬롯 인덱스 0~47 (00:00부터)")
    exp_bikes: float | None = Field(description="예상 잔여 대수. 결측이면 null")
    p_empty: float | None = Field(description="0대 확률(0~1). 결측이면 null")
    p_full: float | None = Field(description="만차 확률(0~1). 결측이면 null")
    source: str | None = Field(description="avg|model. 결측이면 null")


class StationStockResponse(BaseModel):
    rental_id: str
    station_name: str | None
    slots: list[StockSlot]


class BikeMetaResponse(BaseModel):
    generated_at: str | None
    source: str | None
    rows: int | None
    stations: int | None


class EtaStockResponse(BaseModel):
    rental_id: str
    eta_minutes: int = Field(description="BE가 넘긴 도착까지 예상 분")
    current_stock: int = Field(description="실시간 재고 파일에서 읽은 현재 재고(대수)")
    predicted_stock: float = Field(
        description="도착 시점 예측 재고. 0 이상으로만 clip, 상한은 BE가 station master로 처리"
    )
    p_empty: float | None = Field(
        description="도착 슬롯 0대 확률(0~1). 분류기 아티팩트 없으면 null"
    )
    p_full: float | None = Field(
        description="도착 슬롯 만차 확률(0~1). 분류기 아티팩트 없으면 null"
    )
    arrival_dow_type: int = Field(description="도착 시점 dow_type(0평일/1토/2일·공휴일)")
    arrival_time_slot: int = Field(description="도착 시점 30분 슬롯(0~47)")
    source: str = Field(
        description="델타 계산에 쓴 예측기. lightgbm(정상) | "
        "lightgbm_global_fallback(학습 시점에 없던 역 — station 무관 전역 평균)"
    )
    model_horizon_min: int = Field(
        description="예측에 실제로 쓰인 horizon(분). eta_minutes가 학습 구간(5·10·15·30)을 "
        "벗어나면 가장 가까운 값으로 근사되며, 30 초과 요청은 항상 30이 된다"
    )
