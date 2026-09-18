"""BIKE 실시간 ETA 재고 API 검증 — LightGBM(v4_weather) 서빙 연결(S15P21A104-160).

실제 LightGBM 모델은 로드하지 않는다 — `service.get_eta_predictor`를 `predict_delta()`만
구현한 가짜 객체로 monkeypatch한다(`test_bike_api.py`의 `_store`/`get_store` monkeypatch
패턴과 동일 정신). 실시간 재고·날씨 스토어는 실제 로직(`LiveStockStore`/`LiveWeatherStore`)
그대로 쓰고 파일 경로만 tmp_path로 바꿔치기한다.
"""

from __future__ import annotations

from datetime import datetime

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.BIKE import service
from app.BIKE.pipeline.predictor_eta import ModelUnavailable, round_horizon
from app.main import app

client = TestClient(app)

# service.py/calendar.py는 의도적으로 naive datetime을 쓴다(서버=KST 가정).
NOW = datetime(2026, 9, 14, 14, 0)  # noqa: DTZ001  # 월요일, 공휴일 아님 -> dow_type 0, slot 28
SATURDAY_NIGHT = datetime(2026, 9, 19, 23, 50)  # noqa: DTZ001  # 토요일(공휴일) -> dow_type 1
SUNDAY_MORNING = datetime(2026, 9, 20, 0, 10)  # noqa: DTZ001


class FakeEtaPredictor:
    """predict_delta()만 구현 — 실제 모델 대신 고정값을 돌려주며 호출 인자를 기록한다."""

    def __init__(
        self,
        net_flow: float = 0.0,
        horizon_min_used: int = 5,
        p_empty: float | None = None,
        p_full: float | None = None,
    ) -> None:
        self.net_flow = net_flow
        self.horizon_min_used = horizon_min_used
        self.p_empty = p_empty
        self.p_full = p_full
        self.calls: list[dict] = []

    def predict_delta(
        self, rental_id, current_stock, eta_minutes, now, anchor_age_minutes, weather
    ):
        self.calls.append(
            {
                "rental_id": rental_id,
                "current_stock": current_stock,
                "eta_minutes": eta_minutes,
                "now": now,
                "anchor_age_minutes": anchor_age_minutes,
                "weather": weather,
            }
        )
        return {
            "net_flow": self.net_flow,
            "horizon_min_used": self.horizon_min_used,
            "p_empty": self.p_empty,
            "p_full": self.p_full,
        }


class RaisingEtaPredictor:
    def predict_delta(self, *args, **kwargs):
        raise ModelUnavailable("모델 아티팩트 로딩 실패(테스트)")


@pytest.fixture
def fake_predictor(monkeypatch):
    def _install(
        net_flow: float = 3.0,
        horizon_min_used: int = 30,
        p_empty: float | None = None,
        p_full: float | None = None,
    ) -> FakeEtaPredictor:
        predictor = FakeEtaPredictor(
            net_flow=net_flow, horizon_min_used=horizon_min_used, p_empty=p_empty, p_full=p_full
        )
        monkeypatch.setattr(service, "_eta_predictor", predictor)
        monkeypatch.setattr(service, "get_eta_predictor", lambda settings=None: predictor)
        return predictor

    return _install


@pytest.fixture
def raising_predictor(monkeypatch):
    predictor = RaisingEtaPredictor()
    monkeypatch.setattr(service, "_eta_predictor", predictor)
    monkeypatch.setattr(service, "get_eta_predictor", lambda settings=None: predictor)
    return predictor


@pytest.fixture
def live_dir(tmp_path, monkeypatch):
    def _write(current_stock: int, updated_at: datetime | None = None) -> None:
        if updated_at is None:
            updated_at = NOW
        path = tmp_path / "latest_stock.parquet"
        pd.DataFrame(
            [{"rental_id": "ST-1", "current_stock": current_stock, "updated_at": updated_at}]
        ).to_parquet(path, index=False)
        monkeypatch.setattr(service, "_live_store", service.LiveStockStore(path))
        monkeypatch.setattr(
            service, "get_live_stock_store", lambda settings=None: service._live_store
        )

    return _write


@pytest.fixture
def weather_dir(tmp_path, monkeypatch):
    def _write(temp: float, is_rain: bool, updated_at: datetime | None = None) -> None:
        if updated_at is None:
            updated_at = NOW
        path = tmp_path / "latest_weather.parquet"
        pd.DataFrame([{"temp": temp, "is_rain": is_rain, "updated_at": updated_at}]).to_parquet(
            path, index=False
        )
        monkeypatch.setattr(service, "_live_weather_store", service.LiveWeatherStore(path))
        monkeypatch.setattr(
            service, "get_live_weather_store", lambda settings=None: service._live_weather_store
        )

    return _write


def test_round_horizon_snaps_to_nearest_trained_value():
    assert round_horizon(0) == 5
    assert round_horizon(3) == 5
    assert round_horizon(17) == 15
    assert round_horizon(23) == 30  # 15과 30 사이 정중앙(22.5)보다 위
    assert round_horizon(30) == 30
    assert round_horizon(120) == 30  # 30분 초과는 전부 30으로 근사
    assert round_horizon(1440) == 30


def test_happy_path_uses_predictor_net_flow(fake_predictor, live_dir):
    fake_predictor(net_flow=3.0)
    live_dir(current_stock=5, updated_at=NOW)

    result = service.predict_eta_stock("ST-1", eta_minutes=15, now=NOW)

    assert result["current_stock"] == 5
    assert result["predicted_stock"] == 8.0  # 5 + 3.0
    assert result["p_empty"] is None
    assert result["p_full"] is None
    assert result["source"] == "lightgbm"
    assert result["arrival_dow_type"] == 0
    assert result["arrival_time_slot"] == 28  # 14:00 + 15분 = 14:15 -> hour*2 + (minute>=30) = 28


def test_empty_full_probabilities_pass_through_when_predictor_returns_them(
    fake_predictor, live_dir
):
    fake_predictor(net_flow=1.0, p_empty=0.12, p_full=0.34)
    live_dir(current_stock=5, updated_at=NOW)

    result = service.predict_eta_stock("ST-1", eta_minutes=15, now=NOW)

    assert result["p_empty"] == 0.12
    assert result["p_full"] == 0.34


def test_predicted_stock_clips_at_zero_not_negative(fake_predictor, live_dir):
    fake_predictor(net_flow=-100.0)
    live_dir(current_stock=2, updated_at=NOW)

    result = service.predict_eta_stock("ST-1", eta_minutes=15, now=NOW)

    assert result["predicted_stock"] == 0.0


def test_predictor_receives_live_stock_and_weather(fake_predictor, live_dir, weather_dir):
    predictor = fake_predictor(net_flow=1.0)
    live_dir(current_stock=7, updated_at=NOW)
    weather_dir(temp=-3.5, is_rain=True, updated_at=NOW)

    service.predict_eta_stock("ST-1", eta_minutes=10, now=NOW)

    assert len(predictor.calls) == 1
    call = predictor.calls[0]
    assert call["rental_id"] == "ST-1"
    assert call["current_stock"] == 7
    assert call["eta_minutes"] == 10
    assert call["weather"] == {"temp": -3.5, "is_rain": True}


def test_missing_weather_falls_back_to_none_not_error(
    fake_predictor, live_dir, tmp_path, monkeypatch
):
    predictor = fake_predictor(net_flow=1.0)
    live_dir(current_stock=5, updated_at=NOW)
    # 실제 로컬/서버 환경 상태에 기대지 않도록, 확실히 존재하지 않는 경로로 명시 고정한다.
    missing_weather_path = tmp_path / "does_not_exist_weather.parquet"
    monkeypatch.setattr(
        service, "_live_weather_store", service.LiveWeatherStore(missing_weather_path)
    )
    monkeypatch.setattr(
        service, "get_live_weather_store", lambda settings=None: service._live_weather_store
    )

    result = service.predict_eta_stock("ST-1", eta_minutes=10, now=NOW)

    assert result["predicted_stock"] == 6.0
    assert predictor.calls[0]["weather"] is None


def test_stale_weather_falls_back_to_none(fake_predictor, live_dir, weather_dir):
    predictor = fake_predictor(net_flow=1.0)
    live_dir(current_stock=5, updated_at=NOW)
    old_time = datetime(2020, 1, 1, 0, 0)  # noqa: DTZ001
    weather_dir(temp=10.0, is_rain=False, updated_at=old_time)

    service.predict_eta_stock("ST-1", eta_minutes=10, now=NOW)

    assert predictor.calls[0]["weather"] is None


def test_live_stock_missing_raises(fake_predictor, tmp_path, monkeypatch):
    fake_predictor(net_flow=1.0)
    missing_path = tmp_path / "does_not_exist.parquet"
    monkeypatch.setattr(service, "_live_store", service.LiveStockStore(missing_path))
    monkeypatch.setattr(service, "get_live_stock_store", lambda settings=None: service._live_store)

    with pytest.raises(service.LiveStockMissing):
        service.predict_eta_stock("ST-1", eta_minutes=15, now=NOW)


def test_stale_live_stock_raises(fake_predictor, live_dir):
    fake_predictor(net_flow=1.0)
    old_time = datetime(2020, 1, 1, 0, 0)  # noqa: DTZ001
    live_dir(current_stock=5, updated_at=old_time)

    with pytest.raises(service.LiveStockMissing):
        service.predict_eta_stock("ST-1", eta_minutes=15, now=NOW)


def test_model_unavailable_raises(raising_predictor, live_dir):
    live_dir(current_stock=5, updated_at=NOW)

    with pytest.raises(ModelUnavailable):
        service.predict_eta_stock("ST-1", eta_minutes=15, now=NOW)


def test_midnight_rollover_changes_dow_type(fake_predictor, live_dir):
    fake_predictor(net_flow=2.0)
    live_dir(current_stock=4, updated_at=SATURDAY_NIGHT)

    result = service.predict_eta_stock("ST-1", eta_minutes=20, now=SATURDAY_NIGHT)

    assert result["arrival_dow_type"] == 2
    assert result["arrival_time_slot"] == 0
    assert result["predicted_stock"] == 6.0


def test_http_happy_path_returns_200(fake_predictor, live_dir, monkeypatch):
    fake_predictor(net_flow=3.0)
    live_dir(current_stock=5, updated_at=NOW)
    monkeypatch.setattr(pd.Timestamp, "now", staticmethod(lambda: pd.Timestamp(NOW)))

    r = client.get("/bike/stations/ST-1/eta-stock", params={"eta_minutes": 15})

    assert r.status_code == 200
    body = r.json()
    assert body["predicted_stock"] == 8.0
    assert body["source"] == "lightgbm"
    assert body["p_empty"] is None
    assert body["p_full"] is None


def test_http_missing_live_stock_returns_404(fake_predictor, tmp_path, monkeypatch):
    fake_predictor(net_flow=1.0)
    missing_path = tmp_path / "does_not_exist.parquet"
    monkeypatch.setattr(service, "_live_store", service.LiveStockStore(missing_path))
    monkeypatch.setattr(service, "get_live_stock_store", lambda settings=None: service._live_store)

    r = client.get("/bike/stations/ST-1/eta-stock", params={"eta_minutes": 15})

    assert r.status_code == 404


def test_http_model_unavailable_returns_503(raising_predictor, live_dir, monkeypatch):
    live_dir(current_stock=5, updated_at=NOW)
    monkeypatch.setattr(pd.Timestamp, "now", staticmethod(lambda: pd.Timestamp(NOW)))

    r = client.get("/bike/stations/ST-1/eta-stock", params={"eta_minutes": 15})

    assert r.status_code == 503


def test_http_eta_minutes_out_of_range_returns_422(fake_predictor, live_dir):
    fake_predictor(net_flow=1.0)
    live_dir(current_stock=5, updated_at=NOW)

    r = client.get("/bike/stations/ST-1/eta-stock", params={"eta_minutes": 1441})

    assert r.status_code == 422


def test_http_eta_minutes_beyond_30_still_returns_200_with_model_horizon_min_capped(
    fake_predictor, live_dir, monkeypatch
):
    """30분 초과 요청도 거부하지 않는다 — 예측치는 30분 기준으로 근사되지만, 도착 시점
    라벨(arrival_dow_type/arrival_time_slot)은 근사 없이 실제 요청 eta_minutes로 계산된다."""
    fake_predictor(net_flow=2.0, horizon_min_used=30)
    live_dir(current_stock=5, updated_at=NOW)
    monkeypatch.setattr(pd.Timestamp, "now", staticmethod(lambda: pd.Timestamp(NOW)))

    r = client.get("/bike/stations/ST-1/eta-stock", params={"eta_minutes": 1440})

    assert r.status_code == 200
    body = r.json()
    assert body["model_horizon_min"] == 30
    # NOW(2026-09-14 14:00, 월요일) + 1440분(24시간) = 2026-09-15 14:00, 화요일, 공휴일 아님
    assert body["arrival_dow_type"] == 0
    assert body["arrival_time_slot"] == 28


def test_model_horizon_min_passes_through_predictor_value(fake_predictor, live_dir):
    fake_predictor(net_flow=1.0, horizon_min_used=15)
    live_dir(current_stock=5, updated_at=NOW)

    result = service.predict_eta_stock("ST-1", eta_minutes=17, now=NOW)

    assert result["model_horizon_min"] == 15
