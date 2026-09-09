"""베이스라인 검증용 데이터셋 준비.

`crowd_panel_2024_2025.parquet`을 학습/평가로 나눈다. **시간 기준으로 자른다** — 무작위
분할을 쓰면 같은 날의 다른 시간대가 학습과 평가에 나눠 들어가 누수가 생기고, 실제 운영
(과거로 미래를 예측)과도 다른 상황을 평가하게 된다.

기본 분할은 2024년 학습 / 2025년 평가다. 논문(「기상 요소와 주기성 및 특이성을 고려한
지하철 혼잡도 예측 모델」)이 학습 기간을 늘리는 것보다 예측 시점과 가까운 최신 1개년만
쓰는 쪽이 더 좋았다고 보고했는데(RMSE 10.743→4.265), 우리 구간이 2년뿐이라 그 비교를
그대로는 못 한다. 대신 1년 학습 / 1년 평가로 두어 최신성 가설을 나중에 확인할 여지를 남긴다.

**예측 대상은 승하차 인원이다.** 혼잡도가 아니다 — 날짜별 실측 혼잡도가 존재하지 않아
혼잡도로는 정직한 성능 측정이 불가능하기 때문이다. 혼잡도는 예측된 승하차를 재귀식으로
변환해 얻는 파생값이라, 승하차 예측이 정확하면 혼잡도도 따라 정확해진다.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

AI_ROOT = Path(__file__).resolve().parents[3]
CROWD_PROCESSED = AI_ROOT / "data" / "CROWD" / "processed"

PANEL_NAME = "crowd_panel_2024_2025.parquet"
EVENTS_NAME = "crowd_station_events_2024_2025.parquet"

# 시간 분할 경계 — 이 날짜 이전이 학습, 이후가 평가.
SPLIT_DATE = pd.Timestamp("2025-01-01")

# 예측 대상. 승차·하차를 따로 예측한다.
TARGETS = ["boarding", "alighting"]

# 베이스라인이 조회 키로 쓰는 컬럼. "요일유형 × 역 × 시간대 평균"이 곧 베이스라인이다.
BASELINE_KEYS = ["day_type", "station_no", "time_slot"]


def load_panel(with_events: bool = False) -> pd.DataFrame:
    """패널을 읽고, 필요하면 이벤트 컬럼까지 붙인다."""
    panel = pd.read_parquet(CROWD_PROCESSED / PANEL_NAME)
    panel = panel.dropna(subset=TARGETS)

    if with_events:
        events = pd.read_parquet(CROWD_PROCESSED / EVENTS_NAME)
        panel = panel.merge(events, on=["date", "station_no"], how="left")
        for col in ("game_count", "festival_count"):
            panel[col] = panel[col].fillna(0).astype(int)
        # 관중수는 채우지 않는다 — 경기가 없는 날과 관중수만 모르는 날을 구분해야 한다.

    return panel


def time_split(
    panel: pd.DataFrame, split_date: pd.Timestamp = SPLIT_DATE
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """학습(경계 이전)과 평가(경계 이후)로 나눈다."""
    train = panel[panel["date"] < split_date].reset_index(drop=True)
    test = panel[panel["date"] >= split_date].reset_index(drop=True)
    return train, test
