"""학습·추론용 패널 로딩과 파생 캐시.

`validation/CROWD/baseline-check/dataset.py`·`derived_features.py`의 로딩·캐시 부분을 승격했다.
분할 기준(2024 학습 / 2025 평가, 시간 분할)과 이벤트 결측 처리 규칙은 validation 문서에 근거가
있다 — 무작위 분할은 같은 날의 다른 시간대가 학습·평가에 갈라 들어가 누수가 생기고, 이벤트
**개수** 컬럼만 0으로 채운다("이벤트가 없었다"가 0인 게 맞다). 관중수·축제 최단 기간처럼 개수가
아닌 컬럼은 채우지 않는다.

파생 캐시(`load_or_build_derived`)는 파생 컬럼 생성(400만 행 merge, 약 15초)을 한 번만 하고
parquet로 재사용한다. 옆 `.meta.json`에 입력 조건(패널 파일 mtime·행 수, lookup 키, 파생 버전)을
남겨 하나라도 다르면 다시 만든다(`AI/CLAUDE.md` "실험 실행 효율").
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from app.CROWD.pipeline.features import DERIVED_VERSION, add_derived_columns
from app.CROWD.pipeline.lookup import TARGETS, DayTypeLookupBaseline
from app.CROWD.pipeline.topology import DEFAULT_TOPOLOGY_PATH, load_topology, resolve_segments

AI_ROOT = Path(__file__).resolve().parents[3]
CROWD_PROCESSED = AI_ROOT / "data" / "CROWD" / "processed"
CROWD_INTERIM = AI_ROOT / "data" / "CROWD" / "interim"

PANEL_NAME = "crowd_panel_2024_2025.parquet"
EVENTS_NAME = "crowd_station_events_2024_2025.parquet"
DERIVED_CACHE = CROWD_INTERIM / "crowd_panel_derived_2024_2025.parquet"

SPLIT_DATE = pd.Timestamp("2025-01-01")

EVENT_COUNT_COLS = ["game_count", "festival_count", "festival_short_count", "festival_long_count"]


def load_panel(
    with_events: bool = True,
    panel_path: Path = CROWD_PROCESSED / PANEL_NAME,
    events_path: Path = CROWD_PROCESSED / EVENTS_NAME,
) -> pd.DataFrame:
    """패널을 읽고 타깃 결측 행을 버린 뒤, 이벤트 컬럼을 붙인다."""
    panel = pd.read_parquet(panel_path).dropna(subset=TARGETS)
    if with_events:
        events = pd.read_parquet(events_path)
        panel = panel.merge(events, on=["date", "station_no"], how="left")
        for col in EVENT_COUNT_COLS:
            if col in panel.columns:
                panel[col] = panel[col].fillna(0).astype(int)
    return panel.reset_index(drop=True)


def time_split(
    panel: pd.DataFrame, split_date: pd.Timestamp = SPLIT_DATE
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """학습(경계 이전)과 평가(경계 이후)로 나눈다."""
    train = panel[panel["date"] < split_date].reset_index(drop=True)
    test = panel[panel["date"] >= split_date].reset_index(drop=True)
    return train, test


def resolved_segments(panel: pd.DataFrame, topology_path: Path = DEFAULT_TOPOLOGY_PATH):
    """패널에 있는 역만 남긴 세그먼트와 결번 인벤토리."""
    return resolve_segments(load_topology(topology_path), set(panel["station_no"].unique()))


def _cache_meta(panel: pd.DataFrame, lookup: DayTypeLookupBaseline, panel_path: Path) -> dict:
    return {
        "panel_file": Path(panel_path).name,
        "panel_mtime": Path(panel_path).stat().st_mtime if Path(panel_path).exists() else None,
        "panel_rows": len(panel),
        "lookup_keys": list(lookup.keys),
        "derived_version": DERIVED_VERSION,
    }


def load_or_build_derived(
    panel: pd.DataFrame,
    lookup: DayTypeLookupBaseline,
    cache_path: Path = DERIVED_CACHE,
    panel_path: Path = CROWD_PROCESSED / PANEL_NAME,
    topology_path: Path = DEFAULT_TOPOLOGY_PATH,
    force: bool = False,
) -> pd.DataFrame:
    """캐시가 유효하면 읽고, 아니면 `add_derived_columns`로 만들어 저장한 뒤 돌려준다."""
    cache_path = Path(cache_path)
    meta_path = cache_path.with_suffix(".meta.json")
    want = _cache_meta(panel, lookup, panel_path)
    if not force and cache_path.exists() and meta_path.exists():
        have = json.loads(meta_path.read_text(encoding="utf-8"))
        have_cols = have.pop("columns", None)
        have.pop("split_date", None)  # 옛 validation 캐시 meta 호환
        if have == want:
            out = pd.read_parquet(cache_path)
            if len(out) == len(panel) and have_cols == list(out.columns):
                print(f"[파생 캐시] 재사용: {cache_path.name}", flush=True)
                return out
            print("[파생 캐시] 행 수·컬럼 불일치 — 다시 만든다", flush=True)
        else:
            print("[파생 캐시] 입력 조건이 달라졌다 — 다시 만든다", flush=True)

    segments, gaps = resolved_segments(panel, topology_path)
    if len(gaps):
        print("[안내] 토폴로지에 있으나 패널에 없는 역(양옆 역이 인접으로 이어진다):", flush=True)
        print(gaps.to_string(index=False), flush=True)
    out = add_derived_columns(panel, lookup, segments)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(cache_path, index=False)
    meta_path.write_text(
        json.dumps({**want, "columns": list(out.columns)}, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    print(f"[파생 캐시] 저장: {cache_path.name} ({len(out):,}행, {out.shape[1]}열)", flush=True)
    return out
