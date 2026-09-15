"""142 1단계 — 배율표 연도 홀드아웃(`validation/CROWD/calibration-holdout/holdout.py`)의 순수 함수.

원천 parquet을 읽는 부분(연도별 재귀식·스냅샷 로딩)은 데이터가 있어야 돌아가므로 테스트하지
않고, 계수 적합·지표·분류·30분 전개처럼 입력만으로 결정되는 함수만 검사한다.
폴더명에 하이픈이 있어 일반 import가 안 되므로 파일 경로로 읽어 온다.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

AI_ROOT = Path(__file__).resolve().parents[2]
_SPEC_PATH = AI_ROOT / "validation" / "CROWD" / "calibration-holdout" / "holdout.py"


def _load_module():
    if str(AI_ROOT) not in sys.path:
        sys.path.insert(0, str(AI_ROOT))
    spec = importlib.util.spec_from_file_location("crowd_calibration_holdout", _SPEC_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


holdout = _load_module()


# ── 계수 적합 ──
def test_fit_scale_only_recovers_slope_without_intercept():
    """상수항 없는 적합은 원점을 지나는 기울기를 그대로 되찾는다."""
    frame = pd.DataFrame({"g": ["a"] * 4, "x": [1.0, 2.0, 3.0, 4.0], "y": [3.0, 6.0, 9.0, 12.0]})
    coefs = holdout.fit_linear_by_group(frame, ["g"], "x", "y", with_const=False)
    assert list(coefs.columns) == ["g", "slope", "intercept"]
    assert coefs.loc[0, "slope"] == pytest.approx(3.0)
    assert coefs.loc[0, "intercept"] == 0.0


def test_fit_scale_const_recovers_intercept_per_group():
    """상수항 적합은 그룹마다 따로 풀리고 절편을 되찾는다(146 §4-C 형태)."""
    frame = pd.DataFrame(
        {
            "g": ["a", "a", "a", "b", "b", "b"],
            "x": [1.0, 2.0, 3.0, 1.0, 2.0, 3.0],
            "y": [2.0 + 5.0, 4.0 + 5.0, 6.0 + 5.0, 3.0, 6.0, 9.0],
        }
    )
    coefs = holdout.fit_linear_by_group(frame, ["g"], "x", "y", with_const=True).set_index("g")
    assert coefs.loc["a", "slope"] == pytest.approx(2.0)
    assert coefs.loc["a", "intercept"] == pytest.approx(5.0)
    assert coefs.loc["b", "slope"] == pytest.approx(3.0)
    assert coefs.loc["b", "intercept"] == pytest.approx(0.0, abs=1e-9)


def test_fit_linear_degenerate_group_is_nan_not_zero():
    """x가 한 점뿐이면 기울기를 못 정한다 — 0으로 채우지 않는다(원칙 8)."""
    frame = pd.DataFrame({"g": ["a", "a"], "x": [2.0, 2.0], "y": [1.0, 3.0]})
    coefs = holdout.fit_linear_by_group(frame, ["g"], "x", "y", with_const=True)
    assert np.isnan(coefs.loc[0, "slope"])


def test_apply_linear_uses_group_coefficients():
    """다른 연도 raw에 그룹별 계수를 붙여 적용한다 — 행 순서·인덱스가 보존된다."""
    coefs = pd.DataFrame({"g": ["a", "b"], "slope": [2.0, 10.0], "intercept": [1.0, 0.0]})
    frame = pd.DataFrame({"g": ["b", "a", "a"], "x": [1.0, 2.0, 3.0]}, index=[5, 6, 7])
    out = holdout.apply_linear(frame, coefs, ["g"], "x")
    assert list(out.index) == [5, 6, 7]
    assert out.tolist() == pytest.approx([10.0, 5.0, 7.0])


# ── 지표 ──
def test_cell_metrics_known_values():
    truth = pd.Series([10.0, 20.0, 30.0, 40.0])
    pred = pd.Series([12.0, 18.0, 33.0, 37.0])
    m = holdout.cell_metrics(truth, pred)
    assert m["n"] == 4
    assert m["mae"] == pytest.approx(2.5)
    assert m["rmse"] == pytest.approx(np.sqrt((4 + 4 + 9 + 9) / 4))
    assert m["corr"] == pytest.approx(float(truth.corr(pred)))


def test_cell_metrics_grade_agreement_uses_50_100_thresholds():
    """등급은 90·146 기준 50/100 — 임계값을 넘나든 셀만 불일치로 센다."""
    truth = pd.Series([10.0, 60.0, 120.0, 49.0])
    pred = pd.Series([20.0, 70.0, 90.0, 51.0])  # 셋째·넷째만 등급이 갈린다
    m = holdout.cell_metrics(truth, pred)
    assert m["grade_agree_%"] == pytest.approx(50.0)


def test_cell_metrics_skips_missing_pairs_and_handles_empty():
    truth = pd.Series([10.0, np.nan, 30.0])
    pred = pd.Series([12.0, 20.0, np.nan])
    m = holdout.cell_metrics(truth, pred)
    assert m["n"] == 1
    assert m["mae"] == pytest.approx(2.0)

    empty = holdout.cell_metrics(pd.Series(dtype=float), pd.Series(dtype=float))
    assert empty["n"] == 0
    assert np.isnan(empty["mae"])


# ── 분류 · 전개 ──
def test_classify_source_continuity_three_classes():
    """불연속은 그 역에서 끝나지 않는다 — 같은 호선의 다른 역도 따로 표시한다."""
    cells = pd.DataFrame(
        {
            "station_no": [150, 151, 219, 2810],
            "line": ["1호선", "1호선", "2호선", "8호선"],
        }
    )
    out = holdout.classify_source_continuity(cells, flagged={150, 2810})
    assert out.tolist() == ["불연속 역", "불연속 호선의 다른 역", "연속", "불연속 역"]


def test_expand_to_30min_splits_hour_buckets():
    """1시간 버킷 → 30분 두 칸(첫차 `~06`은 한 칸, `24~`는 자정 이후 두 칸)."""
    raw = pd.DataFrame(
        {
            "station_no": [150, 150, 150],
            "time_slot": ["~06", "06-07", "24~"],
            "raw_mean": [1.0, 2.0, 3.0],
        }
    )
    out = holdout.expand_to_30min(raw)
    assert "time_slot" not in out.columns
    assert out["time_slot_30min"].tolist() == ["05:30", "06:00", "06:30", "00:00", "00:30"]
    assert out["raw_mean"].tolist() == [1.0, 2.0, 2.0, 3.0, 3.0]


def test_verdict_reads_total_axis_both_directions():
    """판정 문장은 계획이 사전에 고정한 두 갈래 중 하나로만 나온다."""

    def frame(pipeline_mae, pipeline_grade):
        return pd.DataFrame(
            [
                {
                    "axis": "전체",
                    "method": "pipeline",
                    "mae": pipeline_mae,
                    "grade_agree_%": pipeline_grade,
                },
                {"axis": "전체", "method": "copy_prev", "mae": 2.0, "grade_agree_%": 96.0},
            ]
        )

    assert "이긴다" in holdout.verdict(frame(1.5, 97.0))
    assert "이기지 못한다" in holdout.verdict(frame(2.5, 95.0))
    assert "갈린다" in holdout.verdict(frame(1.5, 95.0))
