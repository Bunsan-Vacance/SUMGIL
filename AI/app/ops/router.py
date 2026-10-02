"""운영 지표 라우터 — Grafana Infinity(JSON) 데이터소스가 읽는 읽기 전용 GET.

인증이 없다: 내부망(클러스터 안 Grafana -> AI 서비스)에서만 닿는다는 전제이며 외부에 노출하지 않는다.
서버에서는 Ingress가 `/ai`를 앞에 붙여 `/ai/ops/...`가 된다. 로직은 service에 위임한다.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from app.ops import service
from app.ops.schemas import (
    DataQualityAvailabilityRow,
    DataQualityFeatureRow,
    DataQualityLineRow,
    DataQualityOutlierRow,
    DataQualityRow,
    DataQualityTargetRow,
    GateRow,
    JobRow,
    ScoreByLineRow,
    ScoreDailyRow,
    SparkRunRow,
)

router = APIRouter(prefix="/ops", tags=["ops"])

DaysQ = Annotated[int, Query(ge=1, le=365, description="최근 N일(채점 파티션 기준)")]
SourceQ = Annotated[str, Query(description="champion | shadow:<artifact>")]


@router.get("/score-daily", response_model=list[ScoreDailyRow])
def get_score_daily(days: DaysQ = 30, source: SourceQ = "champion") -> list[dict]:
    try:
        return service.score_daily(days, source)
    except service.InvalidSourceError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/score-daily/by-line", response_model=list[ScoreByLineRow])
def get_score_by_line(days: DaysQ = 30) -> list[dict]:
    return service.score_by_line(days)


@router.get("/gate", response_model=list[GateRow])
def get_gate(limit: Annotated[int, Query(ge=1, le=200)] = 10) -> list[dict]:
    return service.gate(limit)


@router.get("/jobs", response_model=list[JobRow])
def get_jobs(
    limit: Annotated[int, Query(ge=1, le=200, description="최근 run 수")] = 20,
) -> list[dict]:
    return service.jobs(limit)


@router.get("/spark-runs", response_model=list[SparkRunRow])
def get_spark_runs(limit: Annotated[int, Query(ge=1, le=500)] = 50) -> list[dict]:
    return service.spark_runs(limit)


@router.get("/data-quality", response_model=list[DataQualityRow])
def get_data_quality(days: DaysQ = 30) -> list[dict]:
    return service.data_quality(days)


@router.get("/data-quality/lines", response_model=list[DataQualityLineRow])
def get_data_quality_lines(days: DaysQ = 30) -> list[dict]:
    return service.data_quality_lines(days)


@router.get("/data-quality/outliers", response_model=list[DataQualityOutlierRow])
def get_data_quality_outliers(
    date: Annotated[str | None, Query(description="YYYY-MM-DD, 생략하면 최신 파티션")] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
) -> list[dict]:
    if date is not None and not date.strip():
        date = None  # Grafana textbox 변수가 비면 ?date= 로 온다 -> 최신 파티션
    try:
        return service.data_quality_outliers(date, limit)
    except service.InvalidDateError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/data-quality/features", response_model=list[DataQualityFeatureRow])
def get_data_quality_features(days: DaysQ = 8) -> list[dict]:
    return service.data_quality_features(days)


@router.get("/data-quality/targets", response_model=list[DataQualityTargetRow])
def get_data_quality_targets(days: DaysQ = 8) -> list[dict]:
    return service.data_quality_targets(days)


@router.get("/data-quality/availability", response_model=list[DataQualityAvailabilityRow])
def get_data_quality_availability(days: DaysQ = 8) -> list[dict]:
    return service.data_quality_availability(days)
