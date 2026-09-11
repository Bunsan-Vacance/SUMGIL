"""승하차 → 재귀식 재차인원 → 배율표 30분 보정 혼잡도 → 등급. 서빙 배치용 순수 함수.

`DATA_ENGINE/eda/build_congestion_label.py`(재귀식·방향 분해)와 `build_congestion_label_calibrated.py`
(30분 배율 적용)에서 동작만 옮겼다. 결정 근거·검증 경위(방향 라벨이 실측과 뒤집혔던 경위, 배율표가
스케일과 30분 모양을 동시에 맞추는 이유, 알려진 결측)는 그 두 파일과 Notion "혼잡도 타겟 정의",
"혼잡도 시간 해상도" 페이지에 있다. `app/`은 `DATA_ENGINE/`을 import하지 않는 규약이라 복제했고,
DATA_ENGINE 쪽이 나중에 여기를 import하는 방향으로 합치면 된다.

## 파이프라인

    승하차(date, station_no, time_slot)
      → segment_loads: 세그먼트별 방향 분해(비례 배분 OD, 순환선은 OD 행렬) → onboard, congestion_raw_pct
      → apply_calibration: 30분 슬롯으로 펼치고 배율표(역·방향·요일유형·30분) 곱 → congestion_pct_calibrated
      → grade: 임계치 → 등급 정수

## 결측은 값으로 채우지 않는다

배율표가 없는 셀(2호선 지선 방향 체계 불일치, 1~8호선 공휴일, 결번 역)은 NaN이고 등급도 NaN이다.
API는 이 셀을 "데이터 부족"으로 노출한다(원칙 8). `congestion_raw_pct`는 배차 미보정이라 절대값을
그대로 쓰면 안 된다 — 항상 배율을 거친 값만 밖으로 낸다.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import pandas as pd

# 역번호 오름차순(= 세그먼트 리스트 순서) 진행 방향이 "하선". 2호선 순환선은 내선/외선.
ASCENDING, DESCENDING = "하선", "상선"
CIRCULAR_LABELS = {ASCENDING: "내선", DESCENDING: "외선"}

# 9호선 스냅샷은 토·일·공휴일을 "휴일" 하나로 묶고, 1~8호선 스냅샷에는 "휴일" 구간이 없다.
_LINE9_DAY_TYPE_BUCKET = {"평일": "평일", "토요일": "휴일", "일요일": "휴일", "휴일": "휴일"}


# ── 방향 분해 ──
def directional_loads(boarding: np.ndarray, alighting: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """선형 구간: 비례 배분 OD로 각 역을 출발한 직후 링크의 오름차순·내림차순 통과량."""
    total_alight = alighting.sum()
    if total_alight <= 0:
        return np.zeros_like(boarding), np.zeros_like(boarding)
    denom = total_alight - alighting
    weight = np.divide(boarding, denom, out=np.zeros_like(boarding), where=denom > 0)
    cum_alight = np.cumsum(alighting)
    alight_after = total_alight - cum_alight
    alight_before = cum_alight - alighting
    cum_weight = np.cumsum(weight)
    weight_from = cum_weight[-1] - cum_weight + weight
    return cum_weight * alight_after, weight_from * alight_before


def circular_path_masks(n: int) -> tuple[np.ndarray, np.ndarray]:
    """순환선에서 OD (i,j)가 링크 k를 지나는지 — 역 수가 적은 쪽 경로를 택한다고 본다."""
    idx = np.arange(n)
    i = idx[None, :, None]
    j = idx[None, None, :]
    k = idx[:, None, None]
    dist_asc = (j - i) % n
    dist_desc = (i - j) % n
    use_asc = (dist_asc <= dist_desc) & (dist_asc > 0)
    use_desc = (dist_desc < dist_asc) & (dist_desc > 0)
    on_asc = ((k - i) % n) < dist_asc
    on_desc = ((i - 1 - k) % n) < dist_desc
    return (on_asc & use_asc), (on_desc & use_desc)


def circular_loads(
    boarding: np.ndarray, alighting: np.ndarray, masks: tuple[np.ndarray, np.ndarray]
) -> tuple[np.ndarray, np.ndarray]:
    """순환선: OD 행렬을 실제로 만들어 링크별 통과량을 낸다(2호선 43역 → 43×43)."""
    total_alight = alighting.sum()
    if total_alight <= 0:
        return np.zeros_like(boarding), np.zeros_like(boarding)
    denom = total_alight - alighting
    weight = np.divide(boarding, denom, out=np.zeros_like(boarding), where=denom > 0)
    od = np.outer(weight, alighting)
    np.fill_diagonal(od, 0.0)
    asc_mask, desc_mask = masks
    return (asc_mask * od).sum(axis=(1, 2)), (desc_mask * od).sum(axis=(1, 2))


def segment_loads(panel: pd.DataFrame, seg: dict, capacity: dict) -> pd.DataFrame | None:
    """한 세그먼트의 모든 (date, time_slot)에 대해 방향별 재차인원과 raw 혼잡도.

    `panel`은 date·station_no·time_slot·boarding·alighting 컬럼(결측은 0으로 채워 넘긴다).
    `capacity`는 `train_capacity.yaml` 내용(`cars_per_train[line]`, `car_capacity`).
    """
    stations = seg["stations"]
    if len(stations) < 2:
        return None
    order = {s: i for i, s in enumerate(stations)}
    sub = panel[panel["station_no"].isin(stations)].copy()
    if sub.empty:
        return None
    sub["seq"] = sub["station_no"].map(order)
    n = len(stations)
    board = (
        sub.pivot_table(
            index=["date", "time_slot"], columns="seq", values="boarding", aggfunc="sum"
        )
        .reindex(columns=range(n))
        .fillna(0.0)
    )
    alight = (
        sub.pivot_table(
            index=["date", "time_slot"], columns="seq", values="alighting", aggfunc="sum"
        )
        .reindex(columns=range(n))
        .fillna(0.0)
    )
    b, a = board.to_numpy(), alight.to_numpy()
    up, down = np.empty_like(b), np.empty_like(b)
    masks = circular_path_masks(n) if seg.get("circular") else None
    for r in range(b.shape[0]):
        if masks is None:
            up[r], down[r] = directional_loads(b[r], a[r])
        else:
            up[r], down[r] = circular_loads(b[r], a[r], masks)

    cars = seg.get("cars_per_train") or capacity["cars_per_train"][seg["line"]]
    train_capacity = cars * capacity["car_capacity"]
    records = []
    for label, load in ((ASCENDING, up), (DESCENDING, down)):
        direction = CIRCULAR_LABELS[label] if seg.get("circular") else label
        frame = pd.DataFrame(load, index=board.index, columns=stations).stack().reset_index()
        frame.columns = ["date", "time_slot", "station_no", "onboard"]
        frame["direction"] = direction
        records.append(frame)
    out = pd.concat(records, ignore_index=True)
    out["line"] = seg["line"]
    out["segment"] = seg["segment"]
    out["train_capacity"] = train_capacity
    out["congestion_raw_pct"] = out["onboard"] / train_capacity * 100
    return out


def recursive_congestion(
    panel: pd.DataFrame, segments: Sequence[dict], capacity: dict
) -> pd.DataFrame:
    """승하차 판 전체 → 세그먼트별 재귀식 결과를 이어 붙인다."""
    cols = ["date", "station_no", "time_slot", "boarding", "alighting"]
    frame = panel[cols].copy()
    frame[["boarding", "alighting"]] = frame[["boarding", "alighting"]].fillna(0.0)
    frames = [f for seg in segments if (f := segment_loads(frame, seg, capacity)) is not None]
    if not frames:
        return pd.DataFrame(
            columns=[
                *cols[:3],
                "onboard",
                "direction",
                "line",
                "segment",
                "train_capacity",
                "congestion_raw_pct",
            ]
        )
    return pd.concat(frames, ignore_index=True)


# ── 30분 배율 ──
def hour_bucket_to_30min_slots(hour_bucket: str) -> list[str]:
    """`06-07` → [`06:00`, `06:30`]; `~06` → [`05:30`]; `24~` → [`00:00`, `00:30`]."""
    if hour_bucket == "24~":
        return ["00:00", "00:30"]
    if hour_bucket == "~06":
        return ["05:30"]
    hour = int(hour_bucket.split("-")[0])
    return [f"{hour:02d}:00", f"{hour:02d}:30"]


def bucket_day_type(line: pd.Series, day_type: pd.Series) -> pd.Series:
    """패널 4종 day_type을 호선별 스냅샷 체계로 접는다(9호선은 주말·공휴일→휴일, 1~8호선 공휴일→None)."""
    is_line9 = line == "9호선"
    bucketed = day_type.where(~is_line9, day_type.map(_LINE9_DAY_TYPE_BUCKET))
    return bucketed.where(is_line9 | (day_type != "휴일"), None)


def apply_calibration(labels: pd.DataFrame, calibration: pd.DataFrame) -> pd.DataFrame:
    """재귀식 결과(1시간, `day_type` 컬럼 포함)를 30분으로 펼쳐 배율을 곱한다.

    `calibration`은 `crowd_congestion_calibration.parquet`(station_no·direction·day_type·time_slot·ratio).
    배율이 없는 셀은 `congestion_pct_calibrated`가 NaN.
    """
    frame = labels.copy()
    frame["day_type_bucket"] = bucket_day_type(frame["line"], frame["day_type"])
    frame["time_slot_30min"] = frame["time_slot"].map(hour_bucket_to_30min_slots)
    frame = frame.explode("time_slot_30min", ignore_index=True)
    ratio_key = calibration[["station_no", "direction", "day_type", "time_slot", "ratio"]].rename(
        columns={"day_type": "day_type_bucket", "time_slot": "time_slot_30min"}
    )
    merged = frame.merge(
        ratio_key, on=["station_no", "direction", "day_type_bucket", "time_slot_30min"], how="left"
    )
    merged["congestion_pct_calibrated"] = merged["congestion_raw_pct"] * merged["ratio"]
    return merged


# ── 등급 ──
def grade(values: pd.Series, thresholds: Sequence[float]) -> pd.Series:
    """임계치 목록으로 0..len(thresholds) 등급. NaN은 NaN 유지(채우지 않는다)."""
    out = pd.Series(
        np.searchsorted(
            np.asarray(thresholds, dtype=float), values.to_numpy(dtype=float), side="right"
        ),
        index=values.index,
        dtype="float",
    )
    out[values.isna()] = np.nan
    return out
