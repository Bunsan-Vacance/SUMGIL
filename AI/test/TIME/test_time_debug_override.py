"""시연용 예측 override 어댑터 검증(S15P21A104-301-B).

두 층을 본다.

1. **래퍼 단위** — `DebugEmptyStockAdapter.call()` 하나만 놓고, 목록 안/밖·`ToolError`·다른
   도구 이름·`model_horizon_min` 채움 여부를 확인한다. 실제 어댑터·서비스는 쓰지 않는다.
2. **라우터 통합** — `router._adapter()`의 게이트(`time_debug_force_trigger_enabled` AND
   `debug_empty_rental_ids`)가 실제로 켜고 끄는지, `GET /time/meta`가 게이트에 따라 목록을
   노출/은닉하는지를 `POST /time/reroute/check` 전체 흐름으로 확인한다. `router._adapter` 자체는
   monkeypatch하지 않는다 — 그래야 이 함수의 게이팅 로직이 실제로 실행된다. 대신 그 안에서
   조립되는 `router.LocalAdapter`/`router.HttpAdapter`만 가짜로 갈아끼운다(실제 BIKE 서비스·
   네트워크를 타지 않기 위해서).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.TIME import router
from app.TIME.adapters import DebugEmptyStockAdapter
from app.TIME.registry import GET_ETA_STOCK, GET_LINE_CONGESTION, REPLAN_ROUTE
from app.TIME.schemas import ToolError
from app.TIME.strategy import RuleStrategy
from test_time_router import (
    ALT_ID,
    BELOW_THRESHOLD_TARGET,
    DEFAULT_INDEX,
    GOOD_ALT,
    NOW,
    TARGET_ID,
    _FakeSettings,
    _payload,
    _route_element,
)

client = TestClient(app)


# ── 래퍼 단위 ──


class _FakeInner:
    """`ToolAdapter` Protocol을 흉내 낸 가짜 내부 어댑터. 고정 응답표를 그대로 돌려준다."""

    def __init__(self, responses: Mapping[str, Any]) -> None:
        self._responses = dict(responses)
        self.calls: list[tuple[str, Mapping[str, Any]]] = []

    def call(self, name: str, args: Mapping[str, Any]) -> Any:
        self.calls.append((name, args))
        key = f"{name}:{args.get('rental_id')}"
        if key in self._responses:
            return self._responses[key]
        if name in self._responses:
            return self._responses[name]
        return ToolError.invalid_input(f"고정되지 않은 호출 {name}/{dict(args)}")


def _eta(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "rental_id": "ST-X",
        "eta_minutes": 10,
        "current_stock": 4,
        "predicted_stock": 3.5,
        "p_empty": 0.1,
        "p_full": 0.0,
        "source": "lightgbm",
        "model_horizon_min": 10,
    }
    body.update(overrides)
    return body


def test_목록_안이면_세_필드가_치환되고_current_stock과_p_full은_유지된다() -> None:
    original = _eta(rental_id="ST-1", current_stock=7, p_full=0.02)
    inner = _FakeInner({"get_eta_stock:ST-1": original})
    adapter = DebugEmptyStockAdapter(inner, ["ST-1"], horizon_fill_min=30)

    result = adapter.call(GET_ETA_STOCK, {"rental_id": "ST-1", "eta_minutes": 10})

    assert result["predicted_stock"] == 0.0
    assert result["p_empty"] == 1.0
    assert result["source"] == "debug_override"
    assert result["current_stock"] == 7  # 실값 유지
    assert result["p_full"] == 0.02  # 실값 유지
    assert result["model_horizon_min"] == 10  # 이미 있으면 덮어쓰지 않는다
    # 원본 dict는 바뀌지 않는다.
    assert original["predicted_stock"] == 3.5
    assert original["p_empty"] == 0.1
    assert original["source"] == "lightgbm"


def test_model_horizon_min이_없을_때만_설정값으로_채운다() -> None:
    original = _eta(rental_id="ST-1", model_horizon_min=None)
    inner = _FakeInner({"get_eta_stock:ST-1": original})
    adapter = DebugEmptyStockAdapter(inner, ["ST-1"], horizon_fill_min=30)

    result = adapter.call(GET_ETA_STOCK, {"rental_id": "ST-1", "eta_minutes": 40})

    assert result["model_horizon_min"] == 30
    assert original["model_horizon_min"] is None  # 원본은 그대로


def test_목록_밖이면_원본_그대로_통과한다() -> None:
    original = _eta(rental_id="ST-2")
    inner = _FakeInner({"get_eta_stock:ST-2": original})
    adapter = DebugEmptyStockAdapter(inner, ["ST-1"], horizon_fill_min=30)

    result = adapter.call(GET_ETA_STOCK, {"rental_id": "ST-2", "eta_minutes": 10})

    assert result == original


def test_ToolError는_그대로_통과한다() -> None:
    """오류였을 자리를 성공으로 둔갑시키지 않는다 — 목록에 있어도 마찬가지다."""
    err = ToolError.upstream_unavailable("모델 장애")
    inner = _FakeInner({"get_eta_stock:ST-1": err})
    adapter = DebugEmptyStockAdapter(inner, ["ST-1"], horizon_fill_min=30)

    result = adapter.call(GET_ETA_STOCK, {"rental_id": "ST-1", "eta_minutes": 10})

    assert result is err


def test_다른_도구_이름은_그대로_통과한다() -> None:
    """`get_eta_stock`이 아니면 목록 검사 자체를 하지 않는다."""
    payload = {"stations": []}
    inner = _FakeInner({GET_LINE_CONGESTION: payload})
    adapter = DebugEmptyStockAdapter(inner, ["ST-1"], horizon_fill_min=30)

    result = adapter.call(
        GET_LINE_CONGESTION, {"date": "2026-09-20", "line": "2호선", "time_slot_30min": "08:30"}
    )

    assert result == payload


# ── 라우터 통합 ──


class _FakeLocal:
    """`_adapter()`가 만드는 실제 `LocalAdapter()` 자리를 대신한다 — 실제 BIKE 서비스(pandas·
    모델 아티팩트)를 부르지 않기 위해서다. `router.LocalAdapter`를 이 클래스로 통째로
    monkeypatch해, `_adapter()`의 게이팅·`CompositeAdapter` 조립 로직은 실제 코드를 그대로
    태운다."""

    def __init__(self, eta_stock: Mapping[str, Any]) -> None:
        self._eta_stock = dict(eta_stock)

    def call(self, name: str, args: Mapping[str, Any]) -> Any:
        if name == GET_ETA_STOCK:
            rental_id = str(args["rental_id"])
            if rental_id not in self._eta_stock:
                return ToolError.not_found(f"{rental_id} 실시간 재고를 확인할 수 없다")
            return dict(self._eta_stock[rental_id])
        return ToolError.invalid_input(f"가짜 로컬 어댑터가 모르는 도구 '{name}'")


class _FakeHttp:
    """`HttpAdapter(base_url, timeout)` 생성자 시그니처를 흉내 내 `_adapter()`가 그대로
    호출할 수 있게 한다."""

    def __init__(self, *_args: Any, **_kwargs: Any) -> None:
        pass

    def call(self, name: str, args: Mapping[str, Any]) -> Any:
        if name == REPLAN_ROUTE:
            return [_route_element()]
        return ToolError.invalid_input(f"가짜 HTTP 어댑터가 모르는 도구 '{name}'")


def _debug_settings(**overrides: Any) -> _FakeSettings:
    base: dict[str, Any] = {
        "time_debug_force_trigger_enabled": True,
        "debug_empty_rental_ids": [TARGET_ID],
    }
    base.update(overrides)
    return _FakeSettings(**base)


@pytest.fixture(autouse=True)
def _reset(monkeypatch: pytest.MonkeyPatch):
    """`router._adapter`는 건드리지 않는다 — 이 파일의 목적이 그 함수의 실제 게이팅 로직을
    검증하는 것이다. 대신 그 안에서 쓰이는 조각(색인·전략·시계·Local/HttpAdapter)을 갈아끼운다."""
    monkeypatch.setattr(router, "_session_store_singleton", None)
    monkeypatch.setattr(router, "_station_index", lambda: DEFAULT_INDEX)
    monkeypatch.setattr(router, "_strategy", lambda session_id: RuleStrategy())
    monkeypatch.setattr(router, "_now", lambda: NOW)
    yield


def test_게이트_켜짐_목록에_대상_대여소면_실판정으로는_안_서던_것도_proposal이_된다(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`BELOW_THRESHOLD_TARGET`(p_empty 0.1)은 override 없이는 트리거가 안 선다
    (`test_time_router.py`의 `test_트리거가_안_서면_status만_온다` 참고) — override가
    predicted_stock=0/p_empty=1.0으로 덮어써야만 proposal이 난다."""
    monkeypatch.setattr(
        router,
        "LocalAdapter",
        lambda: _FakeLocal({TARGET_ID: BELOW_THRESHOLD_TARGET, ALT_ID: GOOD_ALT}),
    )
    monkeypatch.setattr(router, "HttpAdapter", _FakeHttp)
    monkeypatch.setattr(router, "get_settings", lambda: _debug_settings())

    r = client.post("/time/reroute/check", json=_payload())

    assert r.status_code == 200
    assert r.json()["status"] == "proposal"


def test_게이트_꺼짐이면_목록이_있어도_실판정이다(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        router,
        "LocalAdapter",
        lambda: _FakeLocal({TARGET_ID: BELOW_THRESHOLD_TARGET, ALT_ID: GOOD_ALT}),
    )
    monkeypatch.setattr(router, "HttpAdapter", _FakeHttp)
    monkeypatch.setattr(
        router,
        "get_settings",
        lambda: _debug_settings(time_debug_force_trigger_enabled=False),
    )

    r = client.post("/time/reroute/check", json=_payload())

    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "no_trigger"
    assert body["reason"] == "below_threshold"


def test_meta는_게이트_켜지면_목록을_노출한다(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(router, "get_settings", lambda: _debug_settings())

    r = client.get("/time/meta")

    assert r.status_code == 200
    assert r.json()["debugEmptyRentalIds"] == [TARGET_ID]


def test_meta는_게이트_꺼지면_목록이_있어도_비운다(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        router,
        "get_settings",
        lambda: _debug_settings(time_debug_force_trigger_enabled=False),
    )

    r = client.get("/time/meta")

    assert r.status_code == 200
    assert r.json()["debugEmptyRentalIds"] == []
