"""199 0단계 — 배율표 변형을 재는 **세 심판**. 후보는 전부 이 세 축으로만 채점한다.

## 왜 심판을 따로 만드나

배율표는 모든 혼잡도 산출의 승수다. "직관적으로 맞다"로 바꾸면 어디가 얼마나 움직였는지 아무도
모른다(199 규칙 2). 그래서 후보마다 **같은 세 축**을 재고 표로 남긴다.

| 심판 | 무엇을 보나 | 순환 참조인가 | 출처 |
| --- | --- | --- | --- |
| ① 연도 홀드아웃 | A연도 스냅샷으로 적합해 B연도를 맞히는 out-of-sample 오차·등급 | **아니다** | 142 `calibration-holdout/holdout.py` |
| ② 2025 등급 일치율 | 승하차 예측 개선이 등급까지 전달되는 폭(lookup 93.983 / 모델 95.107) | 배율은 in-sample | 90 `grade_cells.parquet` |
| ③ 기준일 `data_status` | 값을 낼 수 있는 셀이 실제로 늘었는가(커버리지) | 해당 없음 | 146 `congestion-criteria-check/diagnose.py` |

①이 유일한 성능 심판이고 ②는 **전달폭이 깨지지 않는지**를 보는 안전장치, ③은 커버리지다.
셋을 같이 보지 않으면 "셀은 늘었는데 값이 나빠졌다"를 놓친다.

## ② 는 `grade_cells`를 다시 만들지 않는다 — 배율만 갈아끼운다

90이 저장한 `grade_cells.parquet`은 2025 셀 764만 개의 **보정 혼잡도**(실측·lookup·모델 승하차를
같은 변환기에 넣은 값)다. 보정 혼잡도는 `raw × ratio`이므로 현행 배율로 나누면 `raw`가 그대로
복원되고, 거기에 변형 배율을 곱하면 그 변형의 보정 혼잡도가 **정확히** 나온다. 재귀식(판당 2~3분)
과 학습(10분대)을 변형마다 다시 돌리지 않아도 되는 이유다(`AI/CLAUDE.md` 실험 실행 효율).

한계 하나는 그대로 적어 둔다: 현행 배율이 없어 `grade_cells`에서 빠진 셀(2호선 지선·절단면 경계)은
**복원할 raw가 없어 이 심판에 들어오지 않는다.** 변형이 새로 살린 셀의 등급 품질은 ②가 아니라
①(홀드아웃 경계 셀 축)과 ③(커버리지)이 본다.

실행:
    cd AI
    python validation/CROWD/calibration-refit/refit.py --stage all
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

_HERE = Path(__file__).resolve().parent
AI_ROOT = _HERE.parents[2]
for _p in (
    str(AI_ROOT),
    str(AI_ROOT / "validation" / "CROWD" / "calibration-holdout"),
    str(AI_ROOT / "validation" / "CROWD" / "baseline-check"),
):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import holdout

from app.CROWD.pipeline.batch_predict import (
    fixed_predictor_factory,
    predict_day,
    to_congestion_table,
)
from app.CROWD.pipeline.calendar import attach_calendar, load_holidays
from app.CROWD.pipeline.congestion import bucket_day_type, grade
from app.CROWD.pipeline.dataset import CROWD_INTERIM

GRADE_CELLS = CROWD_INTERIM / "validation" / "grade_cells.parquet"
GRADE_THRESHOLDS = (50.0, 100.0)
# 146이 쓴 기준일 — 평일 1 · 토요일 1 · 공휴일 1(2025-10-03 개천절). 그대로 쓴다(전후 비교 가능).
REFERENCE_DATES = ("2025-06-02", "2025-06-07", "2025-10-03")
STATUS_ORDER = (
    "ok",
    "calibration_fallback",
    "no_lookup",
    "line1_truncated",
    "segment_truncated",
    "no_calibration",
)
CELL_KEY = ["station_no", "direction", "day_type_bucket", "time_slot_30min"]


# ── ① 연도 홀드아웃 ──
def holdout_scores(
    variants: dict[str, holdout.HoldoutVariant],
    pairs: tuple[tuple[int, int], ...] = ((2023, 2024), (2024, 2025)),
) -> pd.DataFrame:
    """변형 × 연도 쌍의 지표 long 표. `holdout.run_holdout`을 그대로 부른다(재구현 금지)."""
    frames = []
    for name, variant in variants.items():
        for fit_year, eval_year in pairs:
            metrics, _ = holdout.run_holdout(fit_year, eval_year, variant)
            frames.append(metrics.assign(안=name))
    return pd.concat(frames, ignore_index=True)


def holdout_summary(scores: pd.DataFrame) -> pd.DataFrame:
    """전체 축만 뽑아 `안 × 연도 쌍`으로 편다 — 채택 규칙이 읽는 표."""
    total = scores[(scores["axis"] == "전체") & (scores["method"] == "pipeline")]
    return (
        total.assign(쌍=total["fit_year"].astype(str) + "→" + total["eval_year"].astype(str))
        .pivot_table(index="안", columns="쌍", values=["n", "mae", "grade_agree_%"])
        .round(3)
    )


def holdout_axis(scores: pd.DataFrame, axis: str, group: str | None = None) -> pd.DataFrame:
    """한 축(호선·경계 셀 등)의 `pipeline` MAE·등급을 안 × 쌍으로 편다."""
    sub = scores[(scores["axis"] == axis) & (scores["method"] == "pipeline")]
    if group is not None:
        sub = sub[sub["group"] == group]
    sub = sub.assign(쌍=sub["fit_year"].astype(str) + "→" + sub["eval_year"].astype(str))
    return sub.pivot_table(
        index=["group", "안"], columns="쌍", values=["n", "mae", "grade_agree_%"]
    ).round(3)


# ── ② 2025 등급 일치율 ──
def load_grade_cells(base: pd.DataFrame, columns: tuple[str, ...] = ("actual", "lookup", "model")):
    """`grade_cells`에 요일유형 버킷을 붙이고 현행 배율로 나눠 `raw`를 복원한다.

    `base`는 현행(88) 배율표다. `ratio`가 0이거나 결측인 셀은 raw를 되돌릴 수 없어 뺀다
    (개수는 부르는 쪽이 표에 적는다).
    """
    cells = pd.read_parquet(GRADE_CELLS)
    cells = attach_calendar(cells, load_holidays())
    cells["day_type_bucket"] = bucket_day_type(cells["line"], cells["day_type"])
    base_key = base[["station_no", "direction", "day_type", "time_slot", "ratio"]].rename(
        columns={"day_type": "day_type_bucket", "time_slot": "time_slot_30min", "ratio": "_base"}
    )
    cells = cells.merge(base_key, on=CELL_KEY, how="left")
    usable = cells["_base"].notna() & (cells["_base"] > 0)
    dropped = int((~usable).sum())
    cells = cells[usable].reset_index(drop=True)
    for col in columns:
        cells[f"raw_{col}"] = (cells[col] / cells["_base"]).astype("float32")
    return cells, dropped


def _agreement_row(name: str, group: str, g_a, g_l, g_m) -> dict:
    changed = g_l != g_m
    return {
        "안": name,
        "구간": group,
        "셀": len(g_a),
        "lookup_일치율_%": round(float((g_l == g_a).mean() * 100), 3),
        "모델_일치율_%": round(float((g_m == g_a).mean() * 100), 3),
        "전달폭_%p": round(float(((g_m == g_a).mean() - (g_l == g_a).mean()) * 100), 3),
        "등급_바뀐_셀_%": round(float(changed.mean() * 100), 3),
        "실측_최저등급_%": round(float((g_a == 0).mean() * 100), 2),
    }


def grade_agreement(
    cells: pd.DataFrame,
    tables: dict[str, pd.DataFrame],
    thresholds: tuple[float, ...] = GRADE_THRESHOLDS,
    by_line: bool = False,
) -> pd.DataFrame:
    """변형 배율표별 2025 등급 일치율(lookup·모델)과 전달폭.

    `(raw + raw_offset) × ratio`로 세 판(실측·lookup·모델)을 다시 만들어 등급을 매긴다 —
    `congestion.apply_calibration`과 같은 식이다.

    **전달폭(모델 일치율 − lookup 일치율)이 이 심판의 핵심 수치**다. 경계 상수를 raw에 더하면
    그만큼 날짜별 변동이 희석되는데, 그 비용이 드러나는 곳이 바로 여기다 — `by_line=True`로
    호선을 갈라 보면 상수가 들어간 호선에서만 전달폭이 줄었는지 확인할 수 있다.
    """
    rows = []
    for name, table in tables.items():
        cols = ["station_no", "direction", "day_type", "time_slot", "ratio"]
        if "raw_offset" in table.columns:
            cols.append("raw_offset")
        key = table[cols].rename(
            columns={"day_type": "day_type_bucket", "time_slot": "time_slot_30min"}
        )
        merged = cells.merge(key, on=CELL_KEY, how="left")
        offset = merged["raw_offset"].fillna(0.0) if "raw_offset" in merged else 0.0
        graded = {}
        for col in ("actual", "lookup", "model"):
            graded[col] = grade((merged[f"raw_{col}"] + offset) * merged["ratio"], thresholds)
        ok = merged["ratio"].notna()
        g_a, g_l, g_m = (graded[c][ok] for c in ("actual", "lookup", "model"))
        row = _agreement_row(name, "전체", g_a, g_l, g_m)
        row["배율_없는_셀"] = int((~ok).sum())
        rows.append(row)
        if by_line:
            line = merged.loc[ok, "line"]
            for value, idx in line.groupby(line, observed=True).groups.items():
                rows.append(_agreement_row(name, str(value), g_a[idx], g_l[idx], g_m[idx]))
    return pd.DataFrame(rows)


# ── ③ 기준일 `data_status` ──
def status_distribution(
    tables: dict[str, pd.DataFrame],
    panel: pd.DataFrame,
    segments: list[dict],
    capacity: dict,
    holidays: pd.DataFrame,
    events: pd.DataFrame | None,
    thresholds: list[float],
    predictor,
    dates: tuple[str, ...] = REFERENCE_DATES,
) -> pd.DataFrame:
    """기준일 3일 × 배율표별 `data_status` 분포. 예측은 날짜마다 **한 번만** 돌린다."""
    rows = []
    for date in dates:
        day = pd.Timestamp(date)
        predicted, _ = predict_day(
            fixed_predictor_factory(predictor),
            panel,
            day,
            segments,
            holidays,
            events,
            override_kind=predictor.kind,
        )
        day_type = str(predicted["day_type"].iloc[0])
        for name, table in tables.items():
            out = to_congestion_table(predicted, segments, capacity, table, thresholds)
            counts = out["data_status"].value_counts().to_dict()
            rows.append(
                {
                    "날짜": date,
                    "요일유형": day_type,
                    "안": name,
                    "셀": len(out),
                    **{k: int(counts.get(k, 0)) for k in STATUS_ORDER},
                }
            )
    return pd.DataFrame(rows)


# ── 표 자체의 변화(규칙 1의 기록 항목) ──
def nan_by_line(tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """배율표별 `ratio` 결측 셀 수를 호선으로 갈라 센다(요일유형 3종 합)."""
    frames = {
        name: table[table["ratio"].isna()].groupby("line", observed=True).size()
        for name, table in tables.items()
    }
    return pd.DataFrame(frames).fillna(0).astype(int).reset_index()


def ratio_change(before: pd.DataFrame, after: pd.DataFrame) -> pd.DataFrame:
    """**원래 값이 있던 셀**의 배율이 얼마나 움직였는지 — 중위·90분위·최대·5% 초과 셀 수.

    새로 생긴 셀(전에 NaN)은 여기 넣지 않는다. 섞으면 "얼마나 바뀌었나"가 커버리지 증가에 묻힌다.
    """
    key = ["station_no", "direction", "day_type", "time_slot"]
    b = before[[*key, "line", "ratio"]].rename(columns={"ratio": "before"})
    a = after[[*key, "ratio"]].rename(columns={"ratio": "after"})
    if "raw_offset" in after.columns:
        a = after[[*key, "ratio", "raw_offset"]].rename(columns={"ratio": "after"})
    merged = b.merge(a, on=key, how="inner").dropna(subset=["before", "after"])
    merged = merged[merged["before"] > 0]
    rel = (merged["after"] - merged["before"]).abs() / merged["before"]
    return pd.DataFrame(
        [
            {
                "line": line,
                "셀": len(sub),
                "중위_변화_%": round(float(rel[sub.index].median() * 100), 3),
                "90분위_변화_%": round(float(rel[sub.index].quantile(0.9) * 100), 3),
                "최대_변화_%": round(float(rel[sub.index].max() * 100), 3),
                "5%_초과_셀": int((rel[sub.index] > 0.05).sum()),
            }
            for line, sub in merged.groupby("line", observed=True)
        ]
        + [
            {
                "line": "전체",
                "셀": len(merged),
                "중위_변화_%": round(float(rel.median() * 100), 3),
                "90분위_변화_%": round(float(rel.quantile(0.9) * 100), 3),
                "최대_변화_%": round(float(rel.max() * 100), 3),
                "5%_초과_셀": int((rel > 0.05).sum()),
            }
        ]
    )


def offset_share(table: pd.DataFrame) -> pd.DataFrame:
    """경계 상수가 raw에서 차지하는 비중 — **날짜별 변동이 얼마나 희석되는가**의 지표.

    `raw_offset / (raw_offset + raw_mean)`이 1에 가까울수록 그 셀의 예측은 날짜에 반응하지 않는
    정적 값에 가까워진다. 커버리지를 얻는 대가라서 규칙 1의 기록 항목으로 남긴다.
    """
    if "raw_offset" not in table.columns:
        return pd.DataFrame(columns=["line", "주입_셀", "상수_비중_중위", "상수_비중_90분위"])
    sub = table[(table["raw_offset"] > 0) & table["raw_mean"].notna()].copy()
    if sub.empty:
        return pd.DataFrame(columns=["line", "주입_셀", "상수_비중_중위", "상수_비중_90분위"])
    sub["share"] = sub["raw_offset"] / (sub["raw_offset"] + sub["raw_mean"])
    grouped = sub.groupby("line", observed=True)["share"]
    return pd.DataFrame(
        {
            "line": grouped.median().index,
            "주입_셀": grouped.size().to_numpy(),
            "상수_비중_중위": np.round(grouped.median().to_numpy(), 3),
            "상수_비중_90분위": np.round(grouped.quantile(0.9).to_numpy(), 3),
        }
    )
