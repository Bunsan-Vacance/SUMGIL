"""승하차 패널(1시간)을 30분 추정치로 분해해 저장한다 — 135번 1층 산출물.

    data/CROWD/processed/crowd_panel_2024_2025.parquet (1시간, 20슬롯)
      → app.CROWD.pipeline.disaggregate.split_hourly_to_30min (88 배율표의 전반/후반 비중)
      → data/CROWD/processed/crowd_ridership_30min_est_2024_2025.parquet (30분, 39슬롯)

컬럼 `boarding_30min_est`·`alighting_30min_est`의 `_est`는 **분해 추정치**라는 표시다(원칙 4).
1시간 원본은 `boarding`·`alighting`으로 같은 행에 남겨 두 30분 합이 원본과 같은지 누구나 확인할 수
있게 한다. 배율표가 없는 (역, 요일유형, 시간)은 비중이 없어 NaN이다 — 채우지 않는다(원칙 8).
9호선은 승하차 패널 기간(2025~2026)이 달라 여기서는 다루지 않는다.

가정: "재차인원의 전반/후반 모양 = 승하차의 전반/후반 모양". 검증은
`validation/CROWD/time-resolution-check/holdout_shares.py`.

실행:
    cd AI
    python -m DATA_ENGINE.eda.build_ridership_30min
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from app.CROWD.pipeline.disaggregate import split_hourly_to_30min
from app.CROWD.pipeline.lookup import TARGETS

AI_ROOT = Path(__file__).resolve().parents[2]
CROWD_PROCESSED = AI_ROOT / "data" / "CROWD" / "processed"
PANEL_NAME = "crowd_panel_2024_2025.parquet"
CALIBRATION_NAME = "crowd_congestion_calibration.parquet"
OUTPUT_NAME = "crowd_ridership_30min_est_2024_2025.parquet"

KEEP = ["date", "station_no", "station_name", "line", "day_type", "time_slot", *TARGETS]


def build() -> tuple[pd.DataFrame, dict]:
    panel = pd.read_parquet(CROWD_PROCESSED / PANEL_NAME, columns=KEEP)
    cal = pd.read_parquet(CROWD_PROCESSED / CALIBRATION_NAME)
    out = split_hourly_to_30min(panel, cal)

    # 질량 보존 — 비중이 있는 (행)에서 두 30분 합 == 1시간 원본
    have = out.dropna(subset=["share"])
    summed = have.groupby(["date", "station_no", "time_slot"], observed=True)[
        "boarding_30min_est"
    ].sum()
    orig = have.groupby(["date", "station_no", "time_slot"], observed=True)["boarding"].first()
    max_gap = float((summed - orig).abs().max()) if len(summed) else 0.0
    stats = {
        "rows_1h": len(panel),
        "rows_30min": len(out),
        "no_share_rows": int(out["share"].isna().sum()),
        "no_share_groups": int(
            out[out["share"].isna()][["station_no", "day_type", "time_slot"]]
            .drop_duplicates()
            .shape[0]
        ),
        "mass_max_abs_gap": max_gap,
    }
    return out, stats


def main() -> None:
    out, stats = build()
    path = CROWD_PROCESSED / OUTPUT_NAME
    out.to_parquet(path, index=False)
    print(f"1시간 {stats['rows_1h']:,}행 → 30분 {stats['rows_30min']:,}행")
    print(
        f"비중 없음: {stats['no_share_rows']:,}행 / (역·요일유형·시간) {stats['no_share_groups']:,}조합 — NaN으로 둠"
    )
    print(f"질량 보존 최대 오차: {stats['mass_max_abs_gap']:.2e}")
    print(f"저장: {path}")


if __name__ == "__main__":
    main()
