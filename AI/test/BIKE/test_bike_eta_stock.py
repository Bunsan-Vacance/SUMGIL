"""BIKE 실시간 ETA 재고 API - 합성 avg 표 + 합성 실시간 재고 파일로 검증한다.

`test_bike_api.py`와 같은 패턴(TestClient + service._store/get_store monkeypatch)을
쓰되, 실시간 재고 스토어(service._live_store/get_live_stock_store)도 같은 방식으로
바꿔치기한다. dow_type/time_slot은 실제 날짜(2026-09-14 월요일, 공휴일 아님)로
고정해 테스트가 실행 시점에 흔들리지 않게 한다.
"""

from __future__ import annotations

import json
from datetime import datetime

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.BIKE import service
from app.main import app

client = TestClient(app)

# service.py/calendar.py는 의도적으로 naive datetime을 쓴다(서버=KST 가정) - 여기서 tzinfo를
# 붙이면 holiday_calendar.parquet(naive)과 비교가 깨진다.
# NOW: 월요일, 공휴일 아님 -> dow_type 0, slot 28
# SATURDAY_NIGHT: 토요일(공휴일) -> dow_type 1, slot 47 / SUNDAY_MORNING: 그 20분 뒤 -> dow_type 2, slot 0
NOW = datetime(2026, 9, 14, 14, 0)  # noqa: DTZ001
SATURDAY_NIGHT = datetime(2026, 9, 19, 23, 50)  # noqa: DTZ001
SUNDAY_MORNING = datetime(2026, 9, 20, 0, 10)  # noqa: DTZ001


def _avg_table() -> pd.DataFrame:
    rows = [
        {
            "rental_id": "ST-1",
            "dow_type": 0,
            "time_slot": 28,
            "exp_bikes": 10.0,
            "p_empty": 0.05,
            "p_full": 0.10,
            "source": "avg",
        },
        {
            "rental_id": "ST-1",
            "dow_type": 0,
            "time_slot": 29,
            "exp_bikes": 13.0,
            "p_empty": 0.02,
            "p_full": 0.20,
            "source": "avg",
        },
        {
            "rental_id": "ST-1",
            "dow_type": 0,
            "time_slot": 30,
            "exp_bikes": np.nan,
            "p_empty": None,
            "p_full": None,
            "source": "avg",
        },
        {
            "rental_id": "ST-1",
            "dow_type": 1,
            "time_slot": 47,
            "exp_bikes": 6.0,
            "p_empty": 0.10,
            "p_full": 0.05,
            "source": "avg",
        },
        {
            "rental_id": "ST-1",
            "dow_type": 2,
            "time_slot": 0,
            "exp_bikes": 9.0,
            "p_empty": 0.03,
            "p_full": 0.08,
            "source": "avg",
        },
    ]
    return pd.DataFrame(rows)


def _live_table(current_stock: int, updated_at: datetime) -> pd.DataFrame:
    return pd.DataFrame(
        [{"rental_id": "ST-1", "current_stock": current_stock, "updated_at": updated_at}]
    )


@pytest.fixture
def avg_dir(tmp_path, monkeypatch):
    path = tmp_path / "bike_stock_pred_20260914.parquet"
    _avg_table().to_parquet(path, index=False)
    path.with_suffix(".meta.json").write_text(
        json.dumps({"generated_at": "2026-09-14T00:00:00+09:00", "source": "avg"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(service, "_store", service.BikeStockStore(tmp_path))
    monkeypatch.setattr(service, "get_store", lambda settings=None: service._store)
    return tmp_path


@pytest.fixture
def live_dir(tmp_path, monkeypatch):
    def _write(current_stock: int, updated_at: datetime | None = None) -> None:
        if updated_at is None:
            updated_at = NOW
        path = tmp_path / "latest_stock.parquet"
        _live_table(current_stock, updated_at).to_parquet(path, index=False)
        monkeypatch.setattr(service, "_live_store", service.LiveStockStore(path))
        monkeypatch.setattr(
            service, "get_live_stock_store", lambda settings=None: service._live_store
        )

    return _write


def test_happy_path_predicted_stock_and_probabilities(avg_dir, live_dir):
    live_dir(current_stock=5, updated_at=NOW)
    result = service.predict_eta_stock("ST-1", eta_minutes=45, now=NOW)
    assert result["current_stock"] == 5
    assert result["predicted_stock"] == 8.0  # 5 + (13.0 - 10.0)
    assert result["p_empty"] == 0.02
    assert result["p_full"] == 0.20
    assert result["arrival_dow_type"] == 0
    assert result["arrival_time_slot"] == 29


def test_predicted_stock_clips_at_zero_not_negative(tmp_path, monkeypatch, live_dir):
    # 현재고 0에, 도착 슬롯 exp_bikes가 현재 슬롯보다 훨씬 낮은(큰 음수 delta) 표를
    # 별도로 준비해서 clip(0)이 실제로 발동하는지 확인한다.
    big_drop = _avg_table().copy()
    big_drop.loc[big_drop["time_slot"] == 29, "exp_bikes"] = -50.0
    path = tmp_path / "bike_stock_pred_20260914.parquet"
    big_drop.to_parquet(path, index=False)
    monkeypatch.setattr(service, "_store", service.BikeStockStore(tmp_path))
    monkeypatch.setattr(service, "get_store", lambda settings=None: service._store)

    live_dir(current_stock=0, updated_at=NOW)
    result = service.predict_eta_stock("ST-1", eta_minutes=45, now=NOW)
    assert result["predicted_stock"] == 0.0


def test_live_stock_missing_returns_404(avg_dir, tmp_path, monkeypatch):
    missing_path = tmp_path / "does_not_exist.parquet"
    monkeypatch.setattr(service, "_live_store", service.LiveStockStore(missing_path))
    monkeypatch.setattr(service, "get_live_stock_store", lambda settings=None: service._live_store)
    with pytest.raises(service.LiveStockMissing):
        service.predict_eta_stock("ST-1", eta_minutes=45, now=NOW)


def test_station_missing_from_live_file_returns_404(avg_dir, tmp_path, monkeypatch):
    path = tmp_path / "latest_stock.parquet"
    pd.DataFrame([{"rental_id": "ST-OTHER", "current_stock": 5, "updated_at": NOW}]).to_parquet(
        path, index=False
    )
    monkeypatch.setattr(service, "_live_store", service.LiveStockStore(path))
    monkeypatch.setattr(service, "get_live_stock_store", lambda settings=None: service._live_store)
    with pytest.raises(service.LiveStockMissing):
        service.predict_eta_stock("ST-1", eta_minutes=45, now=NOW)


def test_stale_live_stock_returns_404(avg_dir, live_dir):
    old_time = datetime(2020, 1, 1, 0, 0)  # noqa: DTZ001
    live_dir(current_stock=5, updated_at=old_time)
    with pytest.raises(service.LiveStockMissing):
        service.predict_eta_stock("ST-1", eta_minutes=45, now=NOW)


def test_avg_table_missing_returns_404(tmp_path, monkeypatch, live_dir):
    monkeypatch.setattr(service, "_store", service.BikeStockStore(tmp_path))
    monkeypatch.setattr(service, "get_store", lambda settings=None: service._store)
    live_dir(current_stock=5, updated_at=NOW)
    with pytest.raises(service.AvgDataMissing):
        service.predict_eta_stock("ST-1", eta_minutes=45, now=NOW)


def test_nan_exp_bikes_treated_as_missing(avg_dir, live_dir):
    live_dir(current_stock=5, updated_at=NOW)
    # time_slot 29(now+45min)는 정상, time_slot 30(now+90min)은 exp_bikes=NaN인 행이라
    # AvgDataMissing이 나야 한다.
    ok = service.predict_eta_stock("ST-1", eta_minutes=45, now=NOW)
    assert ok["predicted_stock"] == 8.0
    with pytest.raises(service.AvgDataMissing):
        service.predict_eta_stock("ST-1", eta_minutes=90, now=NOW)


def test_midnight_rollover_changes_dow_type(avg_dir, live_dir):
    live_dir(current_stock=4, updated_at=SATURDAY_NIGHT)
    result = service.predict_eta_stock("ST-1", eta_minutes=20, now=SATURDAY_NIGHT)
    assert result["arrival_dow_type"] == 2
    assert result["arrival_time_slot"] == 0
    assert result["predicted_stock"] == 4 + (9.0 - 6.0)


def test_http_happy_path_returns_200(avg_dir, live_dir, monkeypatch):
    live_dir(current_stock=5, updated_at=NOW)
    monkeypatch.setattr(pd.Timestamp, "now", staticmethod(lambda: pd.Timestamp(NOW)))
    # NOW=14:00 + 30분 = 14:30 -> slot 29(경계값, le=30 허용치 안)
    r = client.get("/bike/stations/ST-1/eta-stock", params={"eta_minutes": 30})
    assert r.status_code == 200
    assert r.json()["predicted_stock"] == 8.0


def test_http_missing_live_stock_returns_404(avg_dir, tmp_path, monkeypatch):
    missing_path = tmp_path / "does_not_exist.parquet"
    monkeypatch.setattr(service, "_live_store", service.LiveStockStore(missing_path))
    monkeypatch.setattr(service, "get_live_stock_store", lambda settings=None: service._live_store)
    r = client.get("/bike/stations/ST-1/eta-stock", params={"eta_minutes": 15})
    assert r.status_code == 404


def test_http_eta_minutes_out_of_range_returns_422(avg_dir, live_dir):
    live_dir(current_stock=5, updated_at=NOW)
    r = client.get("/bike/stations/ST-1/eta-stock", params={"eta_minutes": 999})
    assert r.status_code == 422
