"""BIKE 조회 API — 합성 bike_stock_pred 표로 엔드포인트와 결측 상태 노출을 확인한다.

배치 잡(B6, 아직 없음)은 실제 데이터가 필요해 여기서 돌리지 않는다. 서빙 디렉터리를
tmp_path로 바꿔 `service.get_store`가 그곳을 읽게 한다. CROWD와 달리 날짜별 파일이
아니라 단일 최신 표라 파일명에 날짜만 붙고(생성 시각 구분용), 조회 파라미터엔 날짜가 없다.
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.BIKE import service
from app.main import app

client = TestClient(app)


def _table() -> pd.DataFrame:
    rows = []
    for dow_type in (0, 1, 2):
        for time_slot, exp_bikes in ((16, 12.5), (36, np.nan)):
            rows.append(
                {
                    "rental_id": "ST-1",
                    "dow_type": dow_type,
                    "time_slot": time_slot,
                    "exp_bikes": exp_bikes,
                    "p_empty": None if np.isnan(exp_bikes) else 0.05,
                    "p_full": None if np.isnan(exp_bikes) else 0.1,
                    "source": "avg",
                }
            )
    return pd.DataFrame(rows)


@pytest.fixture
def serving_dir(tmp_path, monkeypatch):
    path = tmp_path / "bike_stock_pred_20260914.parquet"
    _table().to_parquet(path, index=False)
    path.with_suffix(".meta.json").write_text(
        json.dumps({"generated_at": "2026-09-14T00:00:00+09:00", "source": "avg"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(service, "_store", service.BikeStockStore(tmp_path))
    monkeypatch.setattr(service, "get_store", lambda settings=None: service._store)
    return tmp_path


def test_meta_reports_rows_and_stations(serving_dir):
    r = client.get("/bike/meta")
    assert r.status_code == 200
    body = r.json()
    assert body["rows"] == 6
    assert body["stations"] == 1
    assert body["source"] == "avg"


def test_station_stock_exposes_missing_as_null_not_zero(serving_dir):
    r = client.get("/bike/stations/ST-1/stock", params={"dow_type": 0})
    assert r.status_code == 200
    body = r.json()
    slots = {s["time_slot"]: s for s in body["slots"]}
    assert len(slots) == 2
    assert slots[16]["exp_bikes"] == 12.5 and slots[16]["p_empty"] == 0.05
    assert slots[36]["exp_bikes"] is None
    assert slots[36]["p_empty"] is None


def test_dow_type_filter(serving_dir):
    r = client.get("/bike/stations/ST-1/stock")
    assert len(r.json()["slots"]) == 6  # 3 dow_type × 2 slot
    r = client.get("/bike/stations/ST-1/stock", params={"dow_type": 1})
    assert len(r.json()["slots"]) == 2
    assert all(s["dow_type"] == 1 for s in r.json()["slots"])


def test_unknown_station_returns_empty_slots(serving_dir):
    r = client.get("/bike/stations/ST-999/stock")
    assert r.status_code == 200
    assert r.json()["slots"] == [] and r.json()["station_name"] is None


def test_missing_table_is_404(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "_store", service.BikeStockStore(tmp_path))
    monkeypatch.setattr(service, "get_store", lambda settings=None: service._store)
    r = client.get("/bike/stations/ST-1/stock")
    assert r.status_code == 404
    assert "배치" in r.json()["detail"]
