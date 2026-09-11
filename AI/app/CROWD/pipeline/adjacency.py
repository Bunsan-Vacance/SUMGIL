"""노선 토폴로지에서 역별 인접역을 뽑아, 같은 (date, time_slot)의 인접역 값을 피처로 붙인다.

89번(피처 엔지니어링)의 핵심 신규 피처. 지하철 승하차는 노선을 따라 전파되므로
"바로 앞/뒤 역이 같은 시간대에 얼마나 붐볐나"가 이 역의 잔차를 설명할 수 있다는 가설이다.

**순수 함수만 둔다.** 토폴로지 YAML 로딩·역 필터링은 `DATA_ENGINE/eda/build_congestion_label`
(`load_topology`·`resolve_segments`)이 이미 하고 있고, `app/`은 `DATA_ENGINE/`을 import하지
않는 규약이라 여기서는 **이미 펼쳐진 세그먼트 목록**(`stations: list[int]`, 선택적 `circular`)
을 인자로 받는다. pandas 기반이라 Spark에서는 `pandas_udf`로 감쌀 수 있다(`AI/README.md` 8절).

**방향 이름.** 세그먼트 리스트의 인덱스 증가 방향이 `하선`이다(`build_congestion_label.py`의
`ASCENDING="하선"` 상수와 같은 약속 — 9호선은 그 약속을 지키려고 리스트 자체를 역번호
내림차순으로 둔다). 그래서 이 모듈의 두 side는:

- `prev` — 리스트상 직전 역. 하선 열차가 **방금 지나온** 역(= 상선 방향 다음 역).
- `next` — 리스트상 다음 역. 하선 열차가 **다음에 갈** 역(= 상선 방향 직전 역).

상/하선을 모델이 따로 보지는 않는다 — 패널 자체가 방향 없는 역 단위 승하차라서다.
방향별 분리는 93번(호선·상/하선 분할)의 몫이다.

**경계 처리.**
- 종점·`truncated` 절단면: 그쪽 인접역이 없으므로 행이 없다 → 피처는 NaN. 0으로 채우지
  않는다(원칙 8: 표본 없는 구간에 값을 채우지 않는다).
- `circular`(2호선 본선): 마지막 역의 next는 첫 역, 첫 역의 prev는 마지막 역.
- 분기점(5호선 강동, 2호선 성수·신도림): 한 역이 여러 세그먼트에 속해 같은 side에 인접역이
  둘 이상이다. `attach_neighbor_features`가 side별로 **평균**(기본)해 한 값으로 만든다 —
  합계를 쓰면 분기점만 값이 2배로 뛰어 "분기점 여부"를 학습하는 꼴이 된다.
- 환승역: 패널에서 환승역은 호선마다 다른 `station_no`를 갖는다(교대 223/330).
  `build_neighbor_map`은 **같은 호선 토폴로지의 앞뒤 역만** 인접으로 본다. 다른 호선의 같은
  역 노드는 `build_transfer_map`이 별도 side `xfer`로 만든다 — 역명이 같으면 같은 역으로
  본다(패널 역명은 역사마스터 기준으로 정정돼 있어 부기명 차이가 없다). 둘을 concat해서
  `attach_neighbor_features`에 넘기면 `nb_xfer_*` 컬럼이 같이 붙는다.
- 패널에 없는 역(3호선 충무로 321 등)은 `resolve_segments`가 이미 빼서 넘기므로, 그 양옆
  역이 서로 인접으로 잡힌다 — "데이터가 있는 가장 가까운 역"이라는 뜻이고 물리적 인접은
  아니다. 결번 인벤토리는 `resolve_segments`의 `gaps`로 따로 확인한다.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

import pandas as pd

SIDES = ("prev", "next", "xfer")
NEIGHBOR_MAP_COLS = ["station_no", "line", "segment", "side", "neighbor_station_no"]


def build_neighbor_map(segments: Iterable[dict]) -> pd.DataFrame:
    """세그먼트 목록 → (역, side) 별 인접역 long 테이블.

    각 세그먼트는 `stations`(펼쳐진 역번호 리스트)와 선택적 `circular`·`line`·`segment`를
    갖는다. 같은 (station_no, side, neighbor_station_no) 쌍이 여러 세그먼트에서 나오면
    (5호선 본선 끝 강동 ↔ 하남선 첫 강동처럼 겹치는 역) 한 번만 남긴다.
    """
    rows: list[dict] = []
    for seg in segments:
        stations: Sequence[int] = list(seg["stations"])
        n = len(stations)
        if n < 2:
            continue
        circular = bool(seg.get("circular"))
        for i, s in enumerate(stations):
            if i > 0 or circular:
                rows.append(_row(seg, s, "prev", stations[(i - 1) % n]))
            if i < n - 1 or circular:
                rows.append(_row(seg, s, "next", stations[(i + 1) % n]))
    out = pd.DataFrame(rows, columns=NEIGHBOR_MAP_COLS)
    return out.drop_duplicates(["station_no", "side", "neighbor_station_no"]).reset_index(drop=True)


def build_transfer_map(stations: pd.DataFrame) -> pd.DataFrame:
    """같은 역명을 가진 다른 `station_no`(= 다른 호선의 같은 환승역)를 side `xfer`로 잇는다.

    `stations`는 `station_no`·`station_name`(·선택적 `line`) 컬럼을 가진 역 목록이다.
    한 역명에 노드가 하나뿐이면(비환승역) 행이 없다 → 피처는 NaN.
    """
    cols = ["station_no", "station_name"] + (["line"] if "line" in stations.columns else [])
    nodes = stations[cols].drop_duplicates("station_no")
    pairs = nodes.merge(nodes, on="station_name", suffixes=("", "_nb"))
    pairs = pairs[pairs["station_no"] != pairs["station_no_nb"]]
    out = pd.DataFrame(
        {
            "station_no": pairs["station_no"].astype(int).to_numpy(),
            "line": pairs["line"].to_numpy() if "line" in pairs.columns else None,
            "segment": "환승:" + pairs["station_name"].astype(str).to_numpy(),
            "side": "xfer",
            "neighbor_station_no": pairs["station_no_nb"].astype(int).to_numpy(),
        },
        columns=NEIGHBOR_MAP_COLS,
    )
    return out.sort_values(["station_no", "neighbor_station_no"]).reset_index(drop=True)


def _row(seg: dict, station: int, side: str, neighbor: int) -> dict:
    return {
        "station_no": int(station),
        "line": seg.get("line"),
        "segment": seg.get("segment"),
        "side": side,
        "neighbor_station_no": int(neighbor),
    }


def attach_neighbor_features(
    panel: pd.DataFrame,
    neighbor_map: pd.DataFrame,
    value_cols: Sequence[str],
    keys: Sequence[str] = ("date", "time_slot"),
    agg: str = "mean",
    prefix: str = "nb",
) -> pd.DataFrame:
    """`panel`의 각 행에 같은 `keys`(기본 date·time_slot)의 인접역 `value_cols`를 붙인다.

    새 컬럼 이름은 `{prefix}_{side}_{col}` (예: `nb_prev_boarding`). 인접역이 없는 행
    (종점·절단면)은 NaN이고, 인접역이 여럿이면 `agg`로 합친다. 입력 행 순서·개수는 그대로다.
    """
    keys = list(keys)
    value_cols = list(value_cols)
    source = panel[keys + ["station_no", *value_cols]].rename(
        columns={"station_no": "neighbor_station_no"}
    )

    out = panel.copy()
    present = set(neighbor_map["side"].unique())
    for side in (s for s in SIDES if s in present):
        pairs = neighbor_map.loc[
            neighbor_map["side"] == side, ["station_no", "neighbor_station_no"]
        ]
        # 역 → 인접역 값: 인접역 쪽 패널 행을 인접역 번호로 붙이고 (역, keys)로 집계한다.
        joined = pairs.merge(source, on="neighbor_station_no", how="inner")
        feat = joined.groupby(["station_no", *keys], observed=True)[value_cols].agg(agg)
        feat.columns = [f"{prefix}_{side}_{c}" for c in value_cols]
        out = out.merge(feat.reset_index(), on=["station_no", *keys], how="left")
    return out


def neighbor_feature_names(
    value_cols: Sequence[str], prefix: str = "nb", sides: Sequence[str] = ("prev", "next")
) -> list[str]:
    """`attach_neighbor_features`가 만드는 컬럼 이름 목록 — 피처 세트 레지스트리에서 쓴다.

    기본은 노선 앞뒤(`prev`·`next`)만이다. 환승 노드까지 쓰면 `sides=SIDES`.
    """
    return [f"{prefix}_{side}_{c}" for side in sides for c in value_cols]
