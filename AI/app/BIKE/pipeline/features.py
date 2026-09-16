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

import numpy as np
import pandas as pd

from app.BIKE.pipeline.calendar import attach_dow_type

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

# ── v4: + KBO·D-1/D-7 lag (성능 고도화, S15P21A104-160) ──
# 검증 결과(2026-09-16, v4-kbo-lag_20260916-1651 vs v3-holiday-tuned_20260913-1558, 같은
# train/valid/test 분할) KBO+lag를 같이 넣었더니 MAE/RMSE/R² 전부 v3보다 근소하게
# 나빠졌다 — anchor+horizon 모델은 이미 stock_anchor_hour(실시간 재고)가 있어서, 그
# 신호가 없던 날짜축 모델과 달리 D-1/D-7 lag의 추가 기여가 거의 없었던 것으로 보인다.
# KBO와 lag를 같이 묶어 테스트해서 둘 중 뭐가 원인인지는 분리 안 됨 — 이 세트는 채택 안
# 하고 기록용으로만 남긴다.
KBO_LAG_FEATURE_COLS = [
    "is_kbo_game_jamsil",
    "lag1d_stock",
    "lag1d_stock_available",
    "lag7d_stock",
    "lag7d_stock_available",
]
FEATURE_COLS_V4 = [*FEATURE_COLS, *KBO_LAG_FEATURE_COLS]
MODEL_FEATURE_COLS_V4 = [*FEATURE_COLS_V4, "station_code"]

# ── v4_weather: + 날씨(is_rain·temp) (성능 고도화, S15P21A104-160) ──
# 검증 결과(2026-09-16, v4-weather_20260916-1725 vs v3-holiday-tuned_20260913-1558, 같은
# train/valid/test 분할, validation/BYC/anchor-horizon-feature-check/RESULTS.md) v3 대비
# MAE/RMSE/R² 전부, 모든 split(valid·202507·202508·202509)에서 일관되게 개선 — **채택**.
# KBO_LAG(위)와 독립적으로 검증했다(한 번에 묶으면 원인 구분이 안 됨, KBO_LAG가 그 실수).
# ASOS 실측이 학습·평가 기간을 이미 커버해서 오프라인 학습은 문제없지만, 실시간 서빙에
# 쓰려면 weather.nowcast Kafka 토픽을 bike.stock처럼 최신 스냅샷화하는 별도 인프라가
# 아직 필요하다(미착수).
WEATHER_FEATURE_COLS = ["is_rain", "temp"]
FEATURE_COLS_V4_WEATHER = [*FEATURE_COLS, *WEATHER_FEATURE_COLS]
MODEL_FEATURE_COLS_V4_WEATHER = [*FEATURE_COLS_V4_WEATHER, "station_code"]

# ── v4_distance: + 역 정적 거리(지하철·버스 도보거리) (성능 고도화, S15P21A104-160) ──
# 검증 결과(2026-09-17, v4-distance_20260917-0830 vs v3-holiday-tuned_20260913-1558, 같은
# train/valid/test 분할, validation/BYC/anchor-horizon-feature-check/RESULTS.md) v3 대비
# RMSE·R²는 근소하게 개선되지만 MAE는 근소하게 악화 — 지표마다 방향이 다르고 크기도
# 작아 노이즈 수준으로 판단, **기각**. Phase 3(510개 역, OSRM)에서 나온 "효과 없음"
# 결론이 전체 역(2,583개)·하버사인 거리로도 재현됐다.
# 시간축이 없는 역 단위 정적 피처라 station_code처럼 od_station_id로 조인만 하면 된다.
# Phase 3(validation/BYC/phase3-station-static)에서 OSRM으로 510개 역만 커버했던 걸
# 전체 역(~2,583개)으로 확장해야 해서, 로컬에 OSRM 서버가 없는 대신 하버사인(직선거리)으로
# 대체했다(validation/BYC/anchor-horizon-feature-check/src/build_full_station_distance.py).
DISTANCE_FEATURE_COLS = ["dist_subway_m", "dist_bus_m"]
FEATURE_COLS_V4_DISTANCE = [*FEATURE_COLS, *DISTANCE_FEATURE_COLS]
MODEL_FEATURE_COLS_V4_DISTANCE = [*FEATURE_COLS_V4_DISTANCE, "station_code"]

FEATURE_SETS = {
    "v3": MODEL_FEATURE_COLS,
    "v4_kbo_lag": MODEL_FEATURE_COLS_V4,
    "v4_weather": MODEL_FEATURE_COLS_V4_WEATHER,
    "v4_distance": MODEL_FEATURE_COLS_V4_DISTANCE,
}

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


def make_xy(
    df: pd.DataFrame, feature_cols: list[str] = MODEL_FEATURE_COLS
) -> tuple[pd.DataFrame, pd.Series]:
    """`.fillna(0)`이 lag1d_stock/lag7d_stock 결측(D-1/D-7 경계 밖)에도 그대로 적용된다 —
    별도 fallback 값을 채우지 않고 0 + `_available=0` 플래그 조합으로 "정보 없음"을
    표현한다(원칙 8: 표본 없는 곳에 그럴듯한 값을 채우지 않는다)."""
    return df[feature_cols].fillna(0), df[TARGET_COL].fillna(0)


def attach_anchor_time_slot(df: pd.DataFrame) -> pd.DataFrame:
    """anchor(hour·minute) 기준 30분 time_slot(0~47) — D-1/D-7 lag 조인 키로 쓴다.

    v3/v4 데이터셋의 hour·minute·date는 base_time(anchor) 그대로다(target이 아님,
    `train.py`의 `_attach_holiday_flag`도 같은 전제) — 그래서 날짜축 멀티소스 모델의
    `compute_target_time_features`와 달리 target 시각을 다시 계산할 필요가 없다.
    """
    df = df.copy()
    df["time_slot"] = df["hour"] * 2 + (df["minute"] >= 30).astype("int8")
    return df


def attach_distance(df: pd.DataFrame, distance: pd.DataFrame) -> pd.DataFrame:
    """역 정적 거리 피처(`DISTANCE_FEATURE_COLS`)를 `od_station_id` 기준으로 붙인다.

    시간축이 없는 station 단위 정적 피처라 단순 left join이면 된다. `distance`에
    없는 역(좌표 매칭 실패 등)은 NaN으로 남고, `make_xy()`의 `fillna(0)`이 처리한다.
    """
    return df.merge(distance, on="od_station_id", how="left")


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


# ═══════════════════════════════════════════════════════════════════════════
# B4-2: 날짜축 멀티소스 모델(anchor 없음) — 위 v3(anchor+horizon)와 별개 축.
# `validation/BYC/lightgbm-stock-conversion-check/RESULTS.md`에서 검증 완료
# (exp_bikes -11.6%, p_full -12.4%, p_empty -1.8%, 전부 avg를 넘김).
# ═══════════════════════════════════════════════════════════════════════════

MULTISOURCE_TARGET_COL = "target_stock"

MULTISOURCE_FEATURE_COLS = [
    "target_hour",
    "target_minute",
    "target_dow",
    "target_is_weekend",
    "target_month",
    "target_sin_hour",
    "target_cos_hour",
    "is_holiday",
    "is_rain",
    "temp",
    "is_kbo_game_jamsil",
    "hist_mean",
    "hist_std",
    "station_code",
    "lag1d_stock",
    "lag1d_stock_available",
    "lag7d_stock",
    "lag7d_stock_available",
]


def add_future_stock_labels(df: pd.DataFrame) -> pd.DataFrame:
    """`stock_anchor_hour + target_net_flow`로 미래 절대 재고 라벨을 만든다(anchor 없는
    모델의 학습 타깃). 여러 스크립트에 계산이 흩어지지 않게 여기 한 곳에 고정한다."""
    df = df.copy()
    df["target_stock"] = df["stock_anchor_hour"] + df["target_net_flow"]
    df["target_stock_ratio"] = df["target_stock"] / df["rack_count"].replace(0, np.nan)
    df["is_empty_future"] = df["target_stock"] <= 0
    df["is_full_future"] = df["target_stock"] >= df["rack_count"]
    return df


def compute_target_time_features(df: pd.DataFrame, holidays: pd.DataFrame) -> pd.DataFrame:
    """`base_time + horizon_min`(=target_datetime) 기준으로 시간 피처를 계산한다.

    anchor(base_time) 기준 hour를 그대로 쓰면 최대 30분 어긋난다(horizon_min=30 고정
    사용 전제) — 이 모델이 예측하는 대상은 "미래 시점 자체"라 그 시점의 요일·시간이어야
    맞다. `dow_type`도 서빙 중인 avg와 완전히 같은 규칙(`calendar.attach_dow_type`)을
    재사용해야 공정 비교/재사용이 된다.
    """
    df = df.copy()
    df["base_time"] = pd.to_datetime(df["base_time"])
    target_dt = df["base_time"] + pd.Timedelta(minutes=30)
    df["target_hour"] = target_dt.dt.hour
    df["target_minute"] = target_dt.dt.minute
    df["target_dow"] = target_dt.dt.dayofweek
    df["target_is_weekend"] = (df["target_dow"] >= 5).astype("int8")
    df["target_month"] = target_dt.dt.month
    df["target_sin_hour"] = np.sin(2 * np.pi * df["target_hour"] / 24)
    df["target_cos_hour"] = np.cos(2 * np.pi * df["target_hour"] / 24)
    df["date"] = target_dt.dt.normalize()
    df = attach_dow_type(df, holidays)
    df["time_slot"] = df["target_hour"] * 2 + (df["target_minute"] >= 30).astype(int)
    return df


def fit_station_dow_time_slot_profile(train_df: pd.DataFrame) -> pd.DataFrame:
    """B4-2 모델용 historical profile — **avg baseline과 완전히 같은 그룹핑**
    (station×dow_type×time_slot). 요일을 안 묶고 계산하면 avg보다 노이즈가 커져서
    모델 성능이 avg를 못 넘는다(원인 진단, RESULTS.md) — 반드시 이 그룹핑을 써야 한다."""
    return (
        train_df.groupby(["od_station_id", "dow_type", "time_slot"])[MULTISOURCE_TARGET_COL]
        .agg(hist_mean="mean", hist_std="std")
        .reset_index()
    )


def attach_multisource_profile(
    df: pd.DataFrame, profile: pd.DataFrame, global_mean: float
) -> pd.DataFrame:
    merged = df.merge(profile, on=["od_station_id", "dow_type", "time_slot"], how="left")
    merged["hist_mean"] = merged["hist_mean"].fillna(global_mean)
    merged["hist_std"] = merged["hist_std"].fillna(0.0)
    return merged


def fill_lag_fallback(df: pd.DataFrame) -> pd.DataFrame:
    """lag1d_stock/lag7d_stock 결측(데이터 경계)을 hist_mean으로 채운다 — CROWD의
    "이력이 전혀 없으면 lookup으로 대체"와 동일 관례. `{col}_available` 플래그는
    그대로 둬서 모델이 실측인지 대체값인지 구분하게 한다."""
    for col in ("lag1d_stock", "lag7d_stock"):
        df[col] = df[col].fillna(df["hist_mean"])
    return df
