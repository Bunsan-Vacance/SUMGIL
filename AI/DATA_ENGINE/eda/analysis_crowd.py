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
