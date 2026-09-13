"""LightGBM 학습·추론에 쓰는 feature 정의와 historical profile 계산.

`validation/BYC/q3-seasonal-dataset-check/src/phase1_baseline.py`(Phase 1 최소셋)와
`phase2_historical_profile.py`(과거 프로파일 추가)에서 검증된 것을 승격했다 — validation
쪽 실험은 `--sample-frac`·`--train-months` 등으로 스케일을 바꿔가며 비교하는 게 목적이라
계속 거기 남겨두고, 여기는 한 세트(v3: 최소셋 + historical profile + 공휴일)로 고정한다.

historical profile은 station×dow×hour×horizon 과거 평균/표준편차를 **train 기간으로만**
fit하고 valid/test엔 조인만 한다(leakage 방지, fallback 3단계: 정확한 조합 →
station×horizon → horizon 전체 — `validation/BYC/reference-notes`의 원래 Phase 2 설계와 동일).
"""

from __future__ import annotations

import pandas as pd

# ── Phase 1 최소셋 ──
BASE_FEATURE_COLS = [
    "horizon_min",
    "stock_anchor_hour",
    "stock_ratio_hour",
    "minutes_since_stock_anchor",
    "is_empty_anchor",
    "is_full_anchor",
    "hour",
    "minute",
    "day_of_week",
    "is_weekend",
    "month",
    "sin_hour",
    "cos_hour",
    "sin_slot",
    "cos_slot",
]

# ── Phase 2: historical profile ──
PROFILE_KEYS_FULL = ["od_station_id", "day_of_week", "hour", "horizon_min"]
PROFILE_KEYS_STATION_HORIZON = ["od_station_id", "horizon_min"]
PROFILE_KEYS_GLOBAL = ["horizon_min"]
PROFILE_STAT_COLS = [
    "historical_net_flow_mean",
    "historical_net_flow_std",
    "historical_rent_mean",
    "historical_return_mean",
]
HISTORICAL_FEATURE_COLS = [*PROFILE_STAT_COLS, "historical_profile_fallback_level"]

# ── v3: + 공휴일 ──
FEATURE_COLS = [*BASE_FEATURE_COLS, *HISTORICAL_FEATURE_COLS, "is_holiday"]
MODEL_FEATURE_COLS = [*FEATURE_COLS, "station_code"]

TARGET_COL = "target_net_flow"
HORIZONS = [5, 10, 15, 30]


def downcast_memory(df: pd.DataFrame) -> pd.DataFrame:
    """메모리 절감 — float64→float32, int64는 저정밀 정수로 다운캐스트.

    전체 대여소 스케일(수천만~1억 행)에서 이게 없으면 쉽게 메모리 한계에 부딪힌다
    (`AI/CLAUDE.md`, `validation/BYC/full-coverage-check/RESULTS.md`의 메모리 실측 참고).
    """
    for col in df.columns:
        if df[col].dtype == "float64":
            df[col] = df[col].astype("float32")
        elif df[col].dtype == "int64":
            df[col] = pd.to_numeric(df[col], downcast="integer")
    return df


def build_station_dtype(*sources: pd.DataFrame | set[str]) -> pd.CategoricalDtype:
    """DataFrame과 station id set을 섞어서 받아 합집합으로 station_code용 dtype을 만든다.

    train만으로 만들면 valid/test에만 있는 station이 unknown 처리된다 — 반드시
    train∪valid∪test 전체를 훑어서 만든다(Phase 2.5에서 겪은 문제, RESULTS.md 참고).
    """
    ids: set[str] = set()
    for src in sources:
        if isinstance(src, pd.DataFrame):
            ids |= set(src["od_station_id"])
        else:
            ids |= set(src)
    return pd.CategoricalDtype(categories=sorted(ids))


def apply_station_code(
    df: pd.DataFrame, dtype: pd.CategoricalDtype, label: str = "df"
) -> pd.DataFrame:
    codes = df["od_station_id"].astype(dtype).cat.codes
    unknown = int((codes == -1).sum())
    assert (
        unknown == 0
    ), f"{label}: station_code 매핑 안 된 station {unknown}건 — dtype 구성 범위 확인 필요"
    df["station_code"] = codes
    return df


def make_xy(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series]:
    return df[MODEL_FEATURE_COLS].fillna(0), df[TARGET_COL].fillna(0)


class HistoricalProfileBuilder:
    """station × 요일 × 시간 × horizon 과거 통계를 train 기간으로만 계산하고 조인한다."""

    def __init__(self) -> None:
        self.full: pd.DataFrame | None = None
        self.station_horizon: pd.DataFrame | None = None
        self.global_: pd.DataFrame | None = None

    @staticmethod
    def _aggregate(df: pd.DataFrame, keys: list[str]) -> pd.DataFrame:
        return (
            df.groupby(keys)
            .agg(
                historical_net_flow_mean=(TARGET_COL, "mean"),
                historical_net_flow_std=(TARGET_COL, "std"),
                historical_rent_mean=("target_rent_count", "mean"),
                historical_return_mean=("target_return_count", "mean"),
            )
            .reset_index()
        )

    def fit(self, train_df: pd.DataFrame) -> HistoricalProfileBuilder:
        self.full = self._aggregate(train_df, PROFILE_KEYS_FULL)
        self.station_horizon = self._aggregate(train_df, PROFILE_KEYS_STATION_HORIZON)
        self.global_ = self._aggregate(train_df, PROFILE_KEYS_GLOBAL)
        return self

    def transform(self, df: pd.DataFrame) -> pd.DataFrame:
        if self.full is None:
            raise RuntimeError("fit()을 먼저 호출해야 한다.")
        merged = df.merge(self.full, on=PROFILE_KEYS_FULL, how="left")
        merged["historical_profile_fallback_level"] = 0

        missing = merged["historical_net_flow_mean"].isna()
        if missing.any():
            fallback = merged.loc[missing, PROFILE_KEYS_STATION_HORIZON].merge(
                self.station_horizon, on=PROFILE_KEYS_STATION_HORIZON, how="left"
            )
            for col in PROFILE_STAT_COLS:
                merged.loc[missing, col] = fallback[col].to_numpy()
            merged.loc[missing, "historical_profile_fallback_level"] = 1

        still_missing = merged["historical_net_flow_mean"].isna()
        if still_missing.any():
            fallback = merged.loc[still_missing, PROFILE_KEYS_GLOBAL].merge(
                self.global_, on=PROFILE_KEYS_GLOBAL, how="left"
            )
            for col in PROFILE_STAT_COLS:
                merged.loc[still_missing, col] = fallback[col].to_numpy()
            merged.loc[still_missing, "historical_profile_fallback_level"] = 2

        merged["historical_net_flow_std"] = merged["historical_net_flow_std"].fillna(0.0)
        return downcast_memory(merged)

    # ── 아티팩트 ──
    def save(self, out_dir) -> None:
        from pathlib import Path

        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        self.full.to_parquet(out_dir / "historical_profile_full.parquet", index=False)
        self.station_horizon.to_parquet(
            out_dir / "historical_profile_station_horizon.parquet", index=False
        )
        self.global_.to_parquet(out_dir / "historical_profile_global.parquet", index=False)

    @classmethod
    def load(cls, out_dir) -> HistoricalProfileBuilder:
        from pathlib import Path

        out_dir = Path(out_dir)
        model = cls()
        model.full = pd.read_parquet(out_dir / "historical_profile_full.parquet")
        model.station_horizon = pd.read_parquet(
            out_dir / "historical_profile_station_horizon.parquet"
        )
        model.global_ = pd.read_parquet(out_dir / "historical_profile_global.parquet")
        return model
