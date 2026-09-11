"""시간 해상도 분해 — 1시간 승하차 → 30분 → 열차 단위 추정치. 순수 함수(135번).

승하차 원천은 1시간 20슬롯, 혼잡도 스냅샷은 30분 39슬롯, 서비스가 원하는 단위는 열차 한 대다.
날짜별 30분 이하 실측은 어느 공개 원천에도 없으므로 **가정을 명시한 분해(temporal disaggregation)**로
파생 라벨을 만든다. 만들어 채우는 값이라 컬럼에 `_est` 접미를 붙이고(원칙 4), 근거가 없는 셀은
채우지 않는다(원칙 8).

## 1층 — 1시간 → 30분 (`split_hourly_to_30min`)

88 배율표의 같은 1시간 안 두 30분 배율은 분모(raw 1시간 평균)가 같으므로
`ratio_a : ratio_b = 실측_a : 실측_b`, 즉 **그 1시간 안에서 전반/후반 30분의 재차인원 비중**이다
(Notion "혼잡도 시간 해상도": 러시 시간대 표준편차 3.7~5.2%p로 역·방향 불문 안정). 이 비중을
승하차에도 적용한다 — **"재차인원 모양 = 승하차 모양"이 이 층의 가정**이다. 비중은 역·요일유형·
1시간 단위로 방향 평균을 쓴다(승하차는 방향이 없다). 배율표가 없는 (역, 요일유형, 시간)은 NaN.
`~06`은 30분 슬롯이 하나(05:30)라 비중 1, `24~`는 00:00·00:30 둘이다.

## 2층 — 30분 → 열차 (`allocate_to_trains`)

그 30분 슬롯에 그 역·방향을 지난 열차 목록(시각표)에 재차인원을 배분한다. 배차 간격이 짧을 때
승객은 시각표를 보지 않고 도착하므로(대중교통 대기시간 연구의 표준 가정 — 무작위 도착, 평균 대기 =
배차/2) **열차 i의 몫 = 직전 열차와의 간격 ÷ 슬롯 길이**다. 간격이 `long_headway_min`(기본 12분)을
넘는 열차는 `headway_long=True`로 표시한다 — 그 구간(심야·막차)에서는 시각표 의존 도착이 되어 균등
가정이 약해진다. 값은 그대로 두고 플래그만 남겨 소비자가 판단한다.

슬롯 첫 열차의 "직전 열차"는 슬롯 경계 이전 마지막 열차다(경계를 넘어 계산). 슬롯에 열차가 없으면
그 슬롯 재차인원은 배분할 곳이 없어 NaN으로 남긴다(운행 없음 = 혼잡도 정의 불가).

## 검증 가능성

- 1층: 두 30분 추정치의 합 = 1시간 원본(질량 보존). 요일유형 홀드아웃으로 모양 오차 측정.
- 2층: 열차 몫의 합 = 슬롯 재차인원(질량 보존). 외부 실측(열차별 혼잡도)이 없어 정확도는 미검증 —
  서울교통공사 칸별 실시간 혼잡도 개방 시 재판정(계획 파일 참고).
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import pandas as pd

from app.CROWD.pipeline.congestion import hour_bucket_to_30min_slots
from app.CROWD.pipeline.features import SLOT_ORDER
from app.CROWD.pipeline.lookup import TARGETS

SLOT_MINUTES = 30
LONG_HEADWAY_MIN = 12.0


# ── 1층 ──
def half_hour_shares(calibration: pd.DataFrame) -> pd.DataFrame:
    """배율표 → (station_no, day_type, time_slot[1시간], time_slot_30min) 별 전반/후반 비중.

    방향별 비중을 먼저 구한 뒤 방향 평균을 낸다. 한 30분만 있는 시간(`~06`)은 비중 1.
    반환 컬럼: station_no, day_type, time_slot, time_slot_30min, share.
    """
    cal = calibration.dropna(subset=["ratio"]).copy()
    # 배율표의 `time_slot`은 30분 슬롯('08:30')이다. 소속 1시간 버킷('08-09')을 따로 만든다.
    cal["time_slot_30min"] = cal["time_slot"].astype(str)
    cal["hour_bucket"] = cal["time_slot_30min"].map(_slot30_to_hour_bucket)
    key = ["station_no", "direction", "day_type", "hour_bucket"]
    total = cal.groupby(key, observed=True)["ratio"].transform("sum")
    cal["share_dir"] = np.where(total > 0, cal["ratio"] / total, np.nan)
    out = (
        cal.groupby(["station_no", "day_type", "hour_bucket", "time_slot_30min"], observed=True)[
            "share_dir"
        ]
        .mean()
        .rename("share")
        .reset_index()
        .rename(columns={"hour_bucket": "time_slot"})
    )
    # 방향 평균 뒤 합이 1에서 어긋날 수 있어 1시간 안에서 다시 정규화한다.
    norm = out.groupby(["station_no", "day_type", "time_slot"], observed=True)["share"].transform(
        "sum"
    )
    out["share"] = np.where(norm > 0, out["share"] / norm, np.nan)
    return out


def _slot30_to_hour_bucket(slot30: str) -> str:
    hh = int(slot30[:2])
    if hh == 5:
        return "~06"
    if hh == 0:
        return "24~"
    return f"{hh:02d}-{hh + 1:02d}"


def split_hourly_to_30min(
    panel: pd.DataFrame,
    calibration: pd.DataFrame,
    value_cols: Sequence[str] = TARGETS,
    suffix: str = "_30min_est",
) -> pd.DataFrame:
    """1시간 패널 행을 30분 행으로 펼치고 `value_cols`를 비중대로 나눈다.

    `panel`은 date·station_no·day_type·time_slot + value_cols. 반환은 행마다 `time_slot_30min`과
    `{col}{suffix}`, `share`가 붙은 프레임(비중 없는 셀은 NaN). 두 30분 합은 1시간 원본과 같다.
    """
    shares = half_hour_shares(calibration)
    out = panel.copy()
    out["time_slot_30min"] = out["time_slot"].map(hour_bucket_to_30min_slots)
    out = out.explode("time_slot_30min", ignore_index=True)
    out = out.merge(
        shares, on=["station_no", "day_type", "time_slot", "time_slot_30min"], how="left"
    )
    for c in value_cols:
        out[f"{c}{suffix}"] = out[c] * out["share"]
    return out


# ── 2층 ──
def _to_minutes(t: pd.Series) -> pd.Series:
    """'HH:MM' 또는 'HH:MM:SS' → 운행일 기준 분(00~02시는 24시 이후로 접는다)."""
    parts = t.astype(str).str.split(":", expand=True)
    minutes = parts[0].astype(int) * 60 + parts[1].astype(int)
    return minutes.where(minutes >= 4 * 60, minutes + 24 * 60)


def slot30_start_minutes(slot30: str) -> int:
    hh, mm = int(slot30[:2]), int(slot30[3:5])
    m = hh * 60 + mm
    return m + 24 * 60 if hh < 4 else m


def allocate_to_trains(
    slot_loads: pd.DataFrame,
    timetable: pd.DataFrame,
    load_col: str = "onboard_30min_est",
    long_headway_min: float = LONG_HEADWAY_MIN,
) -> pd.DataFrame:
    """30분 슬롯 재차인원을 그 슬롯의 열차에 간격 비례로 배분한다.

    `slot_loads`: date, station_no, direction, day_type, time_slot_30min, `load_col`.
    `timetable`: station_no, direction, day_type, train_id, arrival_time('HH:MM[:SS]').
    반환: 열차 한 대 = 한 행. `load_est`(몫), `headway_min`, `headway_long`, `share`.
    슬롯에 열차가 없으면 그 슬롯은 반환에 나오지 않는다(호출자가 NaN으로 취급).
    """
    tt = timetable.copy()
    tt["arr_min"] = _to_minutes(tt["arrival_time"])
    tt = tt.sort_values(["station_no", "direction", "day_type", "arr_min"]).reset_index(drop=True)
    tt["headway_min"] = tt.groupby(["station_no", "direction", "day_type"], observed=True)[
        "arr_min"
    ].diff()
    # 첫차는 직전 열차가 없다 → 슬롯 길이로 둔다(하한 가정, 플래그는 별도)
    tt["headway_min"] = tt["headway_min"].fillna(float(SLOT_MINUTES))
    tt["slot_start"] = (tt["arr_min"] // SLOT_MINUTES) * SLOT_MINUTES
    tt["time_slot_30min"] = tt["slot_start"].map(_minutes_to_slot30)

    key = ["station_no", "direction", "day_type", "time_slot_30min"]
    slot_total = tt.groupby(key, observed=True)["headway_min"].transform("sum")
    tt["share"] = tt["headway_min"] / slot_total
    tt["headway_long"] = tt["headway_min"] > long_headway_min

    merged = slot_loads.merge(
        tt[[*key, "train_id", "arrival_time", "headway_min", "share", "headway_long"]],
        on=key,
        how="inner",
    )
    merged["load_est"] = merged[load_col] * merged["share"]
    return merged


def _minutes_to_slot30(m: int) -> str:
    m = int(m) % (24 * 60)
    return f"{m // 60:02d}:{m % 60:02d}"


def slots_in_order() -> list[str]:
    """운행일 순서의 30분 슬롯 39개(05:30 … 00:30)."""
    out: list[str] = []
    for bucket in SLOT_ORDER:
        out.extend(hour_bucket_to_30min_slots(bucket))
    return out
