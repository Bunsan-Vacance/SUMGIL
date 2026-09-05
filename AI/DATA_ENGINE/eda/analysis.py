"""따릉이 재고·날씨 영향 EDA 분석 함수 모음.

데이터가 아직 없는 상태에서 만든 스캐폴딩이라, 각 함수는 입력 스키마를 docstring에
명시해두고 실제 실행은 데이터 수집 이후로 미룬다 (report.py 에서 orchestration).

공통 기대 스키마:
  snapshots (재고 스냅샷, 실시간 폴러 산출물 누적):
    stationId, stationName, rackTotCnt, parkingBikeTotCnt, shared,
    stationLatitude, stationLongitude, collected_at(tz-aware)

  rental_hourly (대여이력을 시간당 집계):
    dt_hour(datetime, naive KST), rent_count

  weather_hourly (ASOS/초단기 병합, 시간당):
    dt_hour(datetime, naive KST), precip_mm, temp_c
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy import stats

PRECIP_BINS = [-0.01, 0, 1, 5, 10, np.inf]
PRECIP_LABELS = ["0", "0-1", "1-5", "5-10", "10+"]
DEPLETION_THRESHOLD = 2  # N <= 2 를 "고갈"로 정의


# ── 1. 재고 분포 ──────────────────────────────────────────────


def inventory_distribution(snapshots: pd.DataFrame) -> dict:
    """잔여대수·점유율 분포 + 시간대별 P(N=0), P(N<=2)."""
    df = snapshots.copy()
    df["occupancy"] = df["parkingBikeTotCnt"] / df["rackTotCnt"].replace(0, np.nan)
    df["hour"] = pd.to_datetime(df["collected_at"]).dt.hour

    by_hour = df.groupby("hour")["parkingBikeTotCnt"].agg(
        p_zero=lambda s: (s == 0).mean(),
        p_depleted=lambda s: (s <= DEPLETION_THRESHOLD).mean(),
    )

    return {
        "count_desc": df["parkingBikeTotCnt"].describe(),
        "occupancy_desc": df["occupancy"].describe(),
        "by_hour": by_hour,
    }


# ── 2. 요일×시간대 히트맵 ─────────────────────────────────────


def weekday_hour_heatmap(
    snapshots: pd.DataFrame, value_col: str = "parkingBikeTotCnt"
) -> pd.DataFrame:
    df = snapshots.copy()
    ts = pd.to_datetime(df["collected_at"])
    df["dow"] = ts.dt.dayofweek  # 0=월
    df["hour"] = ts.dt.hour
    return df.pivot_table(index="dow", columns="hour", values=value_col, aggfunc="mean")


# ── 3. 날씨 영향 ──────────────────────────────────────────────


@dataclass
class WeatherImpactResult:
    precip_bin_summary: pd.DataFrame
    precip_kruskal_pvalue: float
    temp_bin_summary: pd.DataFrame
    depletion_rate_by_rain: pd.Series
    depletion_chi2_pvalue: float
    raw_corr: float
    residual_corr: float


def _merge_hourly(rental_hourly: pd.DataFrame, weather_hourly: pd.DataFrame) -> pd.DataFrame:
    return rental_hourly.merge(weather_hourly, on="dt_hour", how="inner")


def weather_impact(
    rental_hourly: pd.DataFrame,
    weather_hourly: pd.DataFrame,
    depletion_by_hour: pd.DataFrame | None = None,
) -> WeatherImpactResult:
    """강수/기온 구간별 대여량 비교, 고갈률 차이, 원계열/잔차 상관.

    depletion_by_hour: dt_hour, is_depleted(bool) — 있으면 강수 유무별 고갈률까지 계산.
    """
    merged = _merge_hourly(rental_hourly, weather_hourly)
    merged["precip_bin"] = pd.cut(merged["precip_mm"], bins=PRECIP_BINS, labels=PRECIP_LABELS)

    # 3-1. 강수량 구간별 대여건수 + Kruskal-Wallis (정규성 가정 없이 그룹 간 분포 차이 검정)
    precip_summary = merged.groupby("precip_bin", observed=True)["rent_count"].agg(
        ["mean", "median", "count"]
    )
    groups = [
        g["rent_count"].values for _, g in merged.groupby("precip_bin", observed=True) if len(g) > 0
    ]
    kruskal_p = stats.kruskal(*groups).pvalue if len(groups) >= 2 else float("nan")

    # 3-2. 기온 구간 (U자 형태 확인 — 10구간 분위수)
    merged["temp_bin"] = pd.qcut(merged["temp_c"], q=10, duplicates="drop")
    temp_summary = (
        merged.groupby("temp_bin", observed=True)["rent_count"].mean().to_frame("mean_rent_count")
    )

    # 3-3. 강수 유무에 따른 고갈률 차이 (카이제곱)
    depletion_rate_by_rain = pd.Series(dtype=float)
    chi2_p = float("nan")
    if depletion_by_hour is not None:
        dep = depletion_by_hour.merge(weather_hourly, on="dt_hour", how="inner")
        dep["is_rain"] = dep["precip_mm"] > 0
        depletion_rate_by_rain = dep.groupby("is_rain")["is_depleted"].mean()
        contingency = pd.crosstab(dep["is_rain"], dep["is_depleted"])
        if contingency.shape == (2, 2):
            chi2_p = stats.chi2_contingency(contingency)[1]

    # 3-4. 원계열 상관 vs (요일,시간대) 그룹평균 제거한 잔차 상관 — 공통 계절성발 허위상관 배제
    ts = merged["dt_hour"]
    merged["dow"] = ts.dt.dayofweek
    merged["hour"] = ts.dt.hour
    raw_corr = merged["rent_count"].corr(merged["precip_mm"])

    group_mean = merged.groupby(["dow", "hour"])["rent_count"].transform("mean")
    merged["rent_resid"] = merged["rent_count"] - group_mean
    precip_group_mean = merged.groupby(["dow", "hour"])["precip_mm"].transform("mean")
    merged["precip_resid"] = merged["precip_mm"] - precip_group_mean
    residual_corr = merged["rent_resid"].corr(merged["precip_resid"])

    return WeatherImpactResult(
        precip_bin_summary=precip_summary,
        precip_kruskal_pvalue=kruskal_p,
        temp_bin_summary=temp_summary,
        depletion_rate_by_rain=depletion_rate_by_rain,
        depletion_chi2_pvalue=chi2_p,
        raw_corr=raw_corr,
        residual_corr=residual_corr,
    )


# ── 4. 공간 구조 ──────────────────────────────────────────────


def _haversine_m(lat1, lon1, lat2, lon2) -> np.ndarray:
    r = 6_371_000.0
    lat1, lon1, lat2, lon2 = map(np.radians, [lat1, lon1, lat2, lon2])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    a = np.sin(dlat / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2) ** 2
    return 2 * r * np.arcsin(np.sqrt(a))


def spatial_neighbor_correlation(
    snapshots: pd.DataFrame,
    radii_m: tuple[int, ...] = (300, 500),
) -> dict[int, float]:
    """대여소 간 거리별(반경 내 이웃) 재고 점유율 상관.

    snapshots를 station × collected_at 점유율 wide-table로 피벗한 뒤, 반경 내 이웃 쌍의
    시계열 상관계수 평균을 반경별로 계산한다. 대여소 수가 많으면 O(n^2) 거리 계산 비용에
    유의 — 필요시 격자(geohash/h3)로 사전 필터링할 것.
    """
    df = snapshots.copy()
    df["occupancy"] = df["parkingBikeTotCnt"] / df["rackTotCnt"].replace(0, np.nan)

    wide = df.pivot_table(index="collected_at", columns="stationId", values="occupancy")
    stations = df.drop_duplicates("stationId").set_index("stationId")[
        ["stationLatitude", "stationLongitude"]
    ]

    ids = stations.index.to_numpy()
    lat = stations["stationLatitude"].to_numpy(dtype=float)
    lon = stations["stationLongitude"].to_numpy(dtype=float)

    corr_matrix = wide.corr()

    results: dict[int, list[float]] = {r: [] for r in radii_m}
    for i in range(len(ids)):
        dists = _haversine_m(lat[i], lon[i], lat, lon)
        for r in radii_m:
            neighbor_idx = np.where((dists > 0) & (dists <= r))[0]
            for j in neighbor_idx:
                if ids[j] not in corr_matrix.columns or ids[i] not in corr_matrix.columns:
                    continue
                c = corr_matrix.loc[ids[i], ids[j]]
                if pd.notna(c):
                    results[r].append(c)

    return {r: float(np.mean(vals)) if vals else float("nan") for r, vals in results.items()}
