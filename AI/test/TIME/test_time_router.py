"""재안내 라우터 검증(S15P21A104-302).

`POST /time/reroute/check`가 지켜야 하는 것들 — 항상 HTTP 200(500 없음), `no_trigger`는
`status`(+`reason`)만 온다, `proposal`은 `recommendationId`·`validUntil`·`recommendedBy`·
`boundary` echo·`walkLeg`·`route`까지 전부 채워진다, 같은 세션은 쿨다운이 걸리고 다른 세션은
안 걸린다, `debugForceTrigger`는 운영 플래그(`time_debug_force_trigger_enabled`)가 꺼져 있으면
무시된다, `boundary`가 없으면 `unavailable`/`boundary_missing`, 어댑터가 터져도 500이 아니라
`unavailable`/`internal_error`, 잘못된 본문은 FastAPI 기본 422(문서화만 한다).

`app.TIME.router`의 모듈 레벨 팩토리(`_station_index`·`_adapter`·`_strategy`·`_now`)를
monkeypatch로 갈아끼운다 — `app.BIKE.router` 테스트가 `service._store`를 갈아끼우는 것과 같은
패턴이다. `_session_store`는 실제 `InMemorySessionStore`를 그대로 쓴다 — 쿨다운 자체가 검증
대상이라, 매 테스트 시작 전에 싱글턴만 리셋해서 테스트 사이에 상태가 새지 않게 한다.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.TIME import router
from app.TIME.registry import GET_ETA_STOCK, REPLAN_ROUTE
from app.TIME.schemas import ToolError
from app.TIME.station_index import InMemoryStationIndex, RentalStation
from app.TIME.strategy import RuleStrategy

client = TestClient(app)

KST = ZoneInfo("Asia/Seoul")
NOW = datetime(2026, 9, 22, 9, 0, tzinfo=KST)

TARGET_ID = "ST-TARGET"
ALT_ID = "ST-ALT"
DEST_ID = "DEST-1"

BOUNDARY_PAYLOAD = {"legIndex": 1, "nodeId": "ND-221", "lat": 37.5665, "lng": 126.9780}


class _FakeSettings:
    """`router.py`가 읽는 필드만 흉내 낸 가짜 설정.

    실제 `.env`/`Settings` 기본값에 테스트가 휘둘리지 않도록(로컬 `.env`가 뭘 담고 있든 무관하게)
    전부 명시로 고정한다.
    """

    def __init__(self, **overrides: Any) -> None:
        base: dict[str, Any] = {
            "time_be_base_url": None,
            "time_be_timeout_sec": 3.0,
            "time_trigger_cooldown_sec": 600.0,
            "time_recommendation_ttl_sec": 600.0,
            "time_debug_force_trigger_enabled": False,
            "time_nearby_radius_m": 500,
            "time_nearby_limit": 5,
            "time_trigger_p_empty": 0.7,
            "time_trigger_min_stock": 1.0,
            "time_trigger_max_eta_min": 30,
            "time_score_empty_penalty_min": 10.0,
            "time_llm_base_url": None,
            "time_llm_model": None,
            "time_llm_api_key": None,
            "time_llm_max_calls_per_session": 3,
            "time_llm_max_tokens_per_session": 8000,
            "time_agent_reason_max_sentences": 2,
            "time_agent_reason_max_chars": 120,
        }
        base.update(overrides)
        for key, value in base.items():
            setattr(self, key, value)


def _station(
    rental_id: str, *, lat: float = 37.5665, lng: float = 126.9780, name: str | None = None
) -> RentalStation:
    return RentalStation(
        rental_id=rental_id,
        name=name or rental_id,
        lat=lat,
        lng=lng,
        rack_count=10,
        current_stock=5,
        updated_at=None,
    )


TARGET_STATION = _station(TARGET_ID, name="역삼")
ALT_STATION = _station(ALT_ID, lat=37.5666, lng=126.9780, name="교대")  # 대상에서 ~11m
DEFAULT_INDEX = InMemoryStationIndex([TARGET_STATION, ALT_STATION])


def _eta(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "rental_id": "X",
        "eta_minutes": 10,
        "current_stock": 0,
        "predicted_stock": 0.3,
        "p_empty": 0.9,
        "p_full": 0.0,
        "source": "lightgbm",
        "model_horizon_min": 10,
    }
    body.update(overrides)
    return body


FIRED_TARGET = _eta(current_stock=0, predicted_stock=0.3, p_empty=0.9)
"""p_empty 0.9 ≥ 기본 임계(0.7) — 트리거가 선다."""

BELOW_THRESHOLD_TARGET = _eta(current_stock=5, predicted_stock=5.0, p_empty=0.1)
"""트리거가 안 선다."""

GOOD_ALT = _eta(current_stock=4, predicted_stock=4.0, p_empty=0.1)


def _route_element() -> dict[str, Any]:
    return {
        "reason": "BE 고정 문구",
        "source": "ALGORITHM",
        "route": {
            "routeType": "BIKE_SUBWAY",
            "totalMinutes": 20.0,
            "source": "ALGORITHM",
            "totalDistanceMeters": 6000.0,
            "transferCount": 0,
            "legs": [{"mode": "BIKE", "minutes": 20.0, "routeId": None}],
        },
    }


class FakeAdapter:
    """`test_time_service.py`의 FakeAdapter와 같은 모양 — `get_eta_stock`은 rental_id별
    고정 응답을, `replan_route`는 고정된 성공 응답(기본)을 낸다."""

    def __init__(self, *, eta_stock: Mapping[str, Any] | None = None, replan: Any = None) -> None:
        self.eta_stock = dict(eta_stock or {})
        self.replan = [_route_element()] if replan is None else replan

    def call(self, name: str, args: Mapping[str, Any]) -> Any:
        if name == GET_ETA_STOCK:
            rental_id = str(args["rental_id"])
            if rental_id not in self.eta_stock:
                return ToolError.not_found(f"{rental_id} 실시간 재고를 확인할 수 없다")
            return self.eta_stock[rental_id]
        if name == REPLAN_ROUTE:
            return self.replan
        return ToolError.invalid_input(f"가짜 어댑터가 모르는 도구 '{name}'")


class _ExplodingAdapter:
    """무엇을 부르든 예외를 던진다 — 라우터가 500 대신 unavailable을 내는지 확인한다."""

    def call(self, name: str, args: Mapping[str, Any]) -> Any:
        raise ValueError("어댑터 내부 버그")


def _default_adapter() -> FakeAdapter:
    return FakeAdapter(eta_stock={TARGET_ID: FIRED_TARGET, ALT_ID: GOOD_ALT})


def _payload(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "sessionId": "SESS-1",
        "step": 0,
        "rentalId": TARGET_ID,
        "etaToRentalMinutes": 10,
        "destStationId": DEST_ID,
        "boundary": BOUNDARY_PAYLOAD,
    }
    body.update(overrides)
    return body


@pytest.fixture(autouse=True)
def _reset_router(monkeypatch: pytest.MonkeyPatch):
    """싱글턴·설정을 매 테스트마다 리셋한다 — 테스트 순서에 무관하게 독립적으로 돈다.

    `_session_store`는 monkeypatch하지 않는다 — 쿨다운 검증(같은 세션이면 막히고 다른 세션은
    안 막히는지)이 이 테스트 모듈의 목적 중 하나라, 실제 `InMemorySessionStore`가 그대로 돌아야
    한다. 대신 싱글턴 변수를 매번 `None`으로 되돌려 테스트끼리 세션 기록이 안 새게 한다.
    """
    monkeypatch.setattr(router, "_session_store_singleton", None)
    monkeypatch.setattr(router, "get_settings", lambda: _FakeSettings())
    monkeypatch.setattr(router, "_station_index", lambda: DEFAULT_INDEX)
    monkeypatch.setattr(router, "_adapter", _default_adapter)
    monkeypatch.setattr(router, "_strategy", RuleStrategy)
    monkeypatch.setattr(router, "_now", lambda: NOW)
    yield


# ── no_trigger ──


def test_트리거가_안_서면_status만_온다(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        router, "_adapter", lambda: FakeAdapter(eta_stock={TARGET_ID: BELOW_THRESHOLD_TARGET})
    )

    r = client.post("/time/reroute/check", json=_payload())

    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "no_trigger"
    assert body["recommendationId"] is None
    assert body["target"] is None


# ── proposal ──


def test_추천이_있으면_전체_필드가_채워진다():
    r = client.post("/time/reroute/check", json=_payload())

    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "proposal"
    # uuid4 형식(36자, 하이픈 4개)인지만 확인한다 — 정확한 값은 알 수 없다.
    assert len(body["recommendationId"]) == 36
    assert body["recommendationId"].count("-") == 4
    assert body["validUntil"] is not None
    assert datetime.fromisoformat(body["validUntil"]) == NOW + timedelta(seconds=600.0)
    assert body["recommendedBy"] == "ALGORITHM"
    assert body["boundary"] == BOUNDARY_PAYLOAD
    assert body["walkLeg"]["estimated"] is True
    assert body["walkLeg"]["mode"] == "WALK"
    assert body["route"]["routeType"] == "BIKE_SUBWAY"
    assert body["target"]["rentalId"] == TARGET_ID
    assert body["alternative"]["rentalId"] == ALT_ID


# ── 쿨다운 ──


def test_같은_세션_두번째_요청은_쿨다운으로_no_trigger다():
    first = client.post("/time/reroute/check", json=_payload())
    assert first.json()["status"] == "proposal"

    # 시계가 고정돼 있어(NOW) 두 번째 요청은 명백히 쿨다운 창(600초) 안이다.
    second = client.post("/time/reroute/check", json=_payload())

    assert second.status_code == 200
    body = second.json()
    assert body["status"] == "no_trigger"
    assert body["reason"] == "cooldown"


def test_다른_세션은_쿨다운의_영향을_받지_않는다():
    first = client.post("/time/reroute/check", json=_payload(sessionId="SESS-1"))
    assert first.json()["status"] == "proposal"

    second = client.post("/time/reroute/check", json=_payload(sessionId="SESS-2"))

    assert second.json()["status"] == "proposal"


# ── debugForceTrigger ──


def test_강제_트리거는_플래그가_꺼져있으면_무시된다(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        router, "_adapter", lambda: FakeAdapter(eta_stock={TARGET_ID: BELOW_THRESHOLD_TARGET})
    )

    r = client.post("/time/reroute/check", json=_payload(debugForceTrigger=True))

    assert r.json()["status"] == "no_trigger"


def test_강제_트리거는_플래그가_켜지면_동작한다(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        router,
        "_adapter",
        lambda: FakeAdapter(eta_stock={TARGET_ID: BELOW_THRESHOLD_TARGET, ALT_ID: GOOD_ALT}),
    )
    monkeypatch.setattr(
        router, "get_settings", lambda: _FakeSettings(time_debug_force_trigger_enabled=True)
    )

    r = client.post("/time/reroute/check", json=_payload(debugForceTrigger=True))

    assert r.json()["status"] == "proposal"


# ── boundary 없음 ──


def test_boundary가_없으면_unavailable이다():
    r = client.post("/time/reroute/check", json=_payload(boundary=None))

    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "unavailable"
    assert body["reason"] == "boundary_missing"


# ── 어댑터 예외 ──


def test_어댑터가_터져도_500이_아니라_unavailable이다(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(router, "_adapter", _ExplodingAdapter)

    r = client.post("/time/reroute/check", json=_payload())

    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "unavailable"
    assert body["reason"] == "internal_error"


# ── 잘못된 본문 — FastAPI 기본 422로 충분하다(문서화) ──


def test_필수_필드가_없으면_422다():
    r = client.post("/time/reroute/check", json={"sessionId": "SESS-1"})

    assert r.status_code == 422
