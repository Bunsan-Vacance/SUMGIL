"""잔차(실측 − 베이스라인)가 어디에 몰려 있는지 진단한다.

`run_baseline.py`가 남은 여지(3.7~4.0%)와 기상·이벤트 상관을 봤다면, 이 스크립트는 그
여지가 **고르게 퍼져 있는지 특정 구간에 몰려 있는지**를 본다. 몰려 있으면 그 구간이
다음 모델링(피처 추가·LightGBM 등)의 승부처고, 고르면 이벤트 외에 더 파고들 이유가 적다.

시간대·요일유형·월(계절)·역별로 나눠 RMSE와 "전체 제곱오차 대비 비중"을 함께 낸다 —
행 수가 다른 구간끼리는 RMSE만 비교하면 표본이 적은 쪽이 과대/과소평가되니, 비중도 같이
봐야 진짜 몰려 있는지 판단할 수 있다.

실행:
    cd AI
    python validation/CROWD/baseline-check/diagnose_residuals.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from baseline import DayTypeLookupBaseline, residuals
from dataset import load_panel, time_split

TOP_N_STATIONS = 15


def _segment_breakdown(resid: pd.DataFrame, target: str, group_col: str) -> pd.DataFrame:
    """구간별 RMSE와 전체 제곱오차 대비 비중.

    비중 합은 항상 100%다 — "몰려 있다"는 건 소수 구간이 이 비중을 불균형하게 가져간다는
    뜻이라, 행 비중과 나란히 놓고 봐야 표본 크기 효과와 구분된다.
    """
    col = f"{target}_resid"
    frame = resid[[group_col, col]].dropna()
    sq = frame[col] ** 2
    total_sq = float(sq.sum())

    grouped = frame.assign(sq=sq).groupby(group_col, observed=True)
    out = grouped["sq"].agg(n="count", 제곱오차합="sum").reset_index()
    out["rmse"] = (out["제곱오차합"] / out["n"]) ** 0.5
    out["행_비중_%"] = out["n"] / len(frame) * 100
    out["오차_비중_%"] = out["제곱오차합"] / total_sq * 100 if total_sq else float("nan")
    out["쏠림"] = out["오차_비중_%"] - out["행_비중_%"]
    return out.drop(columns="제곱오차합").sort_values("쏠림", ascending=False)


def station_breakdown(
    resid: pd.DataFrame, panel: pd.DataFrame, target: str, top_n: int = TOP_N_STATIONS
) -> pd.DataFrame:
    """역별 쏠림 상위 N개. 역명·이벤트 연결 여부를 같이 붙여 원인을 바로 읽게 한다."""
    out = _segment_breakdown(resid, target, "station_no")
    names = panel[["station_no", "station_name"]].drop_duplicates("station_no")
    out = out.merge(names, on="station_no", how="left")
    return out.sort_values("쏠림", ascending=False).head(top_n)


def main() -> None:
    panel = load_panel(with_events=True)
    train, test = time_split(panel)
    model = DayTypeLookupBaseline().fit(train)
    resid = residuals(model, test)
    resid["month"] = resid["date"].dt.month

    for target in model.targets:
        print(f"\n{'=' * 60}\n[{target}] 잔차 쏠림 진단\n{'=' * 60}")

        print("\n[시간대별]")
        print(_segment_breakdown(resid, target, "time_slot").round(2).to_string(index=False))

        print("\n[요일유형별]")
        print(_segment_breakdown(resid, target, "day_type").round(2).to_string(index=False))

        print("\n[월별]")
        print(_segment_breakdown(resid, target, "month").round(2).to_string(index=False))

        print(f"\n[역별 쏠림 상위 {TOP_N_STATIONS}]")
        print(station_breakdown(resid, panel, target).round(2).to_string(index=False))


if __name__ == "__main__":
    main()
