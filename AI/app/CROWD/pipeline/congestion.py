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

## 146 — 결측을 줄이되 "채우지" 않는다

세 가지 결측 원인 중 두 개를 라벨 층에서 푼다. 어느 쪽도 값을 지어내지 않고, 대체한 사실은
`calibration_fallback` 불리언으로 그대로 밖에 내보낸다(원칙 8).

- **1~8호선 공휴일**: 배율표에 공휴일 구간이 없어 하루치가 통째로 결측이었다. 공휴일은 서울교통공사
  열차운행시간표가 **일요일 다이어**로 돌고(`timetable_long.parquet`의 요일유형이 평일·토요일·일요일
  3종이며 공휴일 다이어가 따로 없다), 9호선 스냅샷은 아예 토·일·공휴일을 "휴일" 하나로 묶는다 —
  배율의 주 성분이 배차라 일요일 배율로 대체한다(`HOLIDAY_FALLBACK_DAY_TYPE`). 근거 수치는
  `validation/CROWD/congestion-criteria-check/RESULTS.md` 2절.
- **2호선 지선 방향 라벨**: 스냅샷은 지선까지 내선/외선으로 보고하는데 재귀식은 지선을 순환으로 보지
  않아 상선/하선으로 계산한다. 두 지선의 대응이 **서로 반대**라는 것을 출퇴근 비대칭과 상관 두 가지로
  확인해 `BRANCH_DIRECTION_MAP`에 고정했다(같은 RESULTS.md 3절).
- **결번 역**(3호선 충무로·6호선 연신내 등)은 그대로 결측이다 — 승하차 자체가 다른 호선에 계상돼
  대체할 값이 없다.

## 199 — 규칙은 한 곳에만 둔다

배율표(88)를 재적합하면서 "표에 들어간 규칙"과 "런타임 규칙"이 겹치지 않게 정리했다.

- **경계 유입 상수는 표에 실린다.** `raw_offset` 컬럼이 있으면 `apply_calibration`이
  `(raw + raw_offset) × ratio`를 계산한다 — 런타임에 상수를 적합하지 않는다. 상수가 없는(또는 0인)
  표에서는 식이 기존과 완전히 같다. 상수를 어떻게 적합하는지는
  `DATA_ENGINE/eda/boundary_inflow.py`에 있다.
- **`truncated_segments`**는 절단 구간만 골라 준다 — 경계 처리와 상태값의 대상 집합이다.
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

# 1~8호선 공휴일이 빌려 쓸 요일유형(146). 모듈 docstring "결측을 줄이되 채우지 않는다" 참고.
HOLIDAY_FALLBACK_DAY_TYPE = "일요일"

# 2호선 지선 — 재귀식의 상선/하선을 스냅샷(배율표)의 내선/외선으로 옮기는 대응표(146).
#
# **두 지선의 대응이 서로 반대다.** 평일 출근(07~09시)·퇴근(18~20시) 실측 혼잡도의 비대칭으로
# 확정했다(RESULTS.md 3절). 성수지선은 본선(성수) 쪽으로 가는 아침 방향이 `내선`(용답 54.6% vs
# 외선 11.3%)이고, 재귀식에서 그 방향은 리스트 역순 = `상선`이다. 신정지선은 반대로 본선(신도림)
# 쪽 아침 방향이 `외선`(양천구청 90.6% vs 내선 24.8%)이라 `상선`이 `외선`에 붙는다. 재귀식 raw의
# 출퇴근 비대칭이 실측과 같은 부호로 맞는 쪽을 고른 것이고, 셀별 상관(성수 0.60 vs 0.29,
# 신정 0.58 vs 0.37)도 같은 답을 준다.
BRANCH_DIRECTION_MAP = {
    "성수지선": {ASCENDING: "외선", DESCENDING: "내선"},
    "신정지선": {ASCENDING: "내선", DESCENDING: "외선"},
}
# 지선과 본선이 함께 지나는 분기역(성수·신도림)은 본선 세그먼트가 이미 내선/외선으로 값을 낸다.
# 지선 쪽 행까지 같은 라벨로 접으면 한 셀에 값이 두 개 생기므로 대응표에서 뺀다.
BRANCH_JUNCTION_STATIONS = frozenset({211, 234})


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


def bucket_day_type(
    line: pd.Series, day_type: pd.Series, holiday_fallback: str | None = None
) -> pd.Series:
    """패널 4종 day_type을 호선별 스냅샷 체계로 접는다(9호선은 주말·공휴일→휴일).

    1~8호선 공휴일은 대응하는 스냅샷 구간이 없다. 기본값(`holiday_fallback=None`)은 원천 정의
    그대로 None으로 떨궈 조인에서 빠지게 하고, `holiday_fallback="일요일"`을 주면 그 요일유형의
    배율을 빌려 쓴다(146). **대체를 켤지는 부르는 쪽이 정한다** — 배율표를 만드는 쪽
    (`DATA_ENGINE`)은 대체하면 안 되고, 서빙 변환(`apply_calibration`)만 켠다.
    """
    is_line9 = line == "9호선"
    bucketed = day_type.where(~is_line9, day_type.map(_LINE9_DAY_TYPE_BUCKET))
    return bucketed.where(is_line9 | (day_type != "휴일"), holiday_fallback)


def holiday_fallback_mask(line: pd.Series, day_type: pd.Series) -> pd.Series:
    """`bucket_day_type`의 공휴일 대체가 실제로 적용되는 행(1~8호선 × 공휴일)."""
    return (line != "9호선") & (day_type == "휴일")


def bucket_direction(
    segment: pd.Series | None, direction: pd.Series, station_no: pd.Series
) -> pd.Series:
    """재귀식 방향 라벨을 배율표(스냅샷) 방향 라벨로 옮긴다 — 2호선 지선만 해당(146).

    `segment`가 없으면(세그먼트 축이 없는 호출) 아무것도 바꾸지 않는다. 분기역
    (`BRANCH_JUNCTION_STATIONS`)은 본선 세그먼트가 이미 값을 내므로 제외한다.
    """
    out = direction.copy()
    if segment is None:
        return out
    for seg_name, mapping in BRANCH_DIRECTION_MAP.items():
        target = (segment == seg_name) & (~station_no.isin(BRANCH_JUNCTION_STATIONS))
        out = out.where(~target, direction.map(mapping))
    return out


def apply_calibration(
    labels: pd.DataFrame,
    calibration: pd.DataFrame,
    holiday_fallback: str | None = HOLIDAY_FALLBACK_DAY_TYPE,
) -> pd.DataFrame:
    """재귀식 결과(1시간, `day_type` 컬럼 포함)를 30분으로 펼쳐 배율을 곱한다.

    `calibration`은 `crowd_congestion_calibration.parquet`(station_no·direction·day_type·time_slot·ratio).
    배율이 없는 셀은 `congestion_pct_calibrated`가 NaN.

    조인 키는 원본 라벨이 아니라 **접은 라벨**(`day_type_bucket`·`direction_bucket`)이다 — 출력의
    `day_type`·`direction`은 그대로 두고, 공휴일을 다른 요일유형의 배율로 채운 행은
    `calibration_fallback=True`로 표시한다(146, 원칙 8).

    배율표에 `raw_offset` 컬럼이 있으면 **`(raw + raw_offset) × ratio`**로 계산한다(199) — 절단면
    바깥에서 들어와 구간을 통과하는 승객(정원 % 단위)을 재귀식 raw에 되돌려 주는 항이고, 배율은
    그 더해진 raw로 적합된 값이다. 컬럼이 없거나 0이면 기존과 완전히 같은 식이다.
    """
    frame = labels.copy()
    frame["day_type_bucket"] = bucket_day_type(frame["line"], frame["day_type"], holiday_fallback)
    frame["calibration_fallback"] = (holiday_fallback is not None) & holiday_fallback_mask(
        frame["line"], frame["day_type"]
    )
    frame["direction_bucket"] = bucket_direction(
        frame["segment"] if "segment" in frame.columns else None,
        frame["direction"],
        frame["station_no"],
    )
    frame["time_slot_30min"] = frame["time_slot"].map(hour_bucket_to_30min_slots)
    frame = frame.explode("time_slot_30min", ignore_index=True)
    cal_cols = ["station_no", "direction", "day_type", "time_slot", "ratio"]
    if "raw_offset" in calibration.columns:
        cal_cols.append("raw_offset")
    ratio_key = calibration[cal_cols].rename(
        columns={
            "direction": "direction_bucket",
            "day_type": "day_type_bucket",
            "time_slot": "time_slot_30min",
        }
    )
    merged = frame.merge(
        ratio_key,
        on=["station_no", "direction_bucket", "day_type_bucket", "time_slot_30min"],
        how="left",
    )
    offset = (
        merged["raw_offset"].fillna(0.0) if "raw_offset" in merged.columns else 0.0
    )  # 표에 없으면 0 — 88·146 표와 식이 같다
    merged["congestion_pct_calibrated"] = (merged["congestion_raw_pct"] + offset) * merged["ratio"]
    # 대체 요일유형으로도 값이 안 나온 셀은 "대체됨"이 아니라 그냥 결측이다.
    merged["calibration_fallback"] = (
        merged["calibration_fallback"] & merged["congestion_pct_calibrated"].notna()
    )
    return merged


def truncated_segments(segments: Sequence[dict], lines: Sequence[str] | None = None) -> list[dict]:
    """`truncated: true`인 선형 세그먼트만 — 절단면 처리(경계 유입·상태값)의 대상 집합(199).

    순환 세그먼트(2호선 본선)와 역이 2개 미만인 세그먼트는 종점 링크 개념이 성립하지 않아 뺀다.
    `lines`를 주면 그 호선으로 좁힌다(`None`이면 전부). 진짜 종점(6호선 응암 순환 시작, 5호선
    지선 종점 등)은 이 플래그가 없어 자동으로 빠진다 — 거기서는 재차 0이 **정답**이다.
    """
    return [
        seg
        for seg in segments
        if seg.get("truncated")
        and not seg.get("circular")
        and len(seg.get("stations", ())) >= 2
        and (lines is None or seg["line"] in lines)
    ]


def truncated_boundary_cells(
    segments: Sequence[dict], lines: Sequence[str] | None = ("1호선",)
) -> set[tuple[int, str]]:
    """절단 구간의 **종점 링크** (역번호, 방향) 집합 — 구조적으로 재차 0이 되는 셀(146).

    선형 세그먼트에서 오름차순 방향의 마지막 역과 내림차순 방향의 첫 역은 "이 역을 출발한 직후"
    통과량이 정의상 0이다. 실제 종점이면 0이 맞지만 `truncated: true` 구간은 절단면이라 0이 틀리다
    — 1호선은 서울역(150) 상선·청량리(158) 하선이 여기 해당하고, 실측 스냅샷은 그 셀에 평일 평균
    32.5%·24.4%를 보고한다. 배율은 raw 평균 0이 분모라 산출 자체가 안 돼(ratio NaN) 값을 낼 수
    없으므로, 값을 지어내는 대신 `data_status`로 사유를 밝힌다.

    `lines`로 범위를 좁힌다 — 146의 스코프는 1호선이었다. `None`이면 3·4·7·9호선 본선과 신정지선
    까지 전부(199 B가 절단면 경계를 판정할 때 쓴다).
    """
    out: set[tuple[int, str]] = set()
    for seg in truncated_segments(segments, lines):
        stations = seg["stations"]
        out.add((stations[-1], ASCENDING))
        out.add((stations[0], DESCENDING))
    return out


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
