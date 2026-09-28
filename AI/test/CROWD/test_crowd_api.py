"""CROWD 조회 API — 합성 예측 표로 세 엔드포인트와 결측 상태 노출을 확인한다.

배치 잡은 실제 데이터가 필요해 여기서 돌리지 않는다. 서빙 디렉터리를 tmp_path로 바꿔
`service.get_store`가 그곳을 읽게 한다.
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.CROWD import service
from app.main import app

client = TestClient(app)
DAY = "2026-01-05"


def _table() -> pd.DataFrame:
    rows = []
    for direction in ("상선", "하선"):
        for slot, pct in (("08:00", 42.0), ("08:30", 61.5), ("09:00", np.nan)):
            rows.append(
                {
                    "date": pd.Timestamp(DAY),
                    "station_no": 222,
                    "station_name": "강남",
                    "line": "2호선",
                    "direction": direction,
                    "time_slot_30min": slot,
                    "time_slot": f"{slot[:2]}-{int(slot[:2]) + 1:02d}",
                    "congestion_pct": pct,
                    "grade": np.nan if np.isnan(pct) else float(pct >= 50),
                    "data_status": "no_calibration" if np.isnan(pct) else "ok",
                    "boarding_pred": 1000.0,
                    "alighting_pred": 900.0,
                    "pred_source": "model",
                    "boarding_lookup": 950.0,
                    "alighting_lookup": 880.0,
                    "actual_boarding": np.nan,
                    "actual_alighting": np.nan,
                    "train_capacity": 1600,
                }
            )
    return pd.DataFrame(rows)


@pytest.fixture
def serving_dir(tmp_path, monkeypatch):
    path = tmp_path / f"predictions_{DAY}.parquet"
    _table().to_parquet(path, index=False)
    path.with_suffix(".meta.json").write_text(
        json.dumps(
            {
                "predictor": "lookup",
                "predictor_version": "lookup:test",
                "lag1d_available": False,
                "grade_thresholds": [50.0, 100.0],
                "generated_at": "2026-01-05T04:00:00+09:00",
                "status_counts": {"ok": 4, "no_calibration": 2},
                "topology_gaps": [],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(service, "_store", service.PredictionStore(tmp_path))
    monkeypatch.setattr(service, "get_store", lambda settings=None: service._store)
    return tmp_path


def test_meta_lists_dates_and_predictor(serving_dir):
    r = client.get("/crowd/meta")
    assert r.status_code == 200
    body = r.json()
    assert body["available_dates"] == [DAY]
    assert body["predictor_version"] == "lookup:test"
    assert body["grade_thresholds"] == [50.0, 100.0]


def test_meta_events_coverage_fields_default_to_none_for_old_meta(serving_dir):
    """200: 이전 meta.json(키 없음)이어도 `.get`으로 안전하게 `None`이 내려가야 한다."""
    r = client.get("/crowd/meta")
    assert r.status_code == 200
    body = r.json()
    assert "events_coverage_end" in body and body["events_coverage_end"] is None
    assert "events_available" in body and body["events_available"] is None


def test_meta_events_coverage_fields_pass_through_when_present(tmp_path, monkeypatch):
    """200: meta.json에 값이 있으면 `/crowd/meta`가 그대로 내려야 한다."""
    path = tmp_path / f"predictions_{DAY}.parquet"
    _table().to_parquet(path, index=False)
    path.with_suffix(".meta.json").write_text(
        json.dumps(
            {
                "predictor": "lookup",
                "predictor_version": "lookup:test",
                "lag1d_available": False,
                "grade_thresholds": [50.0, 100.0],
                "generated_at": "2026-01-05T04:00:00+09:00",
                "status_counts": {"ok": 4, "no_calibration": 2},
                "topology_gaps": [],
                "events_coverage_end": "2026-12-31",
                "events_available": True,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(service, "_store", service.PredictionStore(tmp_path))
    monkeypatch.setattr(service, "get_store", lambda settings=None: service._store)

    r = client.get("/crowd/meta")
    assert r.status_code == 200
    body = r.json()
    assert body["events_coverage_end"] == "2026-12-31"
    assert body["events_available"] is True


def test_station_congestion_exposes_missing_as_status_not_zero(serving_dir):
    r = client.get("/crowd/stations/222/congestion", params={"date": DAY, "direction": "하선"})
    assert r.status_code == 200
    body = r.json()
    assert body["station_name"] == "강남" and body["train_capacity"] == 1600
    assert body["lag1d_available"] is False
    slots = {s["time_slot_30min"]: s for s in body["slots"]}
    assert len(slots) == 3
    assert slots["08:30"]["grade"] == 1 and slots["08:30"]["congestion_pct"] == 61.5
    assert slots["09:00"]["congestion_pct"] is None
    assert slots["09:00"]["grade"] is None
    assert slots["09:00"]["data_status"] == "no_calibration"


def test_unknown_station_returns_empty_slots(serving_dir):
    r = client.get("/crowd/stations/9999/congestion", params={"date": DAY})
    assert r.status_code == 200
    assert r.json()["slots"] == [] and r.json()["station_name"] is None


def test_missing_table_is_404(serving_dir):
    r = client.get("/crowd/stations/222/congestion", params={"date": "2026-02-01"})
    assert r.status_code == 404
    assert "배치" in r.json()["detail"]


def test_line_snapshot(serving_dir):
    r = client.get("/crowd/lines/2호선/congestion", params={"date": DAY, "time": "08:00"})
    assert r.status_code == 200
    body = r.json()
    assert {s["direction"] for s in body["stations"]} == {"상선", "하선"}
    assert all(s["congestion_pct"] == 42.0 for s in body["stations"])
