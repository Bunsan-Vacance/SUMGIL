"""line9-model-check 5단계 — 1~8호선 드리프트 측정(구 아티팩트 vs 병합 패널 신 아티팩트).

`SERVING_CONTRACT.md` 6절의 통지 02·03 행과 같은 형식(평균 |Δ|·중앙값·95퍼센타일·최대,
grade 변화 셀 비율, data_status 동일 여부, lookup_substituted_rows 변화)으로 낸다.

**행 정렬 주의**(`MODEL_REGISTRY.md`·`SERVING_CONTRACT.md` 5.4절) — 강동(5호선/하남선)이
(station_no, direction, time_slot_30min) 키로 중복될 수 있어 병합 전에 `date` 기준으로
그룹 내 순서를 고정해 정렬한다(두 배치가 같은 순서로 생성됐다는 가정에 기대지 않는다).

실행:
    cd AI
    python validation/CROWD/line9-model-check/drift_check.py --old <old_dir> --new <new_dir>
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

KEY = ["station_no", "direction", "time_slot_30min"]


def load(out_dir: Path, date: str) -> tuple[pd.DataFrame, dict]:
    table = pd.read_parquet(out_dir / f"predictions_{date}.parquet")
    meta = json.loads((out_dir / f"predictions_{date}.meta.json").read_text(encoding="utf-8"))
    return table, meta


def compare_date(old_dir: Path, new_dir: Path, date: str) -> dict:
    old, old_meta = load(old_dir, date)
    new, new_meta = load(new_dir, date)

    # 9호선은 두 판 모두 predict_line9_day(lookup 전용) 경로라 애초에 아티팩트 교체와 무관하다 —
    # 드리프트 비교 대상에서 뺀다(과제 지시).
    old = old[old["line"] != "9호선"].copy()
    new = new[new["line"] != "9호선"].copy()

    # 강동처럼 (station_no, direction, time_slot_30min)이 유일하지 않을 수 있어(5.4절) 그룹 내
    # 순서를 date·정렬키로 고정한 뒤 두 판을 같은 순서로 나란히 놓는다(merge가 아니라 위치 정렬).
    sort_cols = [*KEY, "line"]
    old = old.sort_values(sort_cols, kind="mergesort").reset_index(drop=True)
    new = new.sort_values(sort_cols, kind="mergesort").reset_index(drop=True)

    if len(old) != len(new):
        raise SystemExit(f"{date}: 구·신 판 행 수가 다르다 — old={len(old)}, new={len(new)}")
    key_match = (old[KEY].reset_index(drop=True) == new[KEY].reset_index(drop=True)).all(axis=1)
    if not key_match.all():
        # 완전히 같은 정렬 키를 보장 못 하면(강동 등 중복) 명시적으로 merge로 다시 정렬해 재확인한다.
        old = old.sort_values([*KEY, "line", "station_name"], kind="mergesort").reset_index(
            drop=True
        )
        new = new.sort_values([*KEY, "line", "station_name"], kind="mergesort").reset_index(
            drop=True
        )
        key_match = (old[KEY].reset_index(drop=True) == new[KEY].reset_index(drop=True)).all(axis=1)
        if not key_match.all():
            raise SystemExit(f"{date}: 정렬 후에도 행 키가 일치하지 않는다 — 수동 확인 필요")

    delta = (new["congestion_pct"] - old["congestion_pct"]).to_numpy(dtype="float64")
    abs_delta = np.abs(delta)
    finite = np.isfinite(abs_delta)

    grade_old = old["grade"].to_numpy()
    grade_new = new["grade"].to_numpy()
    both_grade_finite = pd.notna(grade_old) & pd.notna(grade_new)
    grade_changed = both_grade_finite & (grade_old != grade_new)

    status_same = (old["data_status"].to_numpy() == new["data_status"].to_numpy()).mean()

    old_sub = int((old["pred_source"] == "lookup_negative").sum())
    new_sub = int((new["pred_source"] == "lookup_negative").sum())

    return {
        "date": date,
        "rows": len(old),
        "congestion_pct_mean_abs_delta": float(np.nanmean(abs_delta[finite])),
        "congestion_pct_median_abs_delta": float(np.nanmedian(abs_delta[finite])),
        "congestion_pct_p95_abs_delta": float(np.nanpercentile(abs_delta[finite], 95)),
        "congestion_pct_max_abs_delta": float(np.nanmax(abs_delta[finite])),
        "grade_changed_pct": (
            float(grade_changed.sum() / both_grade_finite.sum() * 100)
            if both_grade_finite.sum()
            else float("nan")
        ),
        "grade_changed_cells": int(grade_changed.sum()),
        "grade_comparable_cells": int(both_grade_finite.sum()),
        "data_status_identical_pct": float(status_same * 100),
        "lookup_substituted_rows_old": old_sub,
        "lookup_substituted_rows_new": new_sub,
        "history_window_days_old": old_meta.get("history_window_days"),
        "history_window_days_new": new_meta.get("history_window_days"),
        "availability_old": old_meta.get("availability"),
        "availability_new": new_meta.get("availability"),
        "predictor_version_old": old_meta.get("predictor_version"),
        "predictor_version_new": new_meta.get("predictor_version"),
    }


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--old", required=True)
    ap.add_argument("--new", required=True)
    ap.add_argument("--dates", nargs="+", default=["2026-09-13", "2026-09-20"])
    args = ap.parse_args(argv)

    old_dir, new_dir = Path(args.old), Path(args.new)
    rows = [compare_date(old_dir, new_dir, d) for d in args.dates]
    result = pd.DataFrame(rows)
    with pd.option_context("display.max_columns", None, "display.width", 200):
        print(result.round(4).to_string(index=False))


if __name__ == "__main__":
    main()
