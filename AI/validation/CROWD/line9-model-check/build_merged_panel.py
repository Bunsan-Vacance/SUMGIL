"""9호선 모델 검증(line9-model-check) 1단계 — 메인 패널 + 9호선 패널 병합.

## 왜

혼잡도 예측 모델은 지금 1~8호선(273역)만 학습돼 있다. 9호선 2·3단계 13역(4126 언주 ~
4138 중앙보훈병원)은 학습 패널에 없어 모델을 못 타고 lookup 기준선만 쓴다 — 그런데 원천은
이미 있다: `crowd_panel_line9_2025_2026.parquet`이 메인 패널과 완전히 같은 스키마(22열)로
102,960행을 갖고 있다. 이 스크립트는 두 패널을 합쳐 **학습 창 안(2024-01-01~2025-12-31)만**
잘라 붙인다 — 2026-01 부분은 학습 창 밖이라 제외한다.

## 하지 않는 것(리포 원칙 8 — 표본 부족 구간에 값을 채우지 않는다)

9호선 패널에는 `alighting`이 NaN인 행이 약 1,040건 있다고 알려져 있다. **채우지도, 버리지도
않는다** — `load_panel`(`dataset.py`)이 타깃 NaN 행을 dropna하는 것은 그 함수의 몫이고, 이
스크립트는 원본을 그대로 이어붙이는 것까지만 한다. 실제 NaN 건수는 실행 로그에 남긴다.

## 검증

- 병합 후 컬럼 순서·dtype이 메인 패널과 같은지 확인한다(`line9`가 이미 동일 스키마이지만
  concat 후 dtype이 흔들릴 수 있어 재확인한다).
- `(date, station_no, time_slot)` 중복이 0건인지 확인한다 — 하나라도 있으면 `SystemExit`.

실행:
    cd AI
    python validation/CROWD/line9-model-check/build_merged_panel.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pandas as pd

_HERE = Path(__file__).resolve().parent
AI_ROOT = _HERE.parents[2]
if str(AI_ROOT) not in sys.path:
    sys.path.insert(0, str(AI_ROOT))

from app.CROWD.pipeline.dataset import CROWD_PROCESSED, LINE9_PANEL_NAME, PANEL_NAME

TRAIN_WINDOW_START = pd.Timestamp("2024-01-01")
TRAIN_WINDOW_END = pd.Timestamp("2025-12-31")
OUT_NAME = "crowd_panel_2024_2025_line9.parquet"


def build(out_path: Path = CROWD_PROCESSED / OUT_NAME) -> pd.DataFrame:
    t0 = time.time()
    main = pd.read_parquet(CROWD_PROCESSED / PANEL_NAME)
    line9_full = pd.read_parquet(CROWD_PROCESSED / LINE9_PANEL_NAME)

    if list(line9_full.columns) != list(main.columns):
        raise SystemExit(
            f"9호선 패널 컬럼이 메인 패널과 다르다 — main={list(main.columns)}, "
            f"line9={list(line9_full.columns)}"
        )

    line9_window = line9_full[
        (line9_full["date"] >= TRAIN_WINDOW_START) & (line9_full["date"] <= TRAIN_WINDOW_END)
    ].copy()
    dropped = len(line9_full) - len(line9_window)
    print(
        f"[9호선 패널] 전체 {len(line9_full):,}행 · 학습 창 안 {len(line9_window):,}행 "
        f"· 2026-01 등 창 밖 제외 {dropped:,}행",
        flush=True,
    )

    na_alighting = int(line9_window["alighting"].isna().sum())
    na_boarding = int(line9_window["boarding"].isna().sum())
    print(
        f"[NaN 확인] 9호선(학습 창 안) alighting NaN {na_alighting:,}건 · "
        f"boarding NaN {na_boarding:,}건 — 채우거나 버리지 않는다(원칙 8)",
        flush=True,
    )

    merged = pd.concat([main, line9_window], ignore_index=True, sort=False)
    merged = merged[list(main.columns)]  # 컬럼 순서를 메인 패널에 맞춘다

    # dtype을 메인 패널에 맞춘다(concat 후 흔들릴 수 있는 컬럼만 재캐스팅)
    for col, dtype in main.dtypes.items():
        if merged[col].dtype != dtype:
            merged[col] = merged[col].astype(dtype)

    dtype_mismatch = [c for c in main.columns if merged[c].dtype != main[c].dtype]
    if dtype_mismatch:
        raise SystemExit(f"병합 후 dtype이 메인 패널과 다른 컬럼: {dtype_mismatch}")

    dup_key = ["date", "station_no", "time_slot"]
    dup_count = int(merged.duplicated(subset=dup_key).sum())
    if dup_count:
        dups = merged[merged.duplicated(subset=dup_key, keep=False)].sort_values(dup_key)
        raise SystemExit(
            f"(date, station_no, time_slot) 중복 {dup_count}건 발견 — 병합을 멈춘다.\n"
            f"{dups.head(20).to_string(index=False)}"
        )
    print("[중복 확인] (date, station_no, time_slot) 중복 0건 확인", flush=True)

    n_stations = merged["station_no"].nunique()
    date_min, date_max = merged["date"].min(), merged["date"].max()
    print(
        f"[병합 결과] {len(merged):,}행 · 역 {n_stations}개 · "
        f"날짜 {date_min.date()}~{date_max.date()}",
        flush=True,
    )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    merged.to_parquet(out_path, index=False)
    print(f"[저장] {out_path} · {time.time() - t0:.1f}s", flush=True)
    return merged


if __name__ == "__main__":
    build()
