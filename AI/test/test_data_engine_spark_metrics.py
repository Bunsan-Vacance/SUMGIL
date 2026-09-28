from __future__ import annotations

import pandas as pd

from DATA_ENGINE.spark.metrics import compare_frames


def test_compare_frames_matches_identical_data():
    pdf = pd.DataFrame({"station_id": ["A", "B"], "dow": [0, 0], "value": [1.0, 2.0]})
    sdf = pdf.copy()
    result = compare_frames(pdf, sdf, key_cols=["station_id", "dow"], value_cols=["value"])
    assert result["rows_match"] is True
    assert result["rows_pandas"] == result["rows_spark"] == 2
    assert result["max_abs_err"] == 0.0


def test_compare_frames_detects_row_count_mismatch():
    pdf = pd.DataFrame({"station_id": ["A", "B"], "dow": [0, 0], "value": [1.0, 2.0]})
    sdf = pd.DataFrame({"station_id": ["A", "B", "C"], "dow": [0, 0, 0], "value": [1.0, 2.0, 3.0]})
    result = compare_frames(pdf, sdf, key_cols=["station_id", "dow"], value_cols=["value"])
    assert result["rows_match"] is False
    assert result["rows_pandas"] == 2
    assert result["rows_spark"] == 3


def test_compare_frames_reports_max_abs_err_on_common_keys_only():
    pdf = pd.DataFrame({"station_id": ["A", "B"], "dow": [0, 0], "value": [1.0, 2.0]})
    # B는 pandas에만 있고, C는 spark에만 있다 — 공통 키(A)만 비교 대상이어야 한다.
    sdf = pd.DataFrame({"station_id": ["A", "C"], "dow": [0, 0], "value": [1.5, 99.0]})
    result = compare_frames(pdf, sdf, key_cols=["station_id", "dow"], value_cols=["value"])
    assert result["rows_match"] is False
    assert result["max_abs_err"] == 0.5


def test_compare_frames_ignores_missing_value_column():
    pdf = pd.DataFrame({"station_id": ["A"], "dow": [0], "value": [1.0]})
    sdf = pd.DataFrame({"station_id": ["A"], "dow": [0], "value": [1.0]})
    result = compare_frames(
        pdf, sdf, key_cols=["station_id", "dow"], value_cols=["value", "no_such_col"]
    )
    assert result["max_abs_err"] == 0.0
