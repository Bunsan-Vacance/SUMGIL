"""절단면 경계 유입 상수 — 재귀식이 못 본 "구간 밖에서 들어와 통과하는 승객"을 정원 % 단위로 적합한다.

## 문제 (146 §4-C·§4-D, 199 B)

`line_topology.yaml`의 `truncated: true` 구간은 양 끝이 실제 종점이 아니라 **절단면**이다(코레일·인천
교통공사 직결 구간이 우리 원천에 없다). 재귀식은 "구간 안에서 타고 구간 안에서 내린다"는 닫힌 OD를
가정하므로 절단면 바깥에서 들어온 통과 승객을 통째로 놓친다. 그 결과 진행방향 마지막 링크의 재차가
정의상 0이 되고, 배율(`실측 ÷ raw 평균`)은 분모가 0이라 **산출 자체가 안 된다**(1호선 서울역 상선·
청량리 하선 = 하루 78셀).

146 §4-C가 역 축을 자유도로 남긴 `meas ≈ s·raw + c` 적합에서 상수항이 정원의 20~30%(상수 17.6~32.2%p,
셀 97.4%가 양수)로 **실재함**을 확인했다. 146 §4-D의 (a)가 실패한 이유는 그 상수를 **기존 배율표 위에**
더한 이중 계상이었다 — `s`가 raw를 실측 축으로 줄이는 배율(≈0.1)이라, 상수를 raw 축으로 환산(`c / s`)
하지 않고 그대로 더하면 10배 과대해진다. 여기서는 상수를 raw 축으로 환산해 주입한 뒤 **배율을 다시
적합**하므로 그 문제가 생기지 않는다.

## 두 적합 방식(199에서 같은 심판으로 비교한다)

| 방식 | 스케일 | 상수 | 성질 |
| --- | --- | --- | --- |
| `joint` | 2모수 최소자승(146 §4-C 그대로) | 같은 적합의 절편 ÷ 기울기 | 원안. `s → 0`인 슬롯에서 발산한다 |
| `anchored` | 내부 셀(raw > 0)만으로 1모수 | 경계 셀 실측 ÷ 스케일 | 자유도를 하나 줄여 안정적 |

두 방식 다 같은 모형 `meas ≈ s·(raw + offset)`이다. `anchored`에서 경계 셀은 raw가 0이라
`ratio = meas / offset = s` — 그 구간·슬롯의 평균 배율을 그대로 받는다.

## 적용 범위

- `segment` — 구간 전체의 같은 방향 셀에 상수를 더한다. 통과 승객은 구간 내내 타고 있다는 모형에
  충실하지만, 내부 셀의 배율까지 모두 바뀌고 **상수가 raw를 압도하는 슬롯에서는 날짜별 변동이
  희석된다**(예측이 정적 표에 가까워진다).
- `cell` — 구조적으로 raw가 0인 경계 셀에만 준다. 내부 셀의 배율은 주입 전과 **완전히 같다**.

진짜 종점(6호선 응암 순환 시작, 5호선 지선 종점 등)은 `truncated` 플래그가 없어 대상이 아니다 —
거기서는 재차 0이 정답이다. 9호선은 패널 밖이라 스코프에서 뺀다.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from app.CROWD.pipeline.congestion import BRANCH_JUNCTION_STATIONS, truncated_segments
from app.CROWD.pipeline.topology import load_topology, resolve_segments

# 상수를 적합하는 단위 — 역 축만 자유도로 남긴다(146 §4-C).
BOUNDARY_FIT_KEYS = ["line", "segment", "direction", "day_type", "time_slot"]
# 9호선은 패널 밖이라 199 스코프에서 뺀다(표는 88 그대로 유지).
BOUNDARY_EXCLUDED_LINES = ("9호선",)
# 적합 가드.
BOUNDARY_MIN_POINTS = 4  # 역 축 표본. 2모수 적합이 보간으로 무너지지 않을 최소치
BOUNDARY_MIN_SLOPE = 1e-6  # s → 0에서 c/s가 발산한다


def truncated_station_map(available: set[int]) -> pd.DataFrame:
    """절단 구간(`truncated: true`)에 속한 역 → `segment`. 경계 유입 적합의 대상 표.

    토폴로지를 실제로 있는 역으로 좁혀(`resolve_segments`) 결번이 자동으로 빠지게 한다.
    분기역(성수 211·신도림 234)은 본선 세그먼트가 이미 값을 내므로 뺀다 — 남기면 한 역이 두 구간의
    상수를 동시에 받는다.
    """
    segments, _ = resolve_segments(load_topology(), available)
    rows = [
        {"station_no": station, "segment": seg["segment"]}
        for seg in truncated_segments(segments)
        if seg["line"] not in BOUNDARY_EXCLUDED_LINES
        for station in seg["stations"]
        if station not in BRANCH_JUNCTION_STATIONS
    ]
    return pd.DataFrame(rows, columns=["station_no", "segment"]).drop_duplicates("station_no")


def _offset_joint(x: np.ndarray, y: np.ndarray) -> float:
    """146 §4-C 그대로 `meas ≈ s·raw + c`를 풀고 `c / s`(정원 %)를 돌려준다.

    가드 셋: 역 축 표본이 `BOUNDARY_MIN_POINTS` 미만이거나 raw가 상수면 2모수 적합이 사실상
    보간이다; 기울기가 0에 붙으면 `c / s`가 발산한다; 절편은 `[0, 그 그룹 실측 최대]`로 자르고,
    상수를 넣어 MAE가 나아지지 않으면 넣지 않는다(146의 판정 축 그대로).
    """
    if len(x) < BOUNDARY_MIN_POINTS or np.ptp(x) <= 0:
        return 0.0
    slope, const = np.polyfit(x, y, 1)
    denom = float((x * x).sum())
    slope_only = float((x * y).sum() / denom) if denom > 0 else 0.0
    const = min(max(float(const), 0.0), float(y.max()))
    improved = np.abs(slope * x + const - y).mean() < np.abs(slope_only * x - y).mean()
    return const / float(slope) if slope > BOUNDARY_MIN_SLOPE and improved else 0.0


def _offset_anchored(x: np.ndarray, y: np.ndarray) -> float:
    """스케일은 내부 셀(raw > 0)만으로 1모수 적합하고, 상수는 경계 셀 실측으로 못박는다.

    `s = Σxy / Σx²`, `offset = mean(meas | raw == 0) / s`. 경계 셀이 없거나(그 방향의 끝이 이 구간에
    없다) 스케일이 0 이하면 0 — 값을 지어내지 않는다(원칙 1·8). 경계 셀 실측이 0이면(3호선 오금처럼
    실제 종점이라 스냅샷도 0을 적는다) 상수도 0이 되어 자동으로 대상에서 빠진다.
    """
    interior = x > 0
    boundary = ~interior
    denom = float((x[interior] ** 2).sum())
    if denom <= 0 or not boundary.any():
        return 0.0
    slope = float((x[interior] * y[interior]).sum() / denom)
    if slope <= BOUNDARY_MIN_SLOPE:
        return 0.0
    return max(float(y[boundary].mean()), 0.0) / slope


_SOLVERS = {"joint": _offset_joint, "anchored": _offset_anchored}


def fit_boundary_inflow(
    frame: pd.DataFrame, scale: float = 1.0, method: str = "anchored"
) -> pd.DataFrame:
    """`BOUNDARY_FIT_KEYS`마다 경계 유입 상수(정원 %)를 적합한다.

    `frame`은 절단 구간 역만 남긴 (역 × 방향 × 요일유형 × 30분) 표로 `raw_mean`·`congestion_pct`를
    갖는다. `scale`은 상수의 배수다 — **0이면 전부 0이라 주입하지 않은 표와 수치가 같다**(회귀 테스트).
    """
    solver = _SOLVERS[method]
    rows = []
    for key, sub in frame.groupby(BOUNDARY_FIT_KEYS, observed=True, sort=True):
        d = sub.dropna(subset=["raw_mean", "congestion_pct"])
        offset = solver(
            d["raw_mean"].to_numpy(dtype=float), d["congestion_pct"].to_numpy(dtype=float)
        )
        rows.append({**dict(zip(BOUNDARY_FIT_KEYS, key)), "raw_offset": offset * scale})
    return pd.DataFrame(rows, columns=[*BOUNDARY_FIT_KEYS, "raw_offset"])


def boundary_offsets(
    frame: pd.DataFrame,
    available: set[int],
    method: str = "anchored",
    apply_to: str = "segment",
    scale: float = 1.0,
) -> pd.DataFrame:
    """`frame`의 각 (역·방향·요일유형·30분) 셀에 붙일 `raw_offset` — 절단 구간 밖은 0이다.

    `frame`은 `station_no·line·direction·day_type·time_slot·raw_mean·congestion_pct`를 갖는
    표다(`time_slot`은 30분). 배율표 산출(`build_congestion_calibration`)과 연도 홀드아웃
    (`validation/CROWD/calibration-holdout/holdout.py`)이 **같은 함수**를 쓴다 — 심판과 산출물이
    다른 상수를 쓰면 비교가 성립하지 않는다.
    """
    cell_key = ["station_no", "direction", "day_type", "time_slot"]
    zero = frame[cell_key].copy()
    zero["raw_offset"] = 0.0
    targets = truncated_station_map(available)
    if targets.empty:
        return zero
    tagged = frame.merge(targets, on="station_no", how="inner")
    if tagged.empty:
        return zero
    offsets = fit_boundary_inflow(tagged, scale=scale, method=method)
    keyed = tagged.merge(offsets, on=BOUNDARY_FIT_KEYS, how="left")
    if apply_to == "cell":
        # 경계 셀(구조적으로 raw 0)에만 상수를 준다 — 내부 셀의 배율은 주입 전과 완전히 같다.
        keyed.loc[keyed["raw_mean"] != 0, "raw_offset"] = 0.0
    elif apply_to != "segment":
        raise ValueError(f"알 수 없는 경계 적용 범위: {apply_to!r}")
    out = zero.merge(keyed[[*cell_key, "raw_offset"]], on=cell_key, how="left", suffixes=("_0", ""))
    out["raw_offset"] = out["raw_offset"].fillna(0.0)
    return out[[*cell_key, "raw_offset"]]


def boundary_neighbors(available: set[int]) -> dict[int, int]:
    """절단 구간의 경계 역 → 그 구간에서 **바로 옆 역**. B2(인접역 보간)가 쓴다."""
    segments, _ = resolve_segments(load_topology(), available)
    out: dict[int, int] = {}
    for seg in truncated_segments(segments):
        if seg["line"] in BOUNDARY_EXCLUDED_LINES:
            continue
        stations = seg["stations"]
        for edge, neighbor in ((stations[-1], stations[-2]), (stations[0], stations[1])):
            if edge not in BRANCH_JUNCTION_STATIONS:
                out[edge] = neighbor
    return out


def borrow_neighbor_boundary(table: pd.DataFrame, available: set[int]) -> pd.DataFrame:
    """B2 — 경계 셀에 **인접역 같은 방향의 배율과 raw 평균**을 그대로 옮긴다(재귀식 불변).

    계획이 적은 "인접역 배율로 보간"을 문자 그대로 하면 값이 0이 된다 — 경계 셀의 raw가 정의상
    0이라 `0 × 배율 = 0`이기 때문이다. 뜻이 통하는 유일한 읽기는 **배율이 아니라 값을 빌리는 것**
    이라, 배율과 함께 인접역의 raw 평균을 `raw_offset`으로 넣어 `(0 + raw_nb) × ratio_nb`
    = 인접역의 날짜 평균 보정 혼잡도가 나오게 한다. 그 대가로 **그 셀은 날짜에 반응하지 않는
    정적 값**이 된다(146 §4-D가 (b)를 기각할 때 든 바로 그 대가의 축소판).
    """
    out = table.copy()
    if "raw_offset" not in out.columns:
        out["raw_offset"] = 0.0
    neighbors = boundary_neighbors(available)
    target = out["ratio"].isna() & (out["raw_mean"] == 0) & out["station_no"].isin(neighbors)
    if not target.any():
        return out
    source = out[["station_no", "direction", "day_type", "time_slot", "ratio", "raw_mean"]].rename(
        columns={"station_no": "_nb", "ratio": "_nb_ratio", "raw_mean": "_nb_raw"}
    )
    out["_nb"] = out["station_no"].map(neighbors)
    merged = out.merge(source, on=["_nb", "direction", "day_type", "time_slot"], how="left")
    fill = target.to_numpy() & merged["_nb_ratio"].notna().to_numpy()
    merged.loc[fill, "raw_offset"] = merged.loc[fill, "_nb_raw"]
    merged.loc[fill, "ratio"] = merged.loc[fill, "_nb_ratio"]
    return merged.drop(columns=["_nb", "_nb_ratio", "_nb_raw"])
