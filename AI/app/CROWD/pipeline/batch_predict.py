"""배치 추론 잡 — 대상 날짜의 전 역·전 시간대 혼잡도 표를 만들어 서빙 디렉터리에 저장한다.

    패널(최근 7일 + 대상 날짜 골격)
      → Predictor.predict (lookup / lightgbm / llm 중 설정값)      승하차 예측
      → recursive_congestion (재귀식 방향 분해)                      1시간 재차인원
      → apply_calibration (배율표)                                  30분 보정 혼잡도
      → grade (임계치)                                              등급
      → data/CROWD/serving/predictions_YYYY-MM-DD.parquet + .meta.json

API는 요청 시점에 모델을 돌리지 않고 이 표만 읽는다(`AI/CLAUDE.md`: 서빙 경로는 가벼운 의존성만).
하루치는 273역 × 20슬롯 × 2방향 × 2(30분) ≈ 21,840행, 재귀식 포함 1분 안쪽.

## 대상 날짜가 패널에 있는가 없는가

- **패널에 있는 날짜**(과거 재현·검증용): 그 날 행을 그대로 창에 넣고 예측한다. 실측이 있으니
  `actual_*` 컬럼도 같이 남겨 API가 "예측 vs 실측"을 보여줄 수 있다.
- **패널에 없는 날짜**(오늘·내일 — 실제 운영): 역 × 20슬롯 골격을 만들고 달력에서 day_type, 이벤트
  테이블에서 경기·축제(없으면 0), 승하차는 NaN으로 둔다. 시차 피처는 창에 든 과거 행에서 채워진다.
  내일은 `lag1d`(전날)가 비어 `lag7d`만으로 예측되는데 이 사실을 `lag1d_available`로 표시한다.

## 결측은 상태로 노출한다

lookup 조회 실패(학습 구간에 없는 요일유형×역×시간대)와 배율표 결측(2호선 지선 방향 체계, 1~8호선
공휴일, 결번 역)은 값을 채우지 않고 `data_status`에 `no_lookup` / `no_calibration`으로 남긴다.
API가 이 셀을 "데이터 부족"으로 표시한다(원칙 8). 예측 승하차 음수는 0으로 자른다(인원).

실행:
    cd AI
    python -m app.CROWD.pipeline.batch_predict --date 2025-06-02            # 패널 안 날짜(재현)
    python -m app.CROWD.pipeline.batch_predict --date 2026-01-05 --predictor lookup
    python -m app.CROWD.pipeline.batch_predict --today --tomorrow             # 운영
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from app.core.config import get_settings
from app.CROWD.pipeline.calendar import attach_calendar, holiday_coverage_end, load_holidays
from app.CROWD.pipeline.congestion import apply_calibration, grade, recursive_congestion
from app.CROWD.pipeline.dataset import (
    CROWD_PROCESSED,
    EVENT_COUNT_COLS,
    EVENTS_NAME,
    load_panel,
    resolved_segments,
)
from app.CROWD.pipeline.features import SLOT_ORDER
from app.CROWD.pipeline.lookup import TARGETS
from app.CROWD.pipeline.predictor import Predictor, build_predictor, latest_artifact
from app.CROWD.pipeline.topology import load_capacity

CALIBRATION_NAME = "crowd_congestion_calibration.parquet"
HISTORY_DAYS = 7
EVENT_NUMERIC_COLS = ["game_attendance", "game_attendance_missing", "festival_min_duration_days"]

OUTPUT_COLS = [
    "date",
    "station_no",
    "station_name",
    "line",
    "direction",
    "time_slot_30min",
    "time_slot",
    "congestion_pct",
    "grade",
    "data_status",
    "boarding_pred",
    "alighting_pred",
    "boarding_lookup",
    "alighting_lookup",
    "actual_boarding",
    "actual_alighting",
    "train_capacity",
]


def station_table(panel: pd.DataFrame) -> pd.DataFrame:
    return panel[["station_no", "station_name", "line", "lat", "lon"]].drop_duplicates("station_no")


def build_target_skeleton(
    panel: pd.DataFrame,
    target_date: pd.Timestamp,
    holidays: pd.DataFrame,
    events: pd.DataFrame | None,
) -> pd.DataFrame:
    """대상 날짜의 (역 × 20슬롯) 골격. 패널에 그 날이 있으면 패널 행을 쓴다."""
    existing = panel[panel["date"] == target_date]
    if len(existing):
        return existing.copy()

    stations = station_table(panel)
    grid = stations.merge(pd.DataFrame({"time_slot": SLOT_ORDER}), how="cross")
    grid["date"] = target_date
    grid = attach_calendar(grid, holidays)
    for t in TARGETS:
        grid[t] = np.nan
    if events is not None:
        grid = grid.merge(events, on=["date", "station_no"], how="left")
    for col in EVENT_COUNT_COLS:
        grid[col] = grid[col].fillna(0).astype(int) if col in grid.columns else 0
    for col in EVENT_NUMERIC_COLS:
        if col not in grid.columns:
            grid[col] = np.nan
    return grid


def resolve_predictor(kind: str, panel_train: pd.DataFrame, settings) -> Predictor:
    """설정값 → 예측기. `auto`는 최신 아티팩트가 있으면 lightgbm, 없으면 lookup."""
    if kind == "auto":
        art = latest_artifact(settings.crowd_models_dir)
        kind = "lightgbm" if art else "lookup"
        if art:
            return build_predictor("lightgbm", artifact_dir=art)
    if kind == "lightgbm":
        art = latest_artifact(settings.crowd_models_dir)
        if art is None:
            raise FileNotFoundError(
                f"아티팩트가 없다: {settings.crowd_models_dir} — train.py를 먼저 돌린다"
            )
        return build_predictor("lightgbm", artifact_dir=art)
    if kind == "lookup":
        return build_predictor("lookup", train_panel=panel_train)
    if kind == "llm":
        return build_predictor(
            "llm", api_key=settings.crowd_llm_api_key, model=settings.crowd_llm_model
        )
    raise ValueError(f"알 수 없는 예측기: {kind}")


def predict_day(
    predictor: Predictor,
    panel: pd.DataFrame,
    target_date: pd.Timestamp,
    segments: list[dict],
    holidays: pd.DataFrame,
    events: pd.DataFrame | None,
) -> tuple[pd.DataFrame, dict]:
    """대상 날짜 한 날의 승하차 예측(대상 날짜 행만). 메타(lag 가용성 등)도 돌려준다."""
    target_date = pd.Timestamp(target_date).normalize()
    history = panel[
        (panel["date"] >= target_date - pd.Timedelta(days=HISTORY_DAYS))
        & (panel["date"] < target_date)
    ]
    target = build_target_skeleton(panel, target_date, holidays, events)
    window = pd.concat([history, target], ignore_index=True, sort=False)
    pred = predictor.predict(window, segments)
    pred = pred[pred["date"] == target_date].reset_index(drop=True)

    have_dates = set(history["date"].unique())
    meta = {
        "target_date": str(target_date.date()),
        "in_panel": bool(len(panel[panel["date"] == target_date])),
        "history_days_present": len(have_dates),
        "lag1d_available": (target_date - pd.Timedelta(days=1)) in have_dates,
        "lag7d_available": (target_date - pd.Timedelta(days=7)) in have_dates,
    }
    out = target[
        ["date", "station_no", "station_name", "line", "time_slot", "day_type", *TARGETS]
    ].merge(pred, on=["date", "station_no", "time_slot"], how="left")
    return out, meta


def to_congestion_table(
    predicted: pd.DataFrame,
    segments: list[dict],
    capacity: dict,
    calibration: pd.DataFrame,
    thresholds: list[float],
) -> pd.DataFrame:
    """승하차 예측 → 30분 보정 혼잡도·등급·상태 표(OUTPUT_COLS)."""
    board = predicted.copy()
    for t in TARGETS:
        board[t] = np.clip(board[f"{t}_pred"].to_numpy(dtype=float), 0.0, None)
    raw = recursive_congestion(board, segments, capacity)
    day_type = predicted[["date", "station_no", "day_type"]].drop_duplicates(["date", "station_no"])
    raw = raw.merge(day_type, on=["date", "station_no"], how="left")
    cal = apply_calibration(raw, calibration)
    cal["grade"] = grade(cal["congestion_pct_calibrated"], thresholds)

    per_row = predicted.rename(
        columns={"boarding": "actual_boarding", "alighting": "actual_alighting"}
    )[
        [
            "date",
            "station_no",
            "time_slot",
            "station_name",
            "boarding_pred",
            "alighting_pred",
            "boarding_lookup",
            "alighting_lookup",
            "actual_boarding",
            "actual_alighting",
        ]
    ]
    out = cal.merge(per_row, on=["date", "station_no", "time_slot"], how="left")
    out = out.rename(columns={"congestion_pct_calibrated": "congestion_pct"})
    status = np.where(out["boarding_lookup"].isna(), "no_lookup", "ok")
    status = np.where(out["congestion_pct"].isna() & (status == "ok"), "no_calibration", status)
    out["data_status"] = status
    return out.reindex(columns=OUTPUT_COLS)


def run(
    target_dates: list[pd.Timestamp],
    predictor_kind: str | None = None,
    out_dir: Path | None = None,
) -> list[Path]:
    settings = get_settings()
    out_dir = Path(out_dir or settings.crowd_serving_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    panel = load_panel(with_events=True)
    holidays = load_holidays()
    events_path = CROWD_PROCESSED / EVENTS_NAME
    events = pd.read_parquet(events_path) if events_path.exists() else None
    segments, gaps = resolved_segments(panel)
    capacity = load_capacity()
    calibration = pd.read_parquet(CROWD_PROCESSED / CALIBRATION_NAME)
    predictor = resolve_predictor(predictor_kind or settings.crowd_predictor, panel, settings)
    thresholds = settings.grade_thresholds

    written = []
    for d in target_dates:
        d = pd.Timestamp(d).normalize()
        predicted, meta = predict_day(predictor, panel, d, segments, holidays, events)
        table = to_congestion_table(predicted, segments, capacity, calibration, thresholds)
        path = out_dir / f"predictions_{d:%Y-%m-%d}.parquet"
        table.to_parquet(path, index=False)
        meta.update(
            {
                "predictor": predictor.kind,
                "predictor_version": predictor.version,
                "grade_thresholds": thresholds,
                "rows": len(table),
                "status_counts": table["data_status"].value_counts().to_dict(),
                "holiday_calendar_until": (
                    str(holiday_coverage_end(holidays).date())
                    if holiday_coverage_end(holidays) is not None
                    else None
                ),
                "topology_gaps": gaps.to_dict("records") if len(gaps) else [],
                "generated_at": datetime.now(UTC).astimezone().isoformat(timespec="seconds"),
            }
        )
        path.with_suffix(".meta.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=1, default=str), encoding="utf-8"
        )
        print(
            f"[배치] {d:%Y-%m-%d} → {path.name} ({len(table):,}행, {predictor.version}, "
            f"상태 {meta['status_counts']})",
            flush=True,
        )
        written.append(path)
    return written


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--date", action="append", default=[], help="YYYY-MM-DD (여러 번 가능)")
    ap.add_argument("--today", action="store_true")
    ap.add_argument("--tomorrow", action="store_true")
    ap.add_argument("--predictor", default=None, help="auto|lookup|lightgbm|llm (기본: 설정값)")
    ap.add_argument("--out-dir", default=None)
    args = ap.parse_args(argv)

    today = pd.Timestamp.now().normalize()
    dates = [pd.Timestamp(x) for x in args.date]
    if args.today:
        dates.append(today)
    if args.tomorrow:
        dates.append(today + pd.Timedelta(days=1))
    if not dates:
        ap.error("--date, --today, --tomorrow 중 하나는 필요하다")
    run(dates, args.predictor, Path(args.out_dir) if args.out_dir else None)


if __name__ == "__main__":
    main(sys.argv[1:])
