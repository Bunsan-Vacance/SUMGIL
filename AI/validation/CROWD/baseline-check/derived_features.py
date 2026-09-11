"""파생 피처(인접역·환승 노드·시차)를 패널에 붙이는 검증용 접착 코드 — 89번(피처 엔지니어링).

순수 함수는 `app/CROWD/pipeline/{adjacency,lags}.py`에 있고, 여기는 그 함수에 **무엇을 먹일지**를
정한다: 토폴로지 로딩·역 필터링(`DATA_ENGINE`의 것을 재사용), 어떤 값을 어떤 시차·이웃으로
끌어올지.

## 잔차를 끌어온다 (원본값이 아니라)

87의 교훈은 "lookup이 이미 설명한 역·시간대 수준을 모델이 다시 배우게 하면 실패한다"였다.
인접역 승하차 **원본값**(`nb_prev_boarding`)은 인접역의 평상시 규모를 그대로 담아 같은 함정에
빠진다 — 실제로 1차 비교에서 잔차 대비 1/4 효과였다(`RESULTS.md`). 그래서 이후 파생은 전부
**lookup 잔차**(`boarding_resid` = 실측 − lookup 예측)를 기준으로 만든다. 원본값 세트는
비교 기준으로만 남긴다.

## 세 종류의 이웃 — 예측 시점에 쓸 수 있는가로 갈린다

| 접두 | 뜻 | 쓸 수 있는 상황 |
| --- | --- | --- |
| `nb_{prev,next}_*` | 같은 호선 앞뒤 역의 **같은 시간대** 값 | 실시간 보정(인접역 집계가 이미 들어온 뒤) |
| `nb_xfer_*` | 같은 역명 다른 호선 노드의 같은 시간대 값 | 실시간 보정 |
| `lag1s_*`, `nb_*_lag1s_*` | 같은 날 **직전 시간대** 값 | 실시간 보정, 1시간 지연 허용 |
| `lag1d_*`, `nb_*_lag1d_*` | **전날** 같은 시간대 값 | 사전 예측 — 전날 집계가 다음 날 아침에 들어올 때 |
| `lag7d_*`, `nb_*_lag7d_*` | **1주 전** 같은 시간대 값 | 사전 예측 — 원천이 일별 CSV여도 안전 |

같은 시간대 이웃(첫 두 줄)은 87 이벤트 피처와 성격이 다르다 — 이벤트 일정은 미리 알지만
인접역 실측은 그 시간이 지나야 안다. 어느 줄까지 쓸지는 서비스의 예측 시점(90번)이 정한다.

## 캐시 — 파생은 한 번, 학습은 여러 번

파생 컬럼 생성은 400만 행에 대한 merge 십여 번이다. 단독으로 재면 약 15초(2026-09-11, SUMGIL
환경)로 학습(LightGBM 8초·XGBoost 30초)과 같은 자릿수지만, 세트마다 프로세스를 새로 띄우면
패널 로딩·lookup fit·파생을 매번 반복한다 — 2차 비교(7세트)가 세트당 4~5분 걸린 것은 이 반복에
다른 실험 프로세스와의 CPU 경합이 겹친 결과였다. 그래서 `load_or_build_derived`가 결과를
`data/CROWD/interim/`에 parquet로 저장하고(다시 읽기 0.4초), 옆 `.meta.json`에 입력 조건(패널
파일 mtime·행 수, 분할 경계, lookup 키, 파생 버전, 컬럼 목록)을 남긴다. 조건이 하나라도 다르면
stale로 보고 다시 만든다. `compare_models.compare_many`는 여기에 더해 세트 목록을 한 프로세스에서
돌려 로딩·fit도 한 번만 한다(`AI/CLAUDE.md` "실험 실행 효율").

## 잔차 계산 기준

잔차는 **학습 구간에 fit한 lookup으로 전체 패널에** 낸다(타깃 잔차와 같은 기준). 시차 피처는
분할 경계를 넘어 참조할 수 있어야 하므로(2025-01-01의 전날은 학습 구간) 분할 전에 전체
패널에서 파생을 만들고 그 뒤에 나눈다. 학습 구간 잔차는 in-sample이라 약간 낙관적이지만
타깃 쪽도 같은 방식이라 일관된다.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

_HERE = Path(__file__).resolve().parent
AI_ROOT = _HERE.parents[2]
for p in (str(_HERE), str(AI_ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

from baseline import DayTypeLookupBaseline
from dataset import CROWD_PROCESSED, PANEL_NAME, SPLIT_DATE, TARGETS

from app.CROWD.pipeline.adjacency import (
    attach_neighbor_features,
    build_neighbor_map,
    build_transfer_map,
    neighbor_feature_names,
)
from app.CROWD.pipeline.lags import (
    attach_day_lags,
    attach_slot_lag,
    day_lag_names,
    slot_lag_names,
)
from DATA_ENGINE.eda.build_congestion_label import load_topology, resolve_segments

CROWD_INTERIM = AI_ROOT / "data" / "CROWD" / "interim"
DERIVED_CACHE = CROWD_INTERIM / "crowd_panel_derived_2024_2025.parquet"
# 파생 규칙(컬럼 정의·조인 방식)이 바뀌면 올린다 — meta가 달라져 캐시가 무효화된다.
DERIVED_VERSION = 1

# 패널의 20개 운행일 슬롯 순서. 사전순이 아니다(`~06`이 첫 슬롯, `24~`가 마지막).
SLOT_ORDER = ["~06"] + [f"{h:02d}-{h + 1:02d}" for h in range(6, 24)] + ["24~"]

DAY_LAGS = (1, 7)
RESID_COLS = [f"{t}_resid" for t in TARGETS]

# ── 세트 레지스트리(features.py)가 참조하는 컬럼 이름 ──
NEIGHBOR_RAW_COLS = neighbor_feature_names(TARGETS)
NEIGHBOR_RESID_COLS = neighbor_feature_names(RESID_COLS)
TRANSFER_RESID_COLS = neighbor_feature_names(RESID_COLS, sides=("xfer",))
SELF_DAY_LAG_COLS = day_lag_names(RESID_COLS, DAY_LAGS)
SELF_DAY_LAG7_COLS = day_lag_names(RESID_COLS, (7,))
SELF_SLOT_LAG_COLS = slot_lag_names(RESID_COLS)
NEIGHBOR_DAY_LAG_COLS = neighbor_feature_names(SELF_DAY_LAG_COLS)
NEIGHBOR_DAY_LAG7_COLS = neighbor_feature_names(SELF_DAY_LAG7_COLS)
NEIGHBOR_SLOT_LAG_COLS = neighbor_feature_names(SELF_SLOT_LAG_COLS)


def neighbor_maps_for(panel: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """(노선 앞뒤 인접역 표, 환승 노드 표, 결번 인벤토리)."""
    segments, gaps = resolve_segments(load_topology(), set(panel["station_no"].unique()))
    line_map = build_neighbor_map(segments)
    transfer_map = build_transfer_map(panel[["station_no", "station_name", "line"]])
    return line_map, transfer_map, gaps


def add_derived_columns(panel: pd.DataFrame, lookup: DayTypeLookupBaseline) -> pd.DataFrame:
    """전체 패널에 잔차 → 시차 → 이웃 순으로 파생 컬럼을 붙인다. 행 순서·개수는 그대로."""
    out = panel.copy()
    pred = lookup.predict(out)
    for t in TARGETS:
        out[f"{t}_resid"] = out[t].to_numpy() - pred[t].to_numpy()

    out = attach_day_lags(out, RESID_COLS, DAY_LAGS)
    out = attach_slot_lag(out, RESID_COLS, SLOT_ORDER)

    line_map, transfer_map, _ = neighbor_maps_for(out)
    # 같은 시간대 이웃: 노선 앞뒤 + 환승 노드. 원본값·잔차 둘 다.
    out = attach_neighbor_features(
        out, pd.concat([line_map, transfer_map], ignore_index=True), [*TARGETS, *RESID_COLS]
    )
    # 시차 이웃: 노선 앞뒤만(환승 노드 시차까지 넣으면 열 수만 는다 — 1차엔 제외).
    out = attach_neighbor_features(out, line_map, [*SELF_DAY_LAG_COLS, *SELF_SLOT_LAG_COLS])
    return out


def _cache_meta(panel: pd.DataFrame, lookup: DayTypeLookupBaseline, split_date) -> dict:
    src = CROWD_PROCESSED / PANEL_NAME
    return {
        "panel_file": src.name,
        "panel_mtime": src.stat().st_mtime if src.exists() else None,
        "panel_rows": len(panel),
        "split_date": str(pd.Timestamp(split_date).date()),
        "lookup_keys": list(lookup.keys),
        "derived_version": DERIVED_VERSION,
    }


def load_or_build_derived(
    panel: pd.DataFrame,
    lookup: DayTypeLookupBaseline,
    split_date=SPLIT_DATE,
    cache_path: Path = DERIVED_CACHE,
    force: bool = False,
) -> pd.DataFrame:
    """캐시가 유효하면 읽고, 아니면 `add_derived_columns`로 만들어 저장한 뒤 돌려준다.

    캐시는 원본 패널 컬럼 + 파생 컬럼 전부를 담은 프레임이라, 돌려준 값이 `panel`을 대신한다.
    행 수·순서는 입력 패널과 같다(같은 정렬로 읽었을 때). 표준 출력에 어느 경로를 탔는지 남긴다.
    """
    meta_path = cache_path.with_suffix(".meta.json")
    want = _cache_meta(panel, lookup, split_date)
    if not force and cache_path.exists() and meta_path.exists():
        have = json.loads(meta_path.read_text(encoding="utf-8"))
        have_cols = have.pop("columns", None)
        if have == want:
            out = pd.read_parquet(cache_path)
            if len(out) == len(panel) and have_cols == list(out.columns):
                print(f"[파생 캐시] 재사용: {cache_path.name}", flush=True)
                return out
            print("[파생 캐시] 행 수·컬럼 불일치 — 다시 만든다", flush=True)
        else:
            print("[파생 캐시] 입력 조건이 달라졌다 — 다시 만든다", flush=True)

    out = add_derived_columns(panel, lookup)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(cache_path, index=False)
    meta_path.write_text(
        json.dumps({**want, "columns": list(out.columns)}, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    print(f"[파생 캐시] 저장: {cache_path.name} ({len(out):,}행, {out.shape[1]}열)", flush=True)
    return out


def needs_derived_columns(cols: list[str]) -> bool:
    return any(c.startswith(("nb_", "lag")) for c in cols)
