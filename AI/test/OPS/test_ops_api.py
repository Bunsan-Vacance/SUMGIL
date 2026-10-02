"""운영 지표 API — 합성 json으로 5개 엔드포인트의 행 수·정렬·필드·null 처리를 확인한다.

json 키는 실제 생산 코드(score.py `part.meta.json`, gate.py `gate.json`, run.py `retrain_state.json`,
crowd_panel_rebuild·replay_kafka `meta.json`)가 쓰는 키와 같게 만든다.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.ops import service

client = TestClient(app)


def _write(path: Path, doc: object, raw: str | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        raw if raw is not None else json.dumps(doc, ensure_ascii=False), encoding="utf-8"
    )


def _target(rmse: float | None, base: float | None, imp: float | None) -> dict:
    return {
        "n": 100,
        "rmse_model": rmse,
        "rmse_lookup": base,
        "mae_model": None if rmse is None else rmse / 2,
        "mae_lookup": None if base is None else base / 2,
        "improvement_rmse_pct": imp,
        "improvement_mae_pct": imp,
    }


def _score_meta(day: str, *, nan: bool = False, shift: float = 0.0) -> dict:
    b = _target(None, None, None) if nan else _target(10 + shift, 12, 16.7)
    a = _target(None, None, None) if nan else _target(8 + shift, 10, 20.0)
    return {
        "target_date": day,
        "availability": "full",
        "predictor_version": "gru_v3",
        "rows_scored": 5000,
        "missing_station_count": 3,
        "metrics": {"boarding": b, "alighting": a},
        "by_line": {
            "2호선": {"n": 3000, "boarding": b, "alighting": a},
            "1호선": {"n": 2000, "boarding": b, "alighting": a},
        },
    }


def _gate_doc(accept: bool, decided_at: str, point: float) -> dict:
    vs = {"point": point, "ci_low": point - 1.0, "ci_high": point + 1.0}
    return {
        "accept": accept,
        "reasons": [],
        "mode": "shadow",
        "window": ["2026-09-01", "2026-09-28"],
        "targets": {"boarding": {"vs_champion": vs}, "alighting": {"vs_champion": vs}},
        "decided_at": decided_at,
    }


@pytest.fixture
def paths(tmp_path: Path):
    p = service.OpsPaths(
        monitoring_dir=tmp_path / "monitoring",
        experiments_dir=tmp_path / "exp_auto",
        processed_auto_dir=tmp_path / "processed_auto",
        spark_exp_dir=tmp_path / "spark_exp",
    )
    service.set_paths_for_test(p)
    yield p
    service.set_paths_for_test(None)


@pytest.fixture
def populated(paths: service.OpsPaths) -> service.OpsPaths:
    root = paths.monitoring_dir / "score_daily"
    _write(root / "dt=2026-09-28" / "part.meta.json", _score_meta("2026-09-28"))
    _write(root / "dt=2026-09-26" / "part.meta.json", _score_meta("2026-09-26", shift=1.0))
    _write(root / "dt=2026-09-27" / "part.meta.json", _score_meta("2026-09-27", nan=True))
    _write(
        paths.monitoring_dir / "score_shadow" / "auto_r2" / "dt=2026-09-28" / "part.meta.json",
        _score_meta("2026-09-28", shift=-1.0),
    )
    _write(
        paths.experiments_dir / "auto_r1" / "gate.json",
        _gate_doc(True, "2026-09-20T09:00:00+09:00", 3.5),
    )
    _write(
        paths.experiments_dir / "auto_r2" / "gate.json",
        _gate_doc(False, "2026-09-27T09:00:00+09:00", 0.2),
    )
    _write(
        paths.monitoring_dir / "shadow_candidates.json",
        {"candidates": [{"artifact": "auto_r1", "registered_at": "2026-09-20T09:01:00+09:00"}]},
    )
    _write(
        paths.monitoring_dir / "retrain_state.json",
        {
            "runs": [
                {
                    "run": "r1",
                    "started_at": "2026-09-20T08:00:00+09:00",
                    "finished_at": "2026-09-20T09:00:00+09:00",
                    "status": "ok",
                    "exit_code": 0,
                    "steps": [
                        {"step": "panel", "rc": 0, "sec": 12.5, "detail": {}},
                        {"step": "gate", "rc": 0, "sec": 30.0, "detail": {}},
                    ],
                },
                {
                    "run": "r2",
                    "started_at": "2026-09-27T08:00:00+09:00",
                    "status": "failed",
                    "exit_code": 1,
                    "steps": [{"step": "panel", "rc": 1, "sec": 3.0, "detail": {}}],
                },
            ]
        },
    )
    _write(
        paths.processed_auto_dir / "meta.json",
        {
            "run": "p1",
            "input_partitions": 270,
            "new_rows": 100,
            "panel_rows": 900000,
            "duplicate_keys": {"new": 0, "final": 0},
            "verify": {"passed": True, "max_abs_err": 0.0, "rows_match": True},
            "elapsed_sec": 42.5,
            "peak_rss_mb": 1500.0,
            "spark": {"cores": "2", "driver_memory": "2g"},
            "generated_at": "2026-09-30T10:00:00+09:00",
        },
    )
    _write(
        paths.spark_exp_dir / "replay_20260929-0900" / "meta.json",
        {
            "topic": "t",
            "events_written": 777,
            "elapsed_sec": 5.0,
            "spark": {"cores": "2", "driver_memory": "1g"},
        },
    )
    os.utime(paths.spark_exp_dir / "replay_20260929-0900" / "meta.json", (1.7e9, 1.7e9))
    return paths


def test_score_daily_sorted_and_null(populated) -> None:
    res = client.get("/ops/score-daily", params={"days": 30})
    assert res.status_code == 200
    rows = res.json()
    assert [r["date"] for r in rows] == ["2026-09-26", "2026-09-27", "2026-09-28"]
    assert rows[0]["boarding_rmse_model"] == 11.0
    assert rows[0]["source"] == "champion"
    assert rows[0]["availability"] == "full"
    assert rows[0]["rows_scored"] == 5000
    nan_row = rows[1]
    assert nan_row["boarding_rmse_model"] is None
    assert nan_row["alighting_improvement_rmse_pct"] is None
    assert nan_row["rows_scored"] == 5000


def test_score_daily_days_limits_to_recent(populated) -> None:
    rows = client.get("/ops/score-daily", params={"days": 2}).json()
    assert [r["date"] for r in rows] == ["2026-09-27", "2026-09-28"]


def test_score_daily_shadow_source(populated) -> None:
    rows = client.get("/ops/score-daily", params={"source": "shadow:auto_r2"}).json()
    assert len(rows) == 1
    assert rows[0]["source"] == "shadow:auto_r2"
    assert rows[0]["boarding_rmse_model"] == 9.0
    assert client.get("/ops/score-daily", params={"source": "shadow:nope"}).json() == []


@pytest.mark.parametrize("source", ["shadow:../x", "foo", "shadow:"])
def test_score_daily_rejects_bad_source(populated, source: str) -> None:
    assert client.get("/ops/score-daily", params={"source": source}).status_code == 422


def test_score_by_line_flattened(populated) -> None:
    rows = client.get("/ops/score-daily/by-line", params={"days": 30}).json()
    assert len(rows) == 6  # 3일 x 2개 노선
    assert [(r["date"], r["line"]) for r in rows[:2]] == [
        ("2026-09-26", "1호선"),
        ("2026-09-26", "2호선"),
    ]
    assert rows[0]["n"] == 2000
    assert rows[0]["boarding_improvement_rmse_pct"] == 16.7
    assert rows[2]["boarding_rmse_model"] is None  # 결측일 노선 행
    assert set(rows[0]) == {
        "date", "line", "n", "boarding_rmse_model", "boarding_improvement_rmse_pct",
        "alighting_rmse_model", "alighting_improvement_rmse_pct",
    }  # fmt: skip


def test_gate_rows_sorted_and_registered(populated) -> None:
    rows = client.get("/ops/gate", params={"limit": 10}).json()
    assert [r["run"] for r in rows] == ["r2", "r1"]  # decided_at 내림차순
    r2, r1 = rows
    assert (r2["accepted"], r2["registered_shadow"]) == (False, False)
    assert (r1["accepted"], r1["registered_shadow"]) == (True, True)
    assert r1["mode"] == "shadow"
    assert (r1["window_start"], r1["window_end"]) == ("2026-09-01", "2026-09-28")
    assert r1["boarding_point_pp"] == 3.5
    assert r1["boarding_ci_low_pp"] == 2.5
    assert len(client.get("/ops/gate", params={"limit": 1}).json()) == 1


def test_jobs_expanded_by_step(populated) -> None:
    rows = client.get("/ops/jobs", params={"limit": 20}).json()
    assert [(r["run_id"], r["step"]) for r in rows] == [
        ("r2", "panel"),
        ("r1", "panel"),
        ("r1", "gate"),
    ]
    assert rows[0]["status"] == "failed"
    assert rows[0]["exit_code"] == 1
    assert rows[0]["finished_at"] is None
    assert rows[0]["step_rc"] == 1
    assert rows[2]["step_sec"] == 30.0
    assert [r["run_id"] for r in client.get("/ops/jobs", params={"limit": 1}).json()] == ["r2"]


def test_spark_runs_both_kinds(populated) -> None:
    rows = client.get("/ops/spark-runs").json()
    assert [r["job"] for r in rows] == ["panel_rebuild", "replay_kafka"]  # generated_at 내림차순
    panel, replay = rows
    assert panel["run"] == "p1"
    assert panel["rows"] == 900000
    assert panel["input_partitions"] == 270
    assert panel["verify_passed"] is True
    assert panel["verify_max_abs_err"] == 0.0
    assert (panel["cores"], panel["driver_memory"]) == ("2", "2g")
    assert panel["peak_rss_mb"] == 1500.0
    assert panel["path"] == "processed_auto/meta.json"
    assert replay["run"] == "20260929-0900"
    assert replay["rows"] == 777
    assert replay["verify_passed"] is None
    assert replay["peak_rss_mb"] is None
    assert replay["generated_at"] is not None  # 파일 mtime으로 대체


@pytest.mark.parametrize(
    "url",
    ["/ops/score-daily", "/ops/score-daily/by-line", "/ops/gate", "/ops/jobs", "/ops/spark-runs"],
)
def test_empty_dirs_return_empty_array(paths, url: str) -> None:
    res = client.get(url)
    assert res.status_code == 200
    assert res.json() == []


def test_broken_file_skipped_with_warning(populated, caplog) -> None:
    _write(
        populated.monitoring_dir / "score_daily" / "dt=2026-09-29" / "part.meta.json",
        None,
        raw="{broken",
    )
    with caplog.at_level("WARNING", logger="app.ops"):
        rows = client.get("/ops/score-daily").json()
    assert len(rows) == 3
    assert any("part.meta.json" in rec.getMessage() for rec in caplog.records)


def test_cache_and_clear(paths) -> None:
    assert client.get("/ops/score-daily").json() == []
    _write(
        paths.monitoring_dir / "score_daily" / "dt=2026-09-28" / "part.meta.json",
        _score_meta("2026-09-28"),
    )
    assert client.get("/ops/score-daily").json() == []  # 60초 캐시
    service.clear_cache()
    assert len(client.get("/ops/score-daily").json()) == 1
