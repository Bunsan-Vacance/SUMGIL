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
