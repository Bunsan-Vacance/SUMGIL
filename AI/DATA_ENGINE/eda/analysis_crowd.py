"""CROWD 혼잡도 스냅샷 정적 프로파일 분석 — 순수 함수, I/O 없음.

입력은 `parsers_crowd.build_congestion_long()`의 결과(tidy long-format)를 기대한다:
    columns: source, line, station_no, station_name, direction, day_type,
             time_slot, congestion_pct, year, train_type
(station_no/train_type/year는 원천에 따라 일부만 채워지고 나머지는 NaN — 정상이며 채우지 않는다)

주의: 두 원천(seoul_1_8, line9)은 day_type/direction 값 체계가 다르다
(seoul_1_8: 평일/토요일/일요일, 상선/하선/내선/외선; line9: 평일/휴일, 상선/하선).
이 차이를 억지로 통일하지 않는다 — `day_type_direction_coverage`로 그대로 드러낸다.
"""

from __future__ import annotations

import pandas as pd
from sklearn.cluster import KMeans

_PIVOT_INDEX = ["source", "line", "station_name", "direction", "day_type", "year", "train_type"]


def station_time_pivot(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """역×시간대 혼잡도 피벗과, 동일 셀에 값이 몇 개 겹쳤는지 세는 count 피벗을 함께 반환.

    count가 1보다 큰 셀은 원본에 중복 행이 있다는 신호이므로 평균으로 조용히 뭉개지 않고
    호출부에서 따로 점검할 수 있게 한다.
    """
    pivot = df.pivot_table(
        index=_PIVOT_INDEX, columns="time_slot", values="congestion_pct", aggfunc="mean"
    )
    counts = df.pivot_table(
        index=_PIVOT_INDEX, columns="time_slot", values="congestion_pct", aggfunc="count"
    )
    return pivot, counts


def missing_cell_inventory(pivot: pd.DataFrame) -> pd.DataFrame:
    """pivot에서 결측(NaN) 셀만 (index..., time_slot) 형태로 나열한다. 채우지 않는다."""
    missing_mask = pivot.isna()
    stacked = missing_mask.stack()
    missing_only = stacked[stacked]
    return missing_only.index.to_frame(index=False)


def outlier_flags(
    df: pd.DataFrame, zero_threshold: float = 0.0, high_threshold: float = 150.0
) -> pd.DataFrame:
    """0% 이하, 100% 초과, high_threshold 초과 값을 flag_reason과 함께 반환. 삭제·보정하지 않는다."""
    zero_mask = df["congestion_pct"] <= zero_threshold
    over_100_mask = (df["congestion_pct"] > 100) & (df["congestion_pct"] <= high_threshold)
    very_high_mask = df["congestion_pct"] > high_threshold

    flags = []
    for mask, reason in [
        (zero_mask, "zero"),
        (over_100_mask, "over_100"),
        (very_high_mask, "very_high"),
    ]:
        flagged = df[mask].copy()
        flagged["flag_reason"] = reason
        flags.append(flagged)

    return pd.concat(flags, ignore_index=True)


def day_type_direction_coverage(df: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """(source, line) x day_type, (source, line) x direction 크로스탭을 각각 반환.

    seoul_1_8(평일/토요일/일요일, 2호선만 내선/외선 나머지 상선/하선)와 line9(평일/휴일,
    상선/하선만)의 체계 차이를 그대로 드러낸다 — 하나로 합치거나 재라벨링하지 않는다.
    """
    day_type_ct = pd.crosstab([df["source"], df["line"]], df["day_type"])
    direction_ct = pd.crosstab([df["source"], df["line"]], df["direction"])
    return {"day_type": day_type_ct, "direction": direction_ct}


def year_over_year_snapshot_reference(df_line9: pd.DataFrame) -> pd.DataFrame:
    """9호선 연도별 스냅샷의 전년 대비 변화율(pct_change)을 역×요일유형×시간대 단위로 계산.

    주의: 연 1회 대표주간 관측치이므로 일 단위 시계열이 아니고 통계적 유의성을 주장할 수
    없다 — 추세 참고용으로만 쓴다("추정 데이터는 절대값이 아니라 변화율로 쓴다" 원칙 적용).

    이전 연도 값이 0%(무혼잡)였던 셀은 변화율이 무한대(inf)로 계산되는데, 이는 실제 변화
    크기를 나타내지 못하는 계산상 허상이라 NaN으로 남긴다(원칙 1: 근거 없는 값을 채우지
    않는다의 연장 — inf도 유효한 변화율이 아니므로 같은 취급).
    """
    pivot = df_line9.pivot_table(
        index=["station_name", "day_type", "direction", "train_type", "time_slot"],
        columns="year",
        values="congestion_pct",
        aggfunc="mean",
    )
    pivot = pivot.reindex(sorted(pivot.columns), axis=1)
    pct_change = pivot.pct_change(axis=1)
    return pct_change.replace([float("inf"), float("-inf")], pd.NA)


def cluster_station_profiles(
    profile_wide: pd.DataFrame, n_clusters: int = 3, random_state: int = 42
) -> pd.Series:
    """역×시간대 혼잡도 프로파일을 시간대 축으로 K-means 군집화.

    입력은 역(행) × time_slot(열) 형태의 wide pivot(예: 특정 line/day_type/direction/
    train_type 조합의 `station_time_pivot` 슬라이스)을 기대한다.

    행 단위 z-score 표준화 후 유클리드 거리로 K-means를 적용한다 — 절대 혼잡도 수준이 아니라
    "하루 중 언제 피크가 오는가"라는 패턴의 모양만 남기기 위해서다. 이는 [장려상] 지하철
    혼잡도 상관분석 논문의 "Correlation similarity 기반 K-means 클러스터링"(오후 혼잡 집중형
    /좌측 피크 쌍봉형/우측 피크 쌍봉형 3군집)을 근사하는 표준 기법이다 — 행을 표준화하면
    유클리드 거리 순위가 피어슨 상관 기반 순위와 일치한다.

    결측이 있는 역은 표준화가 왜곡되므로 제외한다(채우지 않는다 원칙의 연장) — 표본 부족
    역은 군집 배정 없이 데이터 부족으로 남는다.
    """
    complete = profile_wide.dropna()
    if len(complete) < n_clusters:
        raise ValueError(
            f"결측 없는 역이 {len(complete)}개뿐이라 n_clusters={n_clusters}로 군집화할 수 없습니다."
        )
    row_mean = complete.mean(axis=1)
    row_std = complete.std(axis=1)
    constant_rows = row_std == 0
    standardized = (
        complete.loc[~constant_rows]
        .sub(row_mean[~constant_rows], axis=0)
        .div(row_std[~constant_rows], axis=0)
    )

    model = KMeans(n_clusters=n_clusters, random_state=random_state, n_init=10)
    labels = model.fit_predict(standardized.to_numpy())
    return pd.Series(labels, index=standardized.index, name="cluster")
