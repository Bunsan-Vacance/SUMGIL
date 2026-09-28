"""app/CROWD/pipeline/{topology,lookup,features}.py — 승격된 순수 함수."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.CROWD.pipeline.features import (
    FEATURE_SETS,
    REALTIME_COLS,
    SLOT_ORDER,
    add_derived_columns,
    build_matrix,
    mask_realtime_columns,
    needs_derived_columns,
)
from app.CROWD.pipeline.lookup import DayTypeLookupBaseline
from app.CROWD.pipeline.topology import expand_stations, load_topology, resolve_segments


# ── topology ──
def test_expand_stations_handles_range_and_literals():
    assert expand_stations([1, {"range": [5, 7]}, 9]) == [1, 5, 6, 7, 9]


def test_resolve_segments_reports_missing_and_keeps_order():
    topo = [{"line": "L", "segment": "본선", "stations": [{"range": [1, 4]}]}]
    resolved, gaps = resolve_segments(topo, {1, 2, 4})
    assert resolved[0]["stations"] == [1, 2, 4]
    assert gaps.iloc[0]["missing"] == [3]


def test_default_topology_file_loads_and_expands():
    segments = load_topology()
    assert any(s["line"] == "2호선" and s.get("circular") for s in segments)
    resolved, _ = resolve_segments(segments, set(range(100, 5000)))
    assert all(len(s["stations"]) >= 2 for s in resolved)


# ── lookup ──
def _panel(days=10):
    rows = []
    for d in range(days):
        date = pd.Timestamp("2025-01-01") + pd.Timedelta(days=d)
        for s in (1, 2, 3):
            for i, slot in enumerate(SLOT_ORDER[:3]):
                rows.append(
                    {
                        "date": date,
                        "station_no": s,
                        "station_name": {1: "A", 2: "B", 3: "A"}[s],
                        "line": {1: "L1", 2: "L1", 3: "L2"}[s],
                        "time_slot": slot,
                        "day_type": "평일" if date.dayofweek < 5 else "토요일",
                        "boarding": float(10 * s + i + d % 3),
                        "alighting": float(5 * s + i),
                        "game_count": 0,
                        "festival_count": 0,
                        "festival_short_count": 0,
                        "festival_long_count": 0,
                        "festival_min_duration_days": np.nan,
                        "temp_c": 10.0,
                        "precip_mm": 0.0,
                        "wind_ms": 1.0,
                        "humidity_pct": 50.0,
                        "snow_cm": 0.0,
                    }
                )
    return pd.DataFrame(rows)


def test_lookup_predict_matches_group_mean_and_nan_for_unseen():
    panel = _panel()
    lookup = DayTypeLookupBaseline().fit(panel)
    pred = lookup.predict(panel)
    expected = panel.groupby(["day_type", "station_no", "time_slot"])["boarding"].transform("mean")
    np.testing.assert_allclose(pred["boarding"].to_numpy(), expected.to_numpy())
    unseen = panel.head(1).assign(day_type="휴일")
    assert lookup.predict(unseen)["boarding"].isna().all()


def test_lookup_residuals_preserve_index_and_sum_to_zero_in_sample():
    panel = _panel()
    lookup = DayTypeLookupBaseline().fit(panel)
    resid = lookup.residuals(panel)
    assert list(resid.index) == list(panel.index)
    grouped = panel.assign(r=resid["boarding_resid"]).groupby(
        ["day_type", "station_no", "time_slot"]
    )["r"]
    assert np.allclose(grouped.sum().to_numpy(), 0.0)


def test_lookup_save_load_roundtrip(tmp_path):
    panel = _panel()
    lookup = DayTypeLookupBaseline().fit(panel)
    path = lookup.save(tmp_path / "lookup.parquet")
    loaded = DayTypeLookupBaseline.load(path)
    pd.testing.assert_frame_equal(loaded.predict(panel), lookup.predict(panel))


# ── features ──
def test_add_derived_columns_produces_every_registered_column():
    panel = _panel()
    lookup = DayTypeLookupBaseline().fit(panel)
    segments = [{"line": "L1", "segment": "본선", "stations": [1, 2]}]
    out = add_derived_columns(panel, lookup, segments)
    assert len(out) == len(panel)
    for cols in FEATURE_SETS.values():
        missing = [c for c in cols if c not in out.columns]
        assert not missing, missing
    # 환승 노드: 역명 A가 1(L1)·3(L2) 두 노드 → 서로 xfer
    r = out.set_index(["date", "station_no", "time_slot"])
    d = pd.Timestamp("2025-01-02")
    assert r.loc[(d, 1, "06-07"), "nb_xfer_boarding_resid"] == pytest.approx(
        r.loc[(d, 3, "06-07"), "boarding_resid"]
    )
    # 전날 시차: 1월 2일의 lag1d = 1월 1일 잔차
    assert r.loc[(d, 2, "06-07"), "lag1d_boarding_resid"] == pytest.approx(
        r.loc[(pd.Timestamp("2025-01-01"), 2, "06-07"), "boarding_resid"]
    )
    # 첫날의 전날은 없다 → NaN (0으로 채우지 않는다)
    assert np.isnan(r.loc[(pd.Timestamp("2025-01-01"), 2, "06-07"), "lag1d_boarding_resid"])


def test_build_matrix_fills_missing_realtime_columns_with_nan_and_casts_categories():
    """환승 노드가 없는 세그먼트라 `nb_xfer_*`(REALTIME_COLS)가 아예 안 만들어지는 경우 —
    이런 결손만 조용히 NaN으로 채운다(197 C부)."""
    panel = _panel().assign(station_name=lambda d: d["station_no"].map({1: "A", 2: "B", 3: "C"}))
    lookup = DayTypeLookupBaseline().fit(panel)
    segments = [{"line": "L1", "segment": "본선", "stations": [1, 2]}]
    out = add_derived_columns(panel, lookup, segments)
    assert "nb_xfer_boarding_resid" not in out.columns

    X = build_matrix(out, "festival_all_derived_resid")
    assert list(X.columns) == FEATURE_SETS["festival_all_derived_resid"]
    assert X["nb_xfer_boarding_resid"].isna().all()
    assert str(X["station_no"].dtype) == "category"


def test_build_matrix_raises_when_non_realtime_column_is_missing():
    """파생이 아직 안 붙은 프레임으로 파생 세트를 요청하면 조용히 NaN을 채우지 않고 바로
    실패한다 — 이게 197 C부 전의 실제 구멍이었다(`reindex`가 전 컬럼에 관대했다)."""
    panel = _panel()
    with pytest.raises(KeyError, match="lag1d_boarding_resid"):
        build_matrix(panel, "festival_selflag_d1d7_resid")


def test_mask_realtime_columns_only_touches_realtime_set():
    panel = _panel()
    lookup = DayTypeLookupBaseline().fit(panel)
    out = add_derived_columns(panel, lookup, [{"stations": [1, 2]}])
    X = build_matrix(out, "festival_all_derived_resid")
    masked = mask_realtime_columns(X)
    assert masked[REALTIME_COLS].isna().all().all()
    kept = [c for c in X.columns if c not in REALTIME_COLS]
    pd.testing.assert_frame_equal(masked[kept], X[kept])


def test_needs_derived_columns():
    assert needs_derived_columns(FEATURE_SETS["festival_lag_d7_resid"])
    assert not needs_derived_columns(FEATURE_SETS["events_station_time_festival"])
