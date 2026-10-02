"""학습 분포 모니터(`retrain/input_drift.py`)와 drift R2 규칙."""

from __future__ import annotations

import json

import numpy as np
import pandas as pd

from app.CROWD.pipeline.features import CATEGORICAL_COLS, FEATURE_SETS
from app.CROWD.pipeline.retrain import drift, input_drift

FS = "festival_selflag_d1sd_d7_resid"
DATE = "2026-10-01"


# ── 순수 함수 ──
def test_psi_same_distribution_near_zero_and_shift_large():
    rng = np.random.default_rng(0)
    base = rng.normal(0, 1, 20000)
    assert input_drift.psi(base, rng.normal(0, 1, 20000)) < 0.02
    assert input_drift.psi(base, rng.normal(1.5, 1, 20000)) > 0.25


def test_psi_ignores_nan_and_handles_constant():
    base = np.array([1.0, 2.0, 3.0, np.nan] * 50)
    assert input_drift.psi(base, base) == 0.0
    assert input_drift.psi(np.zeros(100), np.zeros(100)) == 0.0
    assert np.isnan(input_drift.psi([], [1.0]))


def test_ks_known_values():
    d, p = input_drift.ks_statistic([1, 2, 3, 4], [1, 2, 3, 4])
    assert d == 0.0 and p == 1.0
    d, p = input_drift.ks_statistic(np.arange(100), np.arange(100) + 1000)
    assert d == 1.0 and p < 1e-10
    # 손계산: x={1,2,3}, y={2,3,4} → 최대 격차 1/3
    d, _ = input_drift.ks_statistic([1, 2, 3], [2, 3, 4])
    assert abs(d - 1 / 3) < 1e-12


def test_quantiles():
    q = input_drift.quantiles(np.arange(101))
    assert q["5"] == 5.0 and q["50"] == 50.0 and q["95"] == 95.0
    assert input_drift.quantiles([np.nan])["50"] is None


def test_js_distance():
    assert input_drift.js_distance([1, 1], [2, 2]) == 0.0
    assert abs(input_drift.js_distance([1, 0], [0, 1]) - 1.0) < 1e-12


def test_level_boundaries():
    assert input_drift.level_for_psi(0.0999) == "ok"
    assert input_drift.level_for_psi(0.1) == "warn"
    assert input_drift.level_for_psi(0.2499) == "warn"
    assert input_drift.level_for_psi(0.25) == "crit"
    assert input_drift.level_for_psi(float("nan")) == "na"


def test_availability_ratio_patterns():
    frame = pd.DataFrame(
        {
            "lag1d_boarding_resid": [1.0, 1.0, np.nan, np.nan],
            "lag7d_boarding_resid": [1.0, np.nan, 1.0, np.nan],
        }
    )
    ratio = input_drift.availability_ratio(frame)
    assert ratio == {"full": 0.25, "d1_only": 0.25, "d7_only": 0.25, "no_lag": 0.25}
    assert input_drift.availability_ratio(pd.DataFrame({"x": [1, 2]}))["no_lag"] == 1.0


# ── compute_input_drift ──
def make_panel(
    n_days: int, start: str, shift: float = 0.0, lag_nan: bool = False, seed: int = 0
) -> pd.DataFrame:
    """이미 파생된 컬럼만 가진 합성 와이드 패널 — add_derived_columns는 건너뛴다(필요 입력 우회)."""
    rng = np.random.default_rng(seed)
    n_per = 40
    dates = np.repeat(pd.date_range(start, periods=n_days), n_per)
    n = len(dates)
    data = {"date": dates, "station_no": 1, "time_slot": "08-09"}
    for col in FEATURE_SETS[FS]:
        if col in CATEGORICAL_COLS:
            continue
        data[col] = rng.normal(shift, 1.0, n)
        if lag_nan and col.startswith("lag"):
            data[col] = np.nan
    data["boarding"] = rng.gamma(4.0, 50.0, n) * (1 + shift)
    data["alighting"] = rng.gamma(4.0, 50.0, n) * (1 + shift)
    return pd.DataFrame(data)


def test_compute_input_drift_stable_vs_shifted():
    train = make_panel(60, "2026-01-01")
    stable = input_drift.compute_input_drift(
        train, make_panel(20, "2026-09-12", seed=1), FS, date=DATE, window=20
    )
    assert stable["alerts"] == []
    assert stable["synthetic"] is False
    assert stable["window"] == ["2026-09-12", DATE]
    names = [f["name"] for f in stable["features"]]
    assert names == [c for c in FEATURE_SETS[FS] if c not in CATEGORICAL_COLS]
    assert all(f["level"] == "ok" for f in stable["features"])
    assert stable["targets"]["boarding"]["baseline"]["50"] > 0

    shifted = input_drift.compute_input_drift(
        train, make_panel(20, "2026-09-12", shift=2.0, seed=1), FS, date=DATE, window=20
    )
    assert any(a.startswith("TD1:") for a in shifted["alerts"])
    assert "TD3" in shifted["alerts"]
    assert all(f["level"] == "crit" for f in shifted["features"])


def test_compute_input_drift_no_lag_rise_and_window_filter():
    train = make_panel(60, "2026-01-01")
    recent = make_panel(20, "2026-09-12", lag_nan=True, seed=2)
    res = input_drift.compute_input_drift(train, recent, FS, date=DATE, window=20)
    assert "TD5" in res["alerts"]
    assert res["availability_ratio"]["recent"]["no_lag"] == 1.0
    assert all(f["level"] == "na" for f in res["features"] if f["name"].startswith("lag"))
    # 창 밖 날짜는 걸러진다
    narrow = input_drift.compute_input_drift(train, recent, FS, date=DATE, window=5)
    assert narrow["features"][0]["n_recent"] == 5 * 40


# ── CLI ──
def test_cli_missing_panel_exit_2(tmp_path):
    code = input_drift.main(
        [
            *("--train-panel", str(tmp_path / "no.parquet")),
            *("--recent-panel", str(tmp_path / "no2.parquet")),
            *("--feature-set", FS, "--date", DATE, "--window", "7"),
            *("--out-root", str(tmp_path / "out")),
        ]
    )
    assert code == 2
    assert not (tmp_path / "out").exists()


def test_cli_writes_part_json(tmp_path):
    make_panel(60, "2026-01-01").to_parquet(tmp_path / "train.parquet")
    make_panel(20, "2026-09-12", seed=1).to_parquet(tmp_path / "recent.parquet")
    code = input_drift.main(
        [
            *("--train-panel", str(tmp_path / "train.parquet")),
            *("--recent-panel", str(tmp_path / "recent.parquet")),
            *("--feature-set", FS, "--date", DATE, "--window", "20"),
            *("--out-root", str(tmp_path / "out"), "--mark-synthetic"),
        ]
    )
    assert code == 0
    body = json.loads((tmp_path / "out" / f"dt={DATE}" / "part.json").read_text(encoding="utf-8"))
    assert body["synthetic"] is True and body["feature_set"] == FS


# ── R2 ──
TODAY = pd.Timestamp("2026-10-04")


def write_part(root, day, body):
    path = root / f"dt={day:%Y-%m-%d}"
    path.mkdir(parents=True)
    (path / "part.json").write_text(json.dumps(body), encoding="utf-8")


def feats(n_crit):
    crit = [{"name": f"f{i}", "level": "crit"} for i in range(n_crit)]
    return {"features": [*crit, {"name": "ok", "level": "ok"}]}


def test_r2_positive_features_and_line_streak(tmp_path):
    dq_root = tmp_path / "dq"
    features_root = dq_root / "features"
    write_part(features_root, TODAY - pd.Timedelta(days=2), feats(2))
    write_part(features_root, TODAY - pd.Timedelta(days=1), feats(1))
    for k in range(3):
        day = TODAY - pd.Timedelta(days=k)
        write_part(dq_root, day, {"line_totals": [{"line": "2호선", "z": -3.5}]})
    res = drift.r2_input_drift(features_root, dq_root, TODAY)
    assert res["rule"] == "R2"
    assert res["features"] == ["f0", "f1"]
    assert res["lines"] == ["2호선"]


def test_r2_negative_and_missing_dirs(tmp_path):
    dq_root = tmp_path / "dq"
    features_root = dq_root / "features"
    assert drift.r2_input_drift(features_root, dq_root, TODAY) is None
    write_part(features_root, TODAY, feats(1))  # crit 1개뿐
    for k in (0, 1, 3):  # 연속 3일이 아님
        day = TODAY - pd.Timedelta(days=k)
        write_part(dq_root, day, {"line_totals": [{"line": "1호선", "z": 4}]})
    assert drift.r2_input_drift(features_root, dq_root, TODAY) is None
    # 창 밖(7일 이전) 신호는 무시
    write_part(features_root, TODAY - pd.Timedelta(days=10), feats(3))
    assert drift.r2_input_drift(features_root, dq_root, TODAY) is None


def test_evaluate_records_r2_without_request(tmp_path):
    write_part(tmp_path / "data_quality" / "features", TODAY, feats(2))
    result = drift.evaluate(TODAY, score_root=tmp_path / "score", monitoring_dir=tmp_path)
    assert result["r2"]["rule"] == "R2"
    latest = json.loads((tmp_path / "drift_latest.json").read_text(encoding="utf-8"))
    assert latest["r2"]["features"] == ["f0", "f1"]
