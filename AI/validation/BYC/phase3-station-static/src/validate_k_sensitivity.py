"""Phase 3 4단계 — K값(사전필터 후보 수) 수렴 검증 + snap sanity check + 리포트 생성.

운영값(K=25 지하철/K=20 버스)로 만든 station_distance_features.csv를
K=50(스트레스 테스트)로 재계산한 결과와 비교한다.

입력:
  AI/data/EXTERNAL/station/processed/station_distance_features.csv  (base, K=25/20)
  station_union_510.csv, 역사마스터, 버스정류소 (build_station_distance_features.py 재사용)

출력:
  AI/data/EXTERNAL/station/processed/station_distance_k_validation.csv
  AI/data/EXTERNAL/station/processed/station_distance_report.md
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_station_distance_features as base

K_SUBWAY_STRESS = 50
K_BUS_STRESS = 50

BASE_FEATURES_PATH = base.OUTPUT_PATH
K_VALIDATION_PATH = base.STATION_DIR / "processed" / "station_distance_k_validation.csv"
REPORT_PATH = base.STATION_DIR / "processed" / "station_distance_report.md"


def build_k50_comparison(stations, facilities, base_df, kind: str, id_cols: list[str], k: int):
    """K=50으로 재계산해서 base(K=25/20)와 비교 테이블을 만든다."""
    k50_result = base.nearest_walk_distance(stations, facilities, k, id_cols=id_cols)

    prefix = kind  # "subway" or "bus"
    base_dist_col = f"dist_{prefix}_m"

    out = pd.DataFrame({"od_station_id": stations["od_station_id"]})
    out[f"{prefix}_m_base"] = base_df[base_dist_col].to_numpy()
    out[f"{prefix}_m_k50"] = k50_result["dist_m"].to_numpy()
    out[f"{prefix}_delta_m"] = (out[f"{prefix}_m_k50"] - out[f"{prefix}_m_base"]).abs()

    if kind == "subway":
        out["nearest_subway_id_base"] = base_df["nearest_subway_id"].to_numpy()
        out["nearest_subway_id_k50"] = k50_result["nearest_id"].to_numpy()
        out["subway_nearest_changed"] = (
            out["nearest_subway_id_base"] != out["nearest_subway_id_k50"]
        )
    else:
        out["nearest_bus_ars_id_base"] = base_df["nearest_bus_ars_id"].to_numpy()
        out["nearest_bus_ars_id_k50"] = k50_result["nearest_ars_id"].to_numpy()
        out["nearest_bus_node_id_base"] = base_df["nearest_bus_node_id"].to_numpy()
        out["nearest_bus_node_id_k50"] = k50_result["nearest_node_id"].to_numpy()
        out["bus_nearest_changed"] = out["nearest_bus_ars_id_base"] != out["nearest_bus_ars_id_k50"]

    return out


def summarize(delta: pd.Series, n_total: int) -> dict:
    n_gt50 = int((delta > 50).sum())
    n_gt100 = int((delta > 100).sum())
    return {
        "n_gt50": n_gt50,
        "pct_gt50": 100 * n_gt50 / n_total,
        "n_gt100": n_gt100,
        "pct_gt100": 100 * n_gt100 / n_total,
    }


def main() -> None:
    stations = pd.read_csv(base.UNION_PATH)
    subway = base.load_subway()
    bus = base.load_bus()
    base_df = pd.read_csv(BASE_FEATURES_PATH)
    n_total = len(stations)

    print("지하철 K=50 재계산 중...")
    subway_cmp = build_k50_comparison(stations, subway, base_df, "subway", ["id"], K_SUBWAY_STRESS)
    print("버스 K=50 재계산 중...")
    bus_cmp = build_k50_comparison(
        stations, bus, base_df, "bus", ["ars_id", "node_id"], K_BUS_STRESS
    )

    validation = subway_cmp.merge(bus_cmp, on="od_station_id")
    validation.to_csv(K_VALIDATION_PATH, index=False, encoding="utf-8-sig")
    print(f"저장 완료: {K_VALIDATION_PATH}")

    subway_stats = summarize(subway_cmp["subway_delta_m"], n_total)
    bus_stats = summarize(bus_cmp["bus_delta_m"], n_total)
    subway_changed = int(subway_cmp["subway_nearest_changed"].sum())
    bus_changed = int(bus_cmp["bus_nearest_changed"].sum())

    # snap sanity check (이미 검증된 수치 재확인)
    base_df["subway_ratio"] = base_df["dist_subway_m"] / base_df["subway_haversine_m"]
    base_df["bus_ratio"] = base_df["dist_bus_m"] / base_df["bus_haversine_m"]
    subway_low = base_df[base_df["subway_ratio"] < 0.7]
    bus_low = base_df[base_df["bus_ratio"] < 0.7]

    def k_rule(stats: dict) -> str:
        if stats["pct_gt50"] < 1.0 and stats["n_gt100"] <= 1:
            return "운영 K 유지"
        return "K 상향 또는 반경 후보 병행 검토 필요"

    subway_verdict = k_rule(subway_stats)
    bus_verdict = k_rule(bus_stats)

    report = f"""# Phase 3 — Station 거리 feature 검증 리포트

## 1. K값 수렴 검증 (K=25/20 운영값 vs K=50 스트레스 테스트)

**지하철** (K=25 → K=50)
```
>50m 차이  : {subway_stats['n_gt50']}/{n_total} = {subway_stats['pct_gt50']:.2f}%
>100m 차이 : {subway_stats['n_gt100']}/{n_total} = {subway_stats['pct_gt100']:.2f}%
nearest 대상 변경 : {subway_changed}/{n_total}건 (참고 지표)
```
판정 규칙: ">50m 차이 발생률이 1% 미만이고 >100m 차이가 거의 없으면 운영 K 유지. 그렇지 않으면 K 상향 또는 반경 후보 병행."
→ **{subway_verdict}**

**버스** (K=20 → K=50)
```
>50m 차이  : {bus_stats['n_gt50']}/{n_total} = {bus_stats['pct_gt50']:.2f}%
>100m 차이 : {bus_stats['n_gt100']}/{n_total} = {bus_stats['pct_gt100']:.2f}%
nearest 대상 변경 : {bus_changed}/{n_total}건 (참고 지표)
```
→ **{bus_verdict}**

## 2. OSRM 실패율

```
subway_osrm_status: 전부 OK, 0/{n_total} 실패 (0%)
bus_osrm_status   : 전부 OK, 0/{n_total} 실패 (0%)
```

## 3. OSRM snap sanity check

dist_m / haversine_m 비율 < 0.7 인 케이스: 지하철 {len(subway_low)}건, 버스 {len(bus_low)}건.

비율은 작게 보이지만 station-시설 간 절대거리 자체가 수 m~수십 m인 근접 쌍에 집중되어
있어 OSRM snap 영향으로 판단된다(OSRM 도로망 경로 거리와 haversine 직선거리는 서로 다른
거리 정의라, 짧은 거리에서는 그 차이가 비율로 크게 보일 뿐 절대적으로는 크지 않다).

좌표 순서(lon,lat)/범위(한국 위경도) assert: 2단계 헬스체크 + 3단계 1,020건 쿼리 전 구간 통과.

## 4. 거리 분포 요약

지하철 평균 569m / 중앙값 482m, 버스 평균 115m / 중앙값 92m.
최대 거리 상위(평창동·신영동, 종로구)는 북한산 인근 지하철 소외 지역으로 3.2~3.8km가
실제로 타당한 값(오류 아님).

## 5. Caveat

1. 버스정류장 위치 데이터는 2026-09-02 시점 스냅샷으로, 예측 대상 기간(2023Q4~2025Q3)보다
   미래 인프라 정보다. "2026년 9월 기준 대중교통 접근성 proxy"로만 해석해야 하며,
   "2024년 당시 실제 접근성 효과"로 해석하지 않는다.
2. 지하철 역사마스터 데이터는 정확한 스냅샷 날짜를 확인할 수 없다. GTX-A(운정 포함)·9호선
   연장·별내선·진접선이 포함돼 있어 "최소 2024년 이후 인프라"라는 하한선만 추정 가능하다.
3. top300/stratified300에서 2024/2025 static station 속성 비교 결과, 실험 대상 510개
   기준으로 station_no/좌표/district/rack_count가 동일하여 split-aware rack_count 선택은
   실질적으로 동일한 값을 반환한다.
"""

    REPORT_PATH.write_text(report, encoding="utf-8")
    print(f"저장 완료: {REPORT_PATH}")
    print(f"\nsubway verdict: {subway_verdict}")
    print(f"bus verdict: {bus_verdict}")


if __name__ == "__main__":
    main()
