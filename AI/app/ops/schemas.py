"""운영 지표 응답 모델 — Grafana Infinity가 그대로 표로 읽도록 전부 평평하게(중첩 없음) 둔다."""

from __future__ import annotations

from pydantic import BaseModel


class ScoreDailyRow(BaseModel):
    date: str
    source: str
    availability: str | None = None
    predictor_version: str | None = None
    rows_scored: int | None = None
    missing_station_count: int | None = None
    boarding_rmse_model: float | None = None
    boarding_rmse_lookup: float | None = None
    boarding_improvement_rmse_pct: float | None = None
    boarding_mae_model: float | None = None
    alighting_rmse_model: float | None = None
    alighting_rmse_lookup: float | None = None
    alighting_improvement_rmse_pct: float | None = None
    alighting_mae_model: float | None = None


class ScoreByLineRow(BaseModel):
    date: str
    line: str
    n: int | None = None
    boarding_rmse_model: float | None = None
    boarding_improvement_rmse_pct: float | None = None
    alighting_rmse_model: float | None = None
    alighting_improvement_rmse_pct: float | None = None


class GateRow(BaseModel):
    run: str
    mode: str | None = None
    window_start: str | None = None
    window_end: str | None = None
    decided_at: str | None = None
    accepted: bool
    boarding_point_pp: float | None = None
    boarding_ci_low_pp: float | None = None
    alighting_point_pp: float | None = None
    alighting_ci_low_pp: float | None = None
    registered_shadow: bool


class JobRow(BaseModel):
    run_id: str
    status: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    exit_code: int | None = None
    step: str | None = None
    step_rc: int | None = None
    step_sec: float | None = None


class SparkRunRow(BaseModel):
    job: str
    run: str
    generated_at: str | None = None
    elapsed_sec: float | None = None
    peak_rss_mb: float | None = None
    rows: int | None = None
    input_partitions: int | None = None
    verify_passed: bool | None = None
    verify_max_abs_err: float | None = None
    cores: str | None = None
    driver_memory: str | None = None
    path: str
