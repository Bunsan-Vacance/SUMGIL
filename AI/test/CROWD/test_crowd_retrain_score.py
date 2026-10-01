"""재학습 루프 채점(`app/CROWD/pipeline/retrain/score.py`) — 합성 데이터로 규칙 하나씩 검사.

순수 pandas/numpy 로직이라 무거운 의존성 가드가 필요 없다. 네트워크·실데이터는 쓰지 않는다.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from app.CROWD.pipeline.retrain import score as sc

D = pd.Timestamp("2026-09-10")
SLOTS = ["08-09", "09-10", "10-11"]
# (역번호, 호선, 모델 오차, lookup 오차) — 승차 기준. 103은 실측에 없는 역이다.
STATIONS = [(101, "2호선", 2.0, 5.0), (102, "1호선", -4.0, -10.0), (103, "3호선", 1.0, 1.0)]
UNPREDICTED = 555
LINE9_STATION = 4126

META_ORDER = [
    "target_date",
    "scored_at",
    "prediction_path",
    "prediction_generated_at",
    "availability",
    "lag1d_available",
    "history_days_present",
    "predictor",
    "predictor_version",
    "rows_scored",
    "pred_rows_raw",
    "pred_rows_dedup",
    "line9_rows_dropped",
    "actual_rows",
    "missing_station_count",
    "missing_stations",
    "unpredicted_station_count",
    "metrics",
    "by_line",
    "excluded_candidates",
    "deploy_stamp",
]


def actual_value(station: int, slot_idx: int, target: str) -> float:
    base = 100.0 + station % 100 + 10 * slot_idx
    return base if target == "boarding" else base / 2


def make_pred(date: pd.Timestamp = D) -> pd.DataFrame:
    rows = []
    for station, line, err_m, err_l in STATIONS:
        for si, slot in enumerate(SLOTS):
            for direction in ("up", "down"):
                for half in (0, 30):
                    b, a = actual_value(station, si, "boarding"), actual_value(
                        station, si, "alighting"
                    )
                    rows.append(
                        {
                            "date": date,
                            "station_no": station,
                            "station_name": f"s{station}",
                            "line": line,
                            "direction": direction,
                            "time_slot_30min": f"{slot}:{half}",
                            "time_slot": slot,
                            "boarding_pred": b + err_m,
                            "alighting_pred": a + 1.0,
                            "pred_source": "model",
                            "boarding_lookup": b + err_l,
                            "alighting_lookup": a + 3.0,
                        }
                    )
    for si, slot in enumerate(SLOTS):
        for direction in ("up", "down"):
            for half in (0, 30):
                rows.append(
                    {
                        "date": date,
                        "station_no": LINE9_STATION,
                        "station_name": "l9",
                        "line": "9호선",
                        "direction": direction,
                        "time_slot_30min": f"{slot}:{half}",
                        "time_slot": slot,
                        "boarding_pred": 50.0,
                        "alighting_pred": 50.0,
                        "pred_source": "lookup_line9",
                        "boarding_lookup": 50.0,
                        "alighting_lookup": 50.0,
                    }
                )
    return pd.DataFrame(rows)


def make_recent_long(dates: list[pd.Timestamp] | None = None) -> pd.DataFrame:
    rows = []
    for date in dates or [D]:
        for station in (101, 102, UNPREDICTED):
            for si, slot in enumerate(SLOTS):
                for target in ("boarding", "alighting"):
                    rows.append(
                        {
                            "date": date,
                            "line": "x",
                            "station_no": station,
                            "station_name": f"s{station}",
                            "direction": target,
                            "passengers": actual_value(station, si, target),
                            "time_slot": slot,
                        }
                    )
    return pd.DataFrame(rows)


def make_meta(**over) -> dict:
    meta = {
        "target_date": f"{D:%Y-%m-%d}",
        "in_panel": False,
        "history_days_present": 7,
        "lag1d_available": True,
        "lag7d_available": True,
        "availability": "full",
        "predictor": "lightgbm",
        "predictor_version": "v1",
        "predictor_override": False,
        "generated_at": "2026-09-10T23:30:00+09:00",
    }
    meta.update(over)
    return meta


def write_pred(path: Path, meta: dict, date: pd.Timestamp = D) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    make_pred(date).to_parquet(path, index=False)
    path.with_suffix(".meta.json").write_text(json.dumps(meta), encoding="utf-8")
    return path


def serving_path(root: Path) -> Path:
    return root / "serving" / f"predictions_{D:%Y-%m-%d}.parquet"


def archive_path(root: Path, gen: str) -> Path:
    return (
        root / "archive" / f"dt={D:%Y-%m-%d}" / f"gen={gen}" / f"predictions_{D:%Y-%m-%d}.parquet"
    )


def run_one(root: Path, recent_long, **kw) -> dict:
    return sc.score_target_date(
        D,
        serving_dir=root / "serving",
        archive_dir=root / "archive",
        recent_long=recent_long,
        out_root=root / "score",
        **kw,
    )


# ── 전처리·지표 ──
def test_prepare_predictions_dedup_and_line9_dropped():
    pred = make_pred()
    prepared, stats = sc.prepare_predictions(pred)
    assert stats["rows_raw"] == len(pred) == 48
    assert stats["line9_rows_dropped"] == 12
    assert stats["rows_dedup"] == len(prepared) == 9
    assert LINE9_STATION not in set(prepared["station_no"])
    assert not prepared.duplicated(sc.KEY).any()


def test_prepare_actuals_pivots_to_one_row_per_key():
    long = make_recent_long([D, D - pd.Timedelta(days=1)])
    actuals = sc.prepare_actuals(long, D)
    assert len(actuals) == 3 * 3
    assert set(actuals.columns) == {*sc.KEY, "boarding_actual", "alighting_actual"}
    assert actuals["station_no"].dtype == np.int64


def test_score_day_missing_unpredicted_and_metrics():
    prepared, _ = sc.prepare_predictions(make_pred())
    actuals = sc.prepare_actuals(make_recent_long(), D)
    rows, summary = sc.score_day(prepared, actuals, make_meta())
    assert summary["missing_stations"] == [103]
    assert summary["missing_station_count"] == 1
    assert summary["unpredicted_station_count"] == 1
    assert summary["rows_scored"] == len(rows) == 6
    assert (rows["availability"] == "full").all()

    boarding = summary["metrics"]["boarding"]
    assert boarding["rmse_model"] == pytest.approx(np.sqrt((3 * 4 + 3 * 16) / 6))
    assert boarding["mae_model"] == pytest.approx(3.0)
    assert boarding["rmse_lookup"] == pytest.approx(np.sqrt((3 * 25 + 3 * 100) / 6))
    assert boarding["mae_lookup"] == pytest.approx(7.5)
    assert boarding["improvement_rmse_pct"] == pytest.approx(
        (1 - np.sqrt(10) / np.sqrt(62.5)) * 100
    )
    assert boarding["improvement_mae_pct"] == pytest.approx((1 - 3.0 / 7.5) * 100)

    alighting = summary["metrics"]["alighting"]
    assert alighting["rmse_model"] == pytest.approx(1.0)
    assert alighting["rmse_lookup"] == pytest.approx(3.0)
    assert alighting["improvement_rmse_pct"] == pytest.approx((1 - 1 / 3) * 100)

    assert summary["by_line"]["2호선"]["boarding"]["rmse_model"] == pytest.approx(2.0)
    assert summary["by_line"]["1호선"]["n"] == 3
    assert rows["boarding_err"].iloc[0] in (2.0, -4.0)


def test_metrics_for_empty_frame_is_nan():
    empty = pd.DataFrame(
        columns=[f"{t}_{k}" for t in sc.TARGETS for k in ("actual", "pred", "lookup")]
    )
    m = sc.metrics_for(empty)
    assert m["boarding"]["n"] == 0
    assert np.isnan(m["boarding"]["improvement_rmse_pct"])


# ── 누수 가드 ──
@pytest.mark.parametrize(
    ("over", "reasons"),
    [
        ({}, []),
        ({"in_panel": True}, ["in_panel"]),
        ({"predictor_override": True}, ["predictor_override"]),
        ({"generated_at": "2026-09-11T00:30:00+09:00"}, ["generated_after_cutoff"]),
        ({"generated_at": "2026-09-10T23:30:00+09:00"}, []),
        # D+1 00:30 KST == D 15:30 UTC → 탈락, D 14:30 UTC(23:30 KST)는 통과
        ({"generated_at": "2026-09-10T15:30:00+00:00"}, ["generated_after_cutoff"]),
        ({"generated_at": "2026-09-10T14:30:00+00:00"}, []),
        # tz가 없으면 서울 시각으로 본다
        ({"generated_at": "2026-09-10T23:30:00"}, []),
        ({"generated_at": "2026-09-11T00:00:00"}, ["generated_after_cutoff"]),
    ],
)
def test_leak_guard_reasons(over, reasons):
    assert sc.leak_guard_reasons(make_meta(**over), D) == reasons


def test_guard_excluded_status_and_reasons(tmp_path):
    write_pred(serving_path(tmp_path), make_meta(in_panel=True))
    result = run_one(tmp_path, make_recent_long())
    assert result["status"] == "guard_excluded"
    assert "in_panel" in result["detail"]
    assert not (tmp_path / "score").exists()


def test_override_excluded(tmp_path):
    write_pred(serving_path(tmp_path), make_meta(predictor_override=True))
    assert run_one(tmp_path, make_recent_long())["status"] == "guard_excluded"


def test_generated_after_cutoff_excluded_and_passing_kept(tmp_path):
    late = write_pred(
        archive_path(tmp_path, "late"), make_meta(generated_at="2026-09-11T00:30:00+09:00")
    )
    ok = write_pred(
        archive_path(tmp_path, "ok"), make_meta(generated_at="2026-09-10T23:30:00+09:00")
    )
    path, meta, excluded = sc.select_prediction(D, tmp_path / "serving", tmp_path / "archive")
    assert path == ok
    assert [e["path"] for e in excluded] == [str(late)]
    assert excluded[0]["reasons"] == ["generated_after_cutoff"]
    assert meta["generated_at"] == "2026-09-10T23:30:00+09:00"


def test_meta_missing_excluded(tmp_path):
    path = serving_path(tmp_path)
    path.parent.mkdir(parents=True)
    make_pred().to_parquet(path, index=False)
    chosen, _, excluded = sc.select_prediction(D, tmp_path / "serving", tmp_path / "archive")
    assert chosen is None
    assert excluded[0]["reasons"] == ["meta_missing"]


def test_archive_with_later_generated_at_preferred_over_serving(tmp_path):
    write_pred(
        serving_path(tmp_path),
        make_meta(generated_at="2026-09-10T20:00:00+09:00", predictor_version="serving"),
    )
    arch = write_pred(
        archive_path(tmp_path, "g2"),
        make_meta(generated_at="2026-09-10T22:00:00+09:00", predictor_version="archive"),
    )
    path, meta, excluded = sc.select_prediction(D, tmp_path / "serving", tmp_path / "archive")
    assert path == arch
    assert meta["predictor_version"] == "archive"
    assert excluded == []


def test_serving_preferred_when_it_is_later(tmp_path):
    serving = write_pred(
        serving_path(tmp_path),
        make_meta(generated_at="2026-09-10T22:00:00+09:00", predictor_version="serving"),
    )
    write_pred(
        archive_path(tmp_path, "g1"),
        make_meta(generated_at="2026-09-10T20:00:00+09:00", predictor_version="archive"),
    )
    path, _, _ = sc.select_prediction(D, tmp_path / "serving", tmp_path / "archive")
    assert path == serving


# ── 채점 실행 ──
def test_score_target_date_outputs_and_meta_order(tmp_path):
    write_pred(serving_path(tmp_path), make_meta(availability="d1_only"))
    result = run_one(tmp_path, make_recent_long())
    assert result["status"] == "scored"

    out_dir = tmp_path / "score" / "dt=2026-09-10"
    rows = pd.read_parquet(out_dir / "part.parquet")
    assert "availability" in rows.columns
    assert (rows["availability"] == "d1_only").all()
    assert len(rows) == 6

    meta = json.loads((out_dir / "part.meta.json").read_text(encoding="utf-8"))
    assert list(meta) == META_ORDER
    assert meta["missing_stations"] == [103]
    assert meta["pred_rows_raw"] == 48
    assert meta["pred_rows_dedup"] == 9
    assert meta["line9_rows_dropped"] == 12
    assert meta["deploy_stamp"] is None or isinstance(meta["deploy_stamp"], dict)
    assert not list(out_dir.glob("*.tmp"))


def test_run_idempotent_and_force(tmp_path):
    write_pred(serving_path(tmp_path), make_meta())
    long = make_recent_long()
    kw = {
        "serving_dir": tmp_path / "serving",
        "archive_dir": tmp_path / "archive",
        "recent_long": long,
        "out_root": tmp_path / "score",
    }
    assert sc.run([D], **kw)[0]["status"] == "scored"
    assert sc.run([D], **kw)[0]["status"] == "exists"
    assert sc.run([D], force=True, **kw)[0]["status"] == "scored"


def test_no_prediction_and_no_actuals(tmp_path):
    assert run_one(tmp_path, make_recent_long())["status"] == "no_prediction"
    write_pred(serving_path(tmp_path), make_meta())
    assert run_one(tmp_path, None)["status"] == "no_actuals"
    other_day = make_recent_long([D - pd.Timedelta(days=1)])
    assert run_one(tmp_path, other_day)["status"] == "no_actuals"


# ── CLI ──
def _main(tmp_path: Path, *extra: str) -> int:
    with pytest.raises(SystemExit) as exc:
        sc.main(
            [
                "--date",
                f"{D:%Y-%m-%d}",
                "--serving-dir",
                str(tmp_path / "serving"),
                "--archive-dir",
                str(tmp_path / "archive"),
                "--recent-long",
                str(tmp_path / "recent.parquet"),
                "--out-dir",
                str(tmp_path / "score"),
                *extra,
            ]
        )
    return exc.value.code


def test_main_exit_codes(tmp_path, capsys):
    write_pred(serving_path(tmp_path), make_meta())
    # 실측 파일이 없다 → 99
    assert _main(tmp_path) == 99
    # 다른 날짜 실측만 있다 → 99
    make_recent_long([D - pd.Timedelta(days=1)]).to_parquet(tmp_path / "recent.parquet")
    assert _main(tmp_path) == 99
    # 실측이 들어오면 채점 → 0
    make_recent_long().to_parquet(tmp_path / "recent.parquet")
    assert _main(tmp_path) == 0
    assert "[채점] 2026-09-10 → scored" in capsys.readouterr().out
    # 이미 채점됨 → exists만이라 0
    assert _main(tmp_path) == 0
