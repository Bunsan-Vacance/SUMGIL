"""예측기 인터페이스와 레지스트리 — 배치 잡·API는 이 이음새 하나만 본다.

CROWD의 `predictor.py`와 같은 목적(모델 계열을 바꿔도 프로덕션 경로가 특정 모델에
안 묶이게)이지만, 출력 형태가 다르다 — CROWD는 시각별 승하차를, BIKE는 `bike_stock_pred`
행(rental_id·time_slot·exp_bikes·p_empty·p_full) 자체를 낸다.

| kind | 구현 | 상태 |
| --- | --- | --- |
| `avg` | station×dow_type×time_slot 실측 평균/빈도(`lookup.StockProfileBaseline`) | 사용 가능 — **기본값** |
| `lightgbm` | 날짜축 멀티소스 모델(`train_multisource.py`) → exp_bikes/p_empty/p_full | 구현됨, `source=model` 기본 전환은 **BE의 pred_date 스키마 동의 이후로 보류**(2026-09-14) |

avg를 기본값으로 두는 이유는 CROWD의 lookup 우선 철학과 같다 — 정직한 baseline이 먼저
프로덕션에 들어가야, 나중에 lightgbm 소스로 바꿨을 때 그것이 avg보다 실제로 나은지가
드러난다. LightGBM(날짜축 멀티소스)은 `validation/BYC/lightgbm-stock-conversion-check
/RESULTS.md`에서 세 지표(exp_bikes -11.6%, p_full -12.4%, p_empty -1.8%) 모두 avg를
넘는 게 검증됐다.

**`predict_all()`이 `target_date`를 받는다** — `avg`는 날짜 개념이 없어 무시하고,
`lightgbm`은 그 날짜의 요일·공휴일·날씨·KBO 맥락으로 다른 값을 낸다. 그래서 두 kind의
출력 스키마가 다르다(avg는 `dow_type`, lightgbm은 `pred_date`) — 이 차이 자체가 B4-2의
핵심(날짜별로 달라야 날씨·KBO가 반영됨, 계획서 1단계) 이고, BE와 협의 중인 스키마
변경(`dow_type`→`pred_date`) 승인 전까지는 `batch_predict.py`가 `avg`만 기본으로 쓴다.

**서빙 시점 데이터 갭(계획서 Phase D, 미해결)**: D-1/D-7 lag는 아티팩트에 저장된
학습 당시 lookup(2024~2025 Q3)만 조회한다 — 그 범위 밖 날짜(운영 중 "진짜 어제")는
아직 `bike_realtime.py` 수집기와 연결이 안 돼 있어 hist_mean으로 대체된다. 날씨도
예보가 아니라 실측만 지원한다(예보 이력 없음). 둘 다 값을 채우지 않고 결측으로 두는
대신, 지금은 fallback으로 대체하고 있다는 걸 기록해둔다(원칙 8과 완전히 부합하진
않지만, 학습 때도 같은 fallback을 썼으므로 train/serve 일관성은 있음).
"""

from __future__ import annotations

import json
import pickle
from datetime import date
from pathlib import Path
from typing import Protocol, runtime_checkable

import numpy as np
import pandas as pd

from app.BIKE.pipeline.calendar import attach_dow_type, load_holidays
from app.BIKE.pipeline.dataset import load_station_static
from app.BIKE.pipeline.external_features import (
    attach_external,
    jamsil_nearby_stations,
    load_jamsil_game_dates,
    load_weather,
)
from app.BIKE.pipeline.features import MULTISOURCE_FEATURE_COLS, fill_lag_fallback
from app.BIKE.pipeline.lag_features import attach_lag
from app.BIKE.pipeline.lookup import StockProfileBaseline

OUTPUT_COLS = ["rental_id", "dow_type", "time_slot", "exp_bikes", "p_empty", "p_full"]
DATE_OUTPUT_COLS = ["rental_id", "pred_date", "time_slot", "exp_bikes", "p_empty", "p_full"]
Z_90 = 1.2816
KEY_COLS = ["rental_id", "dow_type", "time_slot"]
VALUE_COLS = ["exp_bikes", "p_empty", "p_full"]
DOW_TYPES = [0, 1, 2]
TIME_SLOTS = list(range(48))


@runtime_checkable
class Predictor(Protocol):
    """모든 예측기가 지키는 계약."""

    kind: str
    version: str

    def predict_all(self, target_date: date | None = None) -> pd.DataFrame:
        """예측 표 + `source` 컬럼. `avg`는 dow_type 기준(OUTPUT_COLS, target_date 무시),
        `lightgbm`은 pred_date 기준(DATE_OUTPUT_COLS)."""
        ...


class AvgPredictor:
    """station×dow_type×time_slot 실측 평균/빈도 조회(`StockProfileBaseline`)."""

    kind = "avg"

    def __init__(self, baseline: StockProfileBaseline, version: str = "avg") -> None:
        self.baseline = baseline
        self.version = version

    @classmethod
    def load(cls, path: Path) -> AvgPredictor:
        return cls(StockProfileBaseline.load(path), version=f"avg:{Path(path).parent.name}")

    def predict_all(self, target_date: date | None = None) -> pd.DataFrame:
        out = self.baseline.predict()
        out = complete_station_fallback_grid(out)
        out["source"] = "avg"
        return out.reindex(columns=[*OUTPUT_COLS, "source", "prediction_source"])


def complete_station_fallback_grid(table: pd.DataFrame) -> pd.DataFrame:
    """관측 대여소별 3×48 grid를 만들고 같은 대여소 내부 평균으로만 채운다."""
    observed = table.reindex(columns=OUTPUT_COLS).copy()
    observed = observed.dropna(subset=KEY_COLS)
    observed = observed.drop_duplicates(subset=KEY_COLS, keep="last")

    stations = sorted(observed["rental_id"].unique())
    grid = pd.MultiIndex.from_product([stations, DOW_TYPES, TIME_SLOTS], names=KEY_COLS).to_frame(
        index=False
    )

    out = grid.merge(observed, on=KEY_COLS, how="left")
    observed_mask = out[VALUE_COLS].notna().all(axis=1)
    out["prediction_source"] = pd.NA
    out.loc[observed_mask, "prediction_source"] = "observed_avg"

    station_time = (
        observed.groupby(["rental_id", "time_slot"], as_index=False)[VALUE_COLS]
        .mean()
        .rename(columns={col: f"{col}_station_time" for col in VALUE_COLS})
    )
    out = out.merge(station_time, on=["rental_id", "time_slot"], how="left")
    _fill_missing(out, "station_time", "station_time_fallback")

    station_global = (
        observed.groupby("rental_id", as_index=False)[VALUE_COLS]
        .mean()
        .rename(columns={col: f"{col}_station_global" for col in VALUE_COLS})
    )
    out = out.merge(station_global, on="rental_id", how="left")
    _fill_missing(out, "station_global", "station_global_fallback")

    return out.reindex(columns=[*OUTPUT_COLS, "prediction_source"])


def _fill_missing(frame: pd.DataFrame, suffix: str, prediction_source: str) -> None:
    missing = frame[VALUE_COLS].isna().any(axis=1)
    fallback_cols = [f"{col}_{suffix}" for col in VALUE_COLS]
    available = frame[fallback_cols].notna().all(axis=1)
    mask = missing & available
    for col in VALUE_COLS:
        frame.loc[mask, col] = frame.loc[mask, f"{col}_{suffix}"]
    frame.loc[mask, "prediction_source"] = prediction_source


class LightGBMPredictor:
    """날짜축 멀티소스 모델(`train_multisource.py` 아티팩트) → exp_bikes/p_empty/p_full.

    `target_date`가 없으면 오늘 날짜로 예측한다. 전체 역 × 48 time_slot 그리드를 만들고,
    그 날짜의 요일·공휴일·날씨(실측만)·KBO·D-1/D-7 lag(학습 당시 lookup 범위 내에서만)를
    붙여서 exp_bikes 모델 1개 + quantile 3개로 예측한다.
    """

    kind = "lightgbm"

    def __init__(self, artifact_dir: Path) -> None:
        self.artifact_dir = Path(artifact_dir)
        self.version = f"lightgbm:{self.artifact_dir.name}"
        self._loaded = False

    @classmethod
    def load(cls, artifact_dir: Path) -> LightGBMPredictor:
        return cls(artifact_dir)

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        import lightgbm as lgb

        d = self.artifact_dir
        self._model_exp_bikes = lgb.Booster(model_file=str(d / "model_exp_bikes.txt"))
        self._q_models = {
            q: lgb.Booster(model_file=str(d / f"model_q{int(q * 100)}.txt"))
            for q in (0.1, 0.5, 0.9)
        }
        with (d / "isotonic_empty.pkl").open("rb") as f:
            self._iso_empty = pickle.load(f)
        with (d / "isotonic_full.pkl").open("rb") as f:
            self._iso_full = pickle.load(f)
        self._profile = pd.read_parquet(d / "historical_profile.parquet")
        self._lag_lookup = pd.read_parquet(d / "lag_lookup.parquet")
        categories = json.loads((d / "station_categories.json").read_text(encoding="utf-8"))
        self._station_dtype = pd.CategoricalDtype(categories=categories)
        meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
        self._global_mean = meta["global_mean"]
        self._loaded = True

    def _build_grid(self, target_date: pd.Timestamp, station_static: pd.DataFrame) -> pd.DataFrame:
        grid = station_static[["od_station_id", "rack_count"]].merge(
            pd.DataFrame({"time_slot": range(48)}), how="cross"
        )
        grid["date"] = target_date
        grid["hour"] = grid["time_slot"] // 2  # attach_external의 anchor 기준 hour 근사(30분 이내)
        grid["target_hour"] = grid["time_slot"] // 2
        grid["target_minute"] = (grid["time_slot"] % 2) * 30
        grid["target_dow"] = target_date.dayofweek
        grid["target_is_weekend"] = int(target_date.dayofweek >= 5)
        grid["target_month"] = target_date.month
        grid["target_sin_hour"] = np.sin(2 * np.pi * grid["target_hour"] / 24)
        grid["target_cos_hour"] = np.cos(2 * np.pi * grid["target_hour"] / 24)
        return grid

    def predict_all(self, target_date: date | None = None) -> pd.DataFrame:
        self._ensure_loaded()
        target_date = pd.Timestamp(target_date or pd.Timestamp.now().date()).normalize()

        holidays = load_holidays()
        weather = load_weather()
        jamsil_dates = load_jamsil_game_dates()
        station_static = load_station_static()
        jamsil_stations = jamsil_nearby_stations(station_static)

        grid = self._build_grid(target_date, station_static)
        grid = attach_external(grid, weather, holidays, jamsil_dates, jamsil_stations)
        grid = attach_dow_type(grid, holidays)
        grid = attach_lag(grid, self._lag_lookup, 1, "lag1d_stock")
        grid = attach_lag(grid, self._lag_lookup, 7, "lag7d_stock")

        merged = grid.merge(
            self._profile, on=["od_station_id", "dow_type", "time_slot"], how="left"
        )
        merged["hist_mean"] = merged["hist_mean"].fillna(self._global_mean)
        merged["hist_std"] = merged["hist_std"].fillna(0.0)
        merged = fill_lag_fallback(merged)
        merged["station_code"] = merged["od_station_id"].astype(self._station_dtype).cat.codes

        x = merged[MULTISOURCE_FEATURE_COLS].fillna(0)
        hist_mean = merged["hist_mean"].to_numpy()

        exp_bikes = hist_mean + self._model_exp_bikes.predict(x)
        q10 = hist_mean + self._q_models[0.1].predict(x)
        q50 = hist_mean + self._q_models[0.5].predict(x)
        q90 = hist_mean + self._q_models[0.9].predict(x)
        sigma = np.where((q90 - q10) <= 1e-6, 1e-6, (q90 - q10) / (2 * Z_90))

        from scipy.stats import norm

        p_empty_raw = norm.cdf(0.0, loc=q50, scale=sigma)
        p_full_raw = 1 - norm.cdf(merged["rack_count"].to_numpy(), loc=q50, scale=sigma)
        merged["exp_bikes"] = np.clip(exp_bikes, 0, merged["rack_count"])
        merged["p_empty"] = self._iso_empty.predict(p_empty_raw)
        merged["p_full"] = self._iso_full.predict(p_full_raw)
        merged["rental_id"] = merged["od_station_id"]
        merged["pred_date"] = target_date.date()
        merged["source"] = "model"
        return merged.reindex(columns=[*DATE_OUTPUT_COLS, "source"])


def build_predictor(kind: str, **cfg) -> Predictor:
    """설정 문자열로 예측기를 만든다.

    - `avg`: `baseline_path`(parquet) 또는 `baseline`(StockProfileBaseline 인스턴스) 중 하나.
    - `lightgbm`: `artifact_dir`(`train_multisource.py`가 저장한 아티팩트 디렉터리) 필수.
    """
    if kind == "avg":
        if cfg.get("baseline_path"):
            return AvgPredictor.load(Path(cfg["baseline_path"]))
        if cfg.get("baseline") is not None:
            return AvgPredictor(cfg["baseline"])
        raise ValueError("avg 예측기는 baseline_path 또는 baseline이 필요하다")
    if kind == "lightgbm":
        if not cfg.get("artifact_dir"):
            raise ValueError("lightgbm 예측기는 artifact_dir이 필요하다")
        return LightGBMPredictor.load(Path(cfg["artifact_dir"]))
    raise ValueError(f"알 수 없는 예측기: {kind} (가능: avg, lightgbm)")


def latest_artifact(models_dir: Path, prefix: str = "") -> Path | None:
    """`models/BIKE/` 아래 가장 최근(이름 기준 정렬) 아티팩트 디렉터리."""
    models_dir = Path(models_dir)
    if not models_dir.exists():
        return None
    dirs = sorted(
        p
        for p in models_dir.iterdir()
        if p.is_dir() and p.name.startswith(prefix) and (p / "meta.json").exists()
    )
    return dirs[-1] if dirs else None
