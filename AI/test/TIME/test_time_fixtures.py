"""FE 통합용 `POST /time/reroute/check` 4상태 실응답 fixture 생성·검증(S15P21A104-323-3).

`app/TIME/fixtures/reroute_check_<status>.json` 4개(`no_trigger`·`no_alternative`·
`unavailable`·`proposal`)를 이 테스트가 직접 만든다 — 손으로 짠 예시가 아니라 실제
`POST /time/reroute/check` 응답이라는 것이 이 픽스처의 값어치다. 매 pytest 실행마다
저장된 파일과 방금 얻은 응답을 비교해, 라우터·스키마가 바뀌면(FE 몰래) 테스트가 먼저 깨진다.

- 파일이 없거나 `TIME_FIXTURES_UPDATE=1`이면 (다시) 쓴다. 그 밖엔 저장된 값과 정확히
  같아야 한다.
- `recommendationId`는 `uuid4`라 실행마다 다르다 — 저장 전에 고정 플레이스홀더로 치환한다
  (형식은 별도로 `test_proposal_fixture`에서 확인한다). 시각(`NOW`)은 이 모듈 상수로 고정해
  `validUntil`을 결정적으로 만든다.
- LLM은 `test_time_agent_strategy.py`의 `_FakeLlmClient`와 같은 모양의 가짜 클라이언트만
  쓴다 — 실제 GMS 게이트웨이를 부르지 않는다. `_strategy` 팩토리 자체를 monkeypatch해
  `router._strategy()`(설정 기반 실전략 생성)를 아예 타지 않게 한다.
- `test_time_router.py`의 픽스처·가짜 어댑터 패턴을 그대로 따른다 — 라우터의 모듈 레벨
  팩토리(`_station_index`·`_adapter`·`_strategy`·`_now`)를 매 테스트가 갈아끼운다.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.TIME import router
from app.TIME.llm import LlmResult
from app.TIME.registry import GET_ETA_STOCK, REPLAN_ROUTE
from app.TIME.schemas import ToolError
from app.TIME.station_index import InMemoryStationIndex, RentalStation
from app.TIME.strategy import AgentStrategy, RuleStrategy

client = TestClient(app)

KST = ZoneInfo("Asia/Seoul")
NOW = datetime(2026, 9, 23, 9, 0, tzinfo=KST)
"""픽스처 고정 시각. 실행 시각에 따라 `validUntil`이 흔들리지 않게 `router._now`를 이 값으로
monkeypatch한다."""

FIXTURES_DIR = Path(__file__).resolve().parents[2] / "app" / "TIME" / "fixtures"
UPDATE = os.environ.get("TIME_FIXTURES_UPDATE") == "1"

RECOMMENDATION_ID_PLACEHOLDER = "00000000-0000-0000-0000-000000000000"

TARGET_ID = "ST-TARGET"
ALT_A_ID = "ST-ALT-A"
ALT_B_ID = "ST-ALT-B"
UNKNOWN_ID = "ST-UNKNOWN"
DEST_ID = "DEST-1"

BOUNDARY_PAYLOAD = {"legIndex": 1, "nodeId": "ND-221", "lat": 37.5665, "lng": 126.9780}


class _FakeSettings:
    """`test_time_router.py`의 가짜 설정과 같은 필드만 흉내 낸다 — 로컬 `.env`가 뭘 담고
    있든 무관하게 값을 전부 명시로 고정한다."""

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


def _route_element() -> dict[str, Any]:
    # 첫 leg는 ALT_A_ID(고정 시나리오의 선택된 대안)에서 출발하는 BIKE다 — 324 첫 leg 검증
    # 가드(`service._pick_route_from_alternative`)를 통과해야 proposal이 난다.
    return {
        "reason": "BE 고정 문구",
        "source": "ALGORITHM",
        "route": {
            "routeType": "BIKE_SUBWAY",
            "totalMinutes": 20.0,
            "source": "ALGORITHM",
            "totalDistanceMeters": 6000.0,
            "transferCount": 0,
            "legs": [{"mode": "BIKE", "minutes": 20.0, "routeId": None, "fromNodeId": ALT_A_ID}],
        },
    }


class FakeAdapter:
    """`test_time_router.py`의 FakeAdapter와 같은 모양 — `get_eta_stock`은 rental_id별
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


class _FakeLlmClient:
    """`test_time_agent_strategy.py`의 `_FakeLlmClient`와 같은 모양 — 정해진 값을 그대로
    돌려주는 가짜 게이트웨이. 실제 네트워크를 타지 않는다."""

    def __init__(self, text: str) -> None:
        self.text = text
        self.calls: list[tuple[str, str]] = []

    def complete(self, system: str, user: str, *, json_schema: Any = None) -> LlmResult:
        self.calls.append((system, user))
        return LlmResult(
            text=self.text,
            input_tokens=50,
            output_tokens=10,
            latency_ms=1.0,
            model="fixture-fake-llm",
        )


def _rule_strategy_factory(*_args: Any, **_kwargs: Any) -> RuleStrategy:
    """`router._strategy`용 대체 팩토리 — 인자 개수를 신경 쓰지 않는다.

    324-3부터 `_strategy(session_id)`로 세션 단위 예산을 물리게 바뀌었다(`router.py` 모듈
    docstring) — 이 파일은 `router.py`를 고치지 않으니 시그니처 변화에 맞춰 우리 쪽 대체
    팩토리를 가변 인자로 둔다."""
    return RuleStrategy()


def _agent_strategy_factory(fake_llm: _FakeLlmClient) -> Any:
    """`router._strategy`용 대체 팩토리 — 가짜 LLM 클라이언트를 문 `AgentStrategy`를 낸다."""

    def factory(*_args: Any, **_kwargs: Any) -> AgentStrategy:
        return AgentStrategy(fake_llm, RuleStrategy())

    return factory


def _payload(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "sessionId": "FIXTURE-DEFAULT",
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
    """`test_time_router.py`와 같은 리셋 — 매 테스트가 독립적으로 돌게 싱글턴·설정을 되돌린다."""
    monkeypatch.setattr(router, "_session_store_singleton", None)
    monkeypatch.setattr(router, "get_settings", lambda: _FakeSettings())
    monkeypatch.setattr(router, "_now", lambda: NOW)
    yield


def _check(payload: dict[str, Any]) -> dict[str, Any]:
    r = client.post("/time/reroute/check", json=payload)
    assert r.status_code == 200
    return r.json()


def _mask_recommendation_id(response: dict[str, Any]) -> dict[str, Any]:
    """`uuid4`라 실행마다 값이 다른 필드를 고정 플레이스홀더로 치환한 사본을 반환한다."""
    masked = dict(response)
    if masked.get("recommendationId") is not None:
        masked["recommendationId"] = RECOMMENDATION_ID_PLACEHOLDER
    return masked


def _assert_or_write(
    status: str, request_body: dict[str, Any], response_body: dict[str, Any]
) -> None:
    path = FIXTURES_DIR / f"reroute_check_{status}.json"
    fixture = {"request": request_body, "response": response_body}
    if UPDATE or not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(fixture, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved == fixture, (
        f"{path.name} 픽스처가 실제 응답과 다르다 — 의도한 변경이면 "
        "TIME_FIXTURES_UPDATE=1로 재생성한 뒤 diff를 리뷰한다."
    )


# ── no_trigger — p_empty가 임계 미만이라 트리거가 안 선다 ──


def test_no_trigger_fixture(monkeypatch: pytest.MonkeyPatch) -> None:
    index = InMemoryStationIndex([_station(TARGET_ID, name="역삼")])
    monkeypatch.setattr(router, "_station_index", lambda: index)
    monkeypatch.setattr(
        router,
        "_adapter",
        lambda: FakeAdapter(
            eta_stock={TARGET_ID: _eta(current_stock=5, predicted_stock=5.0, p_empty=0.1)}
        ),
    )
    monkeypatch.setattr(router, "_strategy", _rule_strategy_factory)

    payload = _payload(sessionId="FIXTURE-NO-TRIGGER")
    body = _check(payload)

    assert body["status"] == "no_trigger"
    assert body["reason"] == "below_threshold"
    assert body["recommendationId"] is None
    _assert_or_write("no_trigger", payload, body)


# ── no_alternative — 트리거는 서지만 주변에 대체 대여소가 없다 ──


def test_no_alternative_fixture(monkeypatch: pytest.MonkeyPatch) -> None:
    index = InMemoryStationIndex([_station(TARGET_ID, name="역삼")])  # 주변 대여소 없음
    monkeypatch.setattr(router, "_station_index", lambda: index)
    monkeypatch.setattr(
        router,
        "_adapter",
        lambda: FakeAdapter(
            eta_stock={TARGET_ID: _eta(current_stock=0, predicted_stock=0.3, p_empty=0.9)}
        ),
    )
    monkeypatch.setattr(router, "_strategy", _rule_strategy_factory)

    payload = _payload(sessionId="FIXTURE-NO-ALTERNATIVE")
    body = _check(payload)

    assert body["status"] == "no_alternative"
    assert body["reason"] == "no_nearby_station"
    _assert_or_write("no_alternative", payload, body)


# ── unavailable — 대상 대여소 자체를 색인에서 못 찾는다(target_unknown) ──


def test_unavailable_fixture(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(router, "_station_index", lambda: InMemoryStationIndex([]))
    monkeypatch.setattr(router, "_adapter", lambda: FakeAdapter())
    monkeypatch.setattr(router, "_strategy", _rule_strategy_factory)

    payload = _payload(sessionId="FIXTURE-UNAVAILABLE", rentalId=UNKNOWN_ID)
    body = _check(payload)

    assert body["status"] == "unavailable"
    assert body["reason"] == "target_unknown"
    assert body["recommendationId"] is None
    _assert_or_write("unavailable", payload, body)


# ── proposal — 대안이 둘이라 LLM(가짜 클라이언트)이 실제로 고른다 ──


def test_proposal_fixture(monkeypatch: pytest.MonkeyPatch) -> None:
    index = InMemoryStationIndex(
        [
            _station(TARGET_ID, name="역삼"),
            _station(ALT_A_ID, lat=37.5666, lng=126.9780, name="교대"),  # 대상에서 ~11m
            _station(ALT_B_ID, lat=37.5700, lng=126.9780, name="강남"),  # 대상에서 ~390m
        ]
    )
    monkeypatch.setattr(router, "_station_index", lambda: index)
    monkeypatch.setattr(
        router,
        "_adapter",
        lambda: FakeAdapter(
            eta_stock={
                TARGET_ID: _eta(current_stock=0, predicted_stock=0.3, p_empty=0.9),
                ALT_A_ID: _eta(current_stock=4, predicted_stock=4.0, p_empty=0.1),
                ALT_B_ID: _eta(current_stock=6, predicted_stock=6.0, p_empty=0.05),
            }
        ),
    )
    reason = "교대 대여소는 거리가 가깝고 자전거도 넉넉합니다."
    fake_llm = _FakeLlmClient(f'{{"chosen_index": 0, "reason": "{reason}"}}')
    monkeypatch.setattr(router, "_strategy", _agent_strategy_factory(fake_llm))

    payload = _payload(sessionId="FIXTURE-PROPOSAL")
    body = _check(payload)

    assert body["status"] == "proposal"
    assert body["recommendedBy"] == "AGENT"
    assert body["reason"] == reason
    assert fake_llm.calls  # 실제로 (가짜) LLM 경로를 탔는지 확인한다
    # uuid4 형식(36자, 하이픈 4개)인지만 실제 값으로 확인하고, 저장할 때는 고정값으로 치환한다.
    assert len(body["recommendationId"]) == 36
    assert body["recommendationId"].count("-") == 4
    _assert_or_write("proposal", payload, _mask_recommendation_id(body))
