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


class DataQualityRow(BaseModel):
    date: str
    day_type: str | None = None
    rows: int | None = None
    stations: int | None = None
    expected_stations: int | None = None
    missing_station_count: int | None = None
    nan_ratio: float | None = None
    zero_ratio: float | None = None
    zero_ratio_baseline: float | None = None
    slot_js: float | None = None
    schema_ok: bool | None = None
    collect_lag_days: int | None = None
    outlier_count: int | None = None
    max_abs_line_z: float | None = None
    alert_count: int
    alerts: str
    synthetic: bool | None = None


class DataQualityLineRow(BaseModel):
    date: str
    line: str
    total: float | None = None
    baseline_mean: float | None = None
    baseline_std: float | None = None
    z: float | None = None
    z_adjusted: float | None = None


class DataQualityOutlierRow(BaseModel):
    date: str
    station_no: int | None = None
    station_name: str | None = None
    line: str | None = None
    time_slot: str | None = None
    direction: str | None = None
    value: float | None = None
    baseline_mean: float | None = None
    baseline_std: float | None = None
    z: float | None = None


class DataQualityFeatureRow(BaseModel):
    date: str
    feature: str
    psi: float | None = None
    ks: float | None = None
    ks_p: float | None = None
    level: str | None = None


class DataQualityTargetRow(BaseModel):
    date: str
    target: str
    kind: str
    q5: float | None = None
    q25: float | None = None
    q50: float | None = None
    q75: float | None = None
    q95: float | None = None


class DataQualityAvailabilityRow(BaseModel):
    date: str
    full: float | None = None
    d1_only: float | None = None
    d7_only: float | None = None
    no_lag: float | None = None
