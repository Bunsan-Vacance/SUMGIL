"""도구 어댑터 검증(S15P21A104-202).

여기서 지키려는 것은 두 가지다.

1. **어댑터는 예외를 밖으로 내지 않는다.** 서비스 예외·HTTP 오류·잘못된 인자가 전부
   `ToolError` 반환값이 되는지 본다. 하나라도 예외로 새면 에이전트 루프가 통째로 죽는다.
2. **"없다"와 "모른다"가 안 섞인다.** 배치 미실행·실시간 재고 없음은 `NOT_FOUND`,
   모델 장애·BE 미기동·타임아웃은 `UPSTREAM_UNAVAILABLE`이다.

테스트는 **실제 parquet도 모델 아티팩트도 네트워크도 쓰지 않는다.** CROWD·BIKE 서비스는
가짜 모듈로 갈아끼우고(LocalAdapter가 함수 안에서 지연 import하므로 `sys.modules` 교체가
그대로 먹는다), `requests.request`는 monkeypatch한다.
"""

from __future__ import annotations

import importlib
import json
import sys
import types
from datetime import date, datetime, timedelta

import pytest
import requests

from app.TIME.adapters import CompositeAdapter, HttpAdapter, LocalAdapter
from app.TIME.registry import (
    BIKE_STATIONS_NEARBY,
    GET_ARRIVALS,
    GET_ETA_STOCK,
    GET_LINE_CONGESTION,
    GET_STATION_CONGESTION,
    REPLAN_ROUTE,
)
from app.TIME.schemas import ToolError, ToolErrorCode

# ── 가짜 서비스 모듈 ──


class _LiveStockMissing(RuntimeError):
    """실제 `app.BIKE.service.LiveStockMissing` 자리를 대신한다(둘 다 RuntimeError 파생)."""


class _ModelUnavailable(RuntimeError):
    """실제 `app.BIKE.service.ModelUnavailable` 자리."""


def _install(monkeypatch: pytest.MonkeyPatch, name: str, module: types.ModuleType) -> None:
    """가짜 모듈을 `sys.modules`와 부모 패키지 속성 양쪽에 꽂는다.

    `from app.CROWD import service` 경로가 둘 중 어느 쪽을 보든 같은 가짜를 잡게 하려는 것이다.
    부모 패키지(`app.CROWD`)의 `__init__.py`는 비어 있어 import해도 무거운 것이 안 딸려온다.
    """
    package_name, _, attr = name.rpartition(".")
    monkeypatch.setitem(sys.modules, name, module)
    monkeypatch.setattr(importlib.import_module(package_name), attr, module, raising=False)


def _fake_crowd(
    monkeypatch: pytest.MonkeyPatch,
    *,
    line_result: dict | None = None,
    station_result: dict | None = None,
) -> types.ModuleType:
    module = types.ModuleType("app.CROWD.service")
    module.calls = []  # type: ignore[attr-defined]

    def line_congestion(day: date, line: str, time_slot_30min: str) -> dict | None:
        module.calls.append(("line", day, line, time_slot_30min))  # type: ignore[attr-defined]
        return line_result

    def station_congestion(day: date, station_no: int, direction: str | None = None) -> dict | None:
        module.calls.append(("station", day, station_no, direction))  # type: ignore[attr-defined]
        return station_result

    module.line_congestion = line_congestion  # type: ignore[attr-defined]
    module.station_congestion = station_congestion  # type: ignore[attr-defined]
    _install(monkeypatch, "app.CROWD.service", module)
    return module


def _fake_bike(
    monkeypatch: pytest.MonkeyPatch,
    *,
    result: dict | None = None,
    raises: Exception | None = None,
) -> types.ModuleType:
    module = types.ModuleType("app.BIKE.service")
    module.LiveStockMissing = _LiveStockMissing  # type: ignore[attr-defined]
    module.ModelUnavailable = _ModelUnavailable  # type: ignore[attr-defined]
    module.calls = []  # type: ignore[attr-defined]

    def predict_eta_stock(rental_id: str, eta_minutes: int, now: datetime | None = None) -> dict:
        module.calls.append((rental_id, eta_minutes))  # type: ignore[attr-defined]
        if raises is not None:
            raise raises
        return result or {}

    module.predict_eta_stock = predict_eta_stock  # type: ignore[attr-defined]
    _install(monkeypatch, "app.BIKE.service", module)
    return module


# ── 가짜 HTTP ──


class _FakeResponse:
    def __init__(self, status_code: int = 200, payload: object = None, text: str | None = None):
        self.status_code = status_code
        self._payload = payload
        if text is not None:
            self.text = text
        elif payload is None:
            self.text = ""
        else:
            self.text = json.dumps(payload, ensure_ascii=False)

    def json(self) -> object:
        if self._payload is None:
            raise ValueError("본문이 JSON이 아니다")
        return self._payload


def _patch_requests(monkeypatch: pytest.MonkeyPatch, handler) -> list[dict]:
    """`requests.request`를 가로채고 호출 인자를 기록한다. 실제 소켓은 열리지 않는다."""
    captured: list[dict] = []

    def fake_request(**kwargs):
        captured.append(kwargs)
        return handler(**kwargs)

    monkeypatch.setattr(requests, "request", fake_request)
    return captured


def _respond(response: _FakeResponse):
    return lambda **_: response


def _raise(exc: Exception):
    def handler(**_):
        raise exc

    return handler


# ── LocalAdapter ──


def test_crowd_none_means_batch_not_run(monkeypatch: pytest.MonkeyPatch) -> None:
    """CROWD 서비스의 None은 '그 날짜 표가 없다'(배치 미실행)다 — 확인된 부재라 NOT_FOUND.
    같은 인자로 다시 불러도 답이 같으므로 재시도를 권하지 않는다."""
    _fake_crowd(monkeypatch, line_result=None, station_result=None)
    adapter = LocalAdapter()

    line = adapter.call(
        GET_LINE_CONGESTION,
        {"date": "2026-09-20", "line": "2호선", "time_slot_30min": "08:30"},
    )
    station = adapter.call(GET_STATION_CONGESTION, {"date": "2026-09-20", "station_no": 239})

    for result in (line, station):
        assert isinstance(result, ToolError)
        assert result.error is ToolErrorCode.NOT_FOUND
        assert result.retryable is False
        assert "배치" in result.detail  # 왜 없는지가 detail에 있어야 에이전트가 재시도를 멈춘다
        assert "2026-09-20" in result.detail


def test_crowd_result_passes_through(monkeypatch: pytest.MonkeyPatch) -> None:
    """성공 응답은 손대지 않는다 — data_status·pred_source를 어댑터가 재해석하면
    `registry.TOOLS`에 박아둔 의미와 어긋난다."""
    payload = {
        "date": date(2026, 9, 20),
        "line": "2호선",
        "time_slot_30min": "08:30",
        "stations": [{"station_no": 239, "congestion_pct": 87.2, "data_status": "ok"}],
    }
    crowd = _fake_crowd(monkeypatch, line_result=payload)

    result = LocalAdapter().call(
        GET_LINE_CONGESTION,
        {"date": "2026-09-20", "line": "2호선", "time_slot_30min": "08:30"},
    )

    # 값은 손대지 않는다. 다만 `date` 객체를 선언한 스키마대로 문자열로 맞추느라 컨테이너가
    # 새로 만들어지므로(`_jsonable`) 동일성이 아니라 동등성으로 본다.
    assert result == {**payload, "date": "2026-09-20"}
    # 'date' 문자열이 datetime.date로 바뀌어 서비스에 넘어갔는지
    assert crowd.calls == [("line", date(2026, 9, 20), "2호선", "08:30")]


def test_station_congestion_passes_direction(monkeypatch: pytest.MonkeyPatch) -> None:
    """direction은 선택 인자다. 생략하면 None(전 방향)으로 내려가야 한다."""
    crowd = _fake_crowd(monkeypatch, station_result={"station_no": 239, "slots": []})
    adapter = LocalAdapter()

    adapter.call(GET_STATION_CONGESTION, {"date": "2026-09-20", "station_no": "239"})
    adapter.call(
        GET_STATION_CONGESTION,
        {"date": "2026-09-20", "station_no": 239, "direction": "내선"},
    )

    assert crowd.calls == [
        ("station", date(2026, 9, 20), 239, None),
        ("station", date(2026, 9, 20), 239, "내선"),
    ]


def test_eta_stock_success(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {"rental_id": "ST-001", "predicted_stock": 4.2, "source": "lightgbm"}
    bike = _fake_bike(monkeypatch, result=payload)

    result = LocalAdapter().call(GET_ETA_STOCK, {"rental_id": "ST-001", "eta_minutes": 10})

    # 직렬화 대상(date·datetime)이 없는 응답이라 값도 구조도 그대로다.
    assert result == payload
    assert bike.calls == [("ST-001", 10)]


def test_live_stock_missing_is_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    """재고 스냅샷에 그 대여소가 없다 = 확인된 부재."""
    _fake_bike(monkeypatch, raises=_LiveStockMissing("ST-001 실시간 재고 없음"))

    result = LocalAdapter().call(GET_ETA_STOCK, {"rental_id": "ST-001", "eta_minutes": 10})

    assert isinstance(result, ToolError)
    assert result.error is ToolErrorCode.NOT_FOUND


def test_model_unavailable_is_upstream_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    """모델 아티팩트 장애는 '재고가 없다'가 아니라 '재고를 모른다'다 — 둘을 섞으면
    에이전트가 자전거가 없다고 단정하게 된다."""
    _fake_bike(monkeypatch, raises=_ModelUnavailable("아티팩트 로딩 실패"))

    result = LocalAdapter().call(GET_ETA_STOCK, {"rental_id": "ST-001", "eta_minutes": 10})

    assert isinstance(result, ToolError)
    assert result.error is ToolErrorCode.UPSTREAM_UNAVAILABLE
    assert result.retryable is True


@pytest.mark.parametrize(
    "args",
    [
        {"date": "2026-13-45", "line": "2호선", "time_slot_30min": "08:30"},
        {"date": "내일", "line": "2호선", "time_slot_30min": "08:30"},
        {"line": "2호선", "time_slot_30min": "08:30"},  # date 누락
    ],
)
def test_bad_date_is_invalid_input(monkeypatch: pytest.MonkeyPatch, args: dict) -> None:
    """날짜 파싱 실패는 예외가 아니라 INVALID_INPUT이다. 같은 인자로 재시도해봐야 같은 결과라
    retryable=False — 에이전트는 인자를 고쳐서 다시 부른다."""
    crowd = _fake_crowd(monkeypatch, line_result={"stations": []})

    result = LocalAdapter().call(GET_LINE_CONGESTION, args)

    assert isinstance(result, ToolError)
    assert result.error is ToolErrorCode.INVALID_INPUT
    assert result.retryable is False
    assert crowd.calls == []  # 서비스까지 내려가지 않고 어댑터에서 걸린다


def test_bad_station_no_is_invalid_input(monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_crowd(monkeypatch, station_result={"slots": []})

    result = LocalAdapter().call(
        GET_STATION_CONGESTION, {"date": "2026-09-20", "station_no": "이수역"}
    )

    assert isinstance(result, ToolError)
    assert result.error is ToolErrorCode.INVALID_INPUT


# ── HttpAdapter ──


def test_missing_base_url_returns_error_not_raises() -> None:
    """BE 주소가 아직 없다(계약 회신 대기). 생성도 호출도 예외를 던지지 않고 값으로 알린다 —
    주소 미설정 때문에 로컬 도구 3종까지 같이 못 쓰게 되는 상황을 막는 것이 요점이다."""
    for base_url in (None, "", "   "):
        adapter = HttpAdapter(base_url=base_url if base_url is None else base_url.strip())
        result = adapter.call(GET_ARRIVALS, {"station_id": "S-239"})
        assert isinstance(result, ToolError)
        assert result.error is ToolErrorCode.UPSTREAM_UNAVAILABLE


def test_unwraps_api_result_data(monkeypatch: pytest.MonkeyPatch) -> None:
    """BE 공통 래퍼(`{"data": ...}`)는 어댑터가 벗긴다."""
    body = {"status": "LIVE", "trains": [{"train_id": "2001"}]}
    _patch_requests(monkeypatch, _respond(_FakeResponse(200, {"data": body})))

    result = HttpAdapter(base_url="http://be.test").call(GET_ARRIVALS, {"station_id": "S-239"})

    assert result == body


def test_passes_through_when_not_wrapped(monkeypatch: pytest.MonkeyPatch) -> None:
    """래퍼가 없는 엔드포인트도 있다 — `data` 키가 없으면 응답 전체가 그대로 결과다."""
    body = [{"reason": "혼잡 회피", "source": "ALGORITHM", "route": {}}]
    _patch_requests(monkeypatch, _respond(_FakeResponse(200, body)))

    result = HttpAdapter(base_url="http://be.test").call(
        REPLAN_ROUTE,
        {"step": 1, "boundary_id": "N-1", "dest_station_id": "S-9"},
    )

    assert result == body


def test_arrivals_query_params(monkeypatch: pytest.MonkeyPatch) -> None:
    """route_id는 선택값이라 없으면 쿼리에서 통째로 빠진다(빈 문자열을 보내지 않는다)."""
    captured = _patch_requests(monkeypatch, _respond(_FakeResponse(200, {"data": {}})))
    adapter = HttpAdapter(
        base_url="http://be.test/"
    )  # 끝 슬래시가 중복 경로를 만들지 않는지도 본다

    adapter.call(GET_ARRIVALS, {"station_id": "S-239"})
    adapter.call(GET_ARRIVALS, {"station_id": "S-239", "route_id": "L2"})

    assert captured[0]["method"] == "GET"
    assert captured[0]["url"] == "http://be.test/api/transit/arrivals"
    assert captured[0]["params"] == {"stationId": "S-239"}
    assert captured[1]["params"] == {"stationId": "S-239", "routeId": "L2"}


def test_replan_body_is_camel_case(monkeypatch: pytest.MonkeyPatch) -> None:
    """도구 스키마는 snake_case, BE DTO는 camelCase다. 변환은 어댑터의 일이다."""
    captured = _patch_requests(monkeypatch, _respond(_FakeResponse(200, {"data": []})))

    HttpAdapter(base_url="http://be.test").call(
        REPLAN_ROUTE,
        {
            "step": 2,
            "boundary_id": "N-77",
            "dest_station_id": "S-9",
            "modes": ["SUBWAY", "BIKE"],
            "priority": "calm",
        },
    )

    assert captured[0]["method"] == "POST"
    assert captured[0]["url"] == "http://be.test/api/routes/replan"
    body = captured[0]["json"]
    assert body["step"] == 2
    assert body["boundaryId"] == "N-77"
    assert body["destStationId"] == "S-9"
    assert body["modes"] == ["SUBWAY", "BIKE"]
    assert body["priority"] == "calm"
    assert set(body) == {"step", "boundaryId", "destStationId", "modes", "priority", "requestedAt"}
    # requestedAt은 offset 포함 ISO-8601 KST여야 한다(BE 데이터가 KST 기준이라 UTC면 9시간 어긋난다)
    assert datetime.fromisoformat(body["requestedAt"]).utcoffset() == timedelta(hours=9)


def test_replan_omits_optional_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    """modes·priority를 안 주면 null이 아니라 키 자체를 뺀다 — BE 기본값을 쓰게 한다."""
    captured = _patch_requests(monkeypatch, _respond(_FakeResponse(200, {"data": []})))

    HttpAdapter(base_url="http://be.test").call(
        REPLAN_ROUTE,
        {"step": 0, "boundary_id": "N-1", "dest_station_id": "S-9", "modes": None},
    )

    assert set(captured[0]["json"]) == {"step", "boundaryId", "destStationId", "requestedAt"}


@pytest.mark.parametrize(
    ("status", "code"),
    [
        (400, ToolErrorCode.INVALID_INPUT),
        (404, ToolErrorCode.NOT_FOUND),
        (409, ToolErrorCode.UPSTREAM_UNAVAILABLE),
        (500, ToolErrorCode.UPSTREAM_UNAVAILABLE),
        (502, ToolErrorCode.UPSTREAM_UNAVAILABLE),
        (503, ToolErrorCode.UPSTREAM_UNAVAILABLE),
        (504, ToolErrorCode.UPSTREAM_UNAVAILABLE),
    ],
)
def test_status_code_mapping(
    monkeypatch: pytest.MonkeyPatch, status: int, code: ToolErrorCode
) -> None:
    """404만 '없다'이고 나머지 실패는 전부 '모른다'로 본다."""
    _patch_requests(monkeypatch, _respond(_FakeResponse(status, None, text="에러 본문")))

    result = HttpAdapter(base_url="http://be.test").call(GET_ARRIVALS, {"station_id": "S-239"})

    assert isinstance(result, ToolError)
    assert result.error is code
    assert str(status) in result.detail


@pytest.mark.parametrize(
    "exc",
    [requests.Timeout("timed out"), requests.ConnectionError("refused")],
)
def test_network_failure_is_retryable(monkeypatch: pytest.MonkeyPatch, exc: Exception) -> None:
    """응답을 못 받은 것은 '대안 없음'이 아니다 — 재시도 가치가 있다고 표시한다."""
    _patch_requests(monkeypatch, _raise(exc))

    result = HttpAdapter(base_url="http://be.test", timeout=0.01).call(
        GET_ARRIVALS, {"station_id": "S-239"}
    )

    assert isinstance(result, ToolError)
    assert result.error is ToolErrorCode.UPSTREAM_UNAVAILABLE
    assert result.retryable is True


def test_default_timeout_is_two_seconds(monkeypatch: pytest.MonkeyPatch) -> None:
    """에이전트 루프 안의 호출이라 기본 타임아웃을 짧게 둔다."""
    captured = _patch_requests(monkeypatch, _respond(_FakeResponse(200, {"data": {}})))

    HttpAdapter(base_url="http://be.test").call(GET_ARRIVALS, {"station_id": "S-239"})

    assert captured[0]["timeout"] == 2.0


def test_non_json_response_is_upstream_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    """200인데 본문이 JSON이 아니면(프록시 HTML 등) 값을 지어내지 않고 실패로 돌린다."""
    _patch_requests(monkeypatch, _respond(_FakeResponse(200, None, text="<html>502</html>")))

    result = HttpAdapter(base_url="http://be.test").call(GET_ARRIVALS, {"station_id": "S-239"})

    assert isinstance(result, ToolError)
    assert result.error is ToolErrorCode.UPSTREAM_UNAVAILABLE


def test_bike_stations_nearby_query_params(monkeypatch: pytest.MonkeyPatch) -> None:
    """radius_meters·limit은 선택값이라 안 주면 쿼리에서 빠진다(modes·priority와 같은 규칙).
    필수 lat·lng는 그대로 전달되고 radius_meters만 camelCase(radiusMeters)로 바뀐다."""
    captured = _patch_requests(monkeypatch, _respond(_FakeResponse(200, {"data": []})))
    adapter = HttpAdapter(base_url="http://be.test")

    adapter.call(BIKE_STATIONS_NEARBY, {"lat": 37.5665, "lng": 127.0})
    adapter.call(
        BIKE_STATIONS_NEARBY,
        {"lat": 37.5665, "lng": 127.0, "radius_meters": 800, "limit": 10},
    )

    assert captured[0]["method"] == "GET"
    assert captured[0]["url"] == "http://be.test/api/bike-stations/nearby"
    assert captured[0]["params"] == {"lat": 37.5665, "lng": 127.0}
    assert captured[1]["params"] == {
        "lat": 37.5665,
        "lng": 127.0,
        "radiusMeters": 800,
        "limit": 10,
    }


def test_bike_stations_nearby_missing_lat_is_invalid_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """필수 인자가 없으면 BE를 부르지도 않고 INVALID_INPUT이다(다른 HTTP 도구와 같은 규칙)."""
    captured = _patch_requests(monkeypatch, _respond(_FakeResponse(200, {"data": []})))

    result = HttpAdapter(base_url="http://be.test").call(BIKE_STATIONS_NEARBY, {"lng": 127.0})

    assert isinstance(result, ToolError)
    assert result.error is ToolErrorCode.INVALID_INPUT
    assert captured == []


def test_bike_stations_nearby_unwraps_response(monkeypatch: pytest.MonkeyPatch) -> None:
    """다른 HTTP 도구와 같은 `{"data": ...}` 래퍼를 쓴다 — 어댑터가 벗겨서 배열 그대로 돌려준다."""
    body = [
        {
            "rentalId": "ST-1",
            "name": "테스트 대여소",
            "lat": 37.5,
            "lng": 127.0,
            "dockCount": 10,
            "distanceMeters": 42.0,
        }
    ]
    _patch_requests(monkeypatch, _respond(_FakeResponse(200, {"data": body})))

    result = HttpAdapter(base_url="http://be.test").call(
        BIKE_STATIONS_NEARBY, {"lat": 37.5, "lng": 127.0}
    )

    assert result == body


def test_bike_stations_nearby_dto에_없는_필드가_와도_그대로_통과한다(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """스키마(rentalId 등 6개)에 없는 필드가 BE 응답에 섞여 와도 어댑터가 지어내거나 걸러내지
    않고 그대로 통과시킨다 — 어댑터는 스키마 검증기가 아니다."""
    body = [{"rentalId": "ST-1", "availableBikes": None, "stockUpdatedAt": None}]
    _patch_requests(monkeypatch, _respond(_FakeResponse(200, {"data": body})))

    result = HttpAdapter(base_url="http://be.test").call(
        BIKE_STATIONS_NEARBY, {"lat": 37.5, "lng": 127.0}
    )

    assert result == body


def test_bike_stations_nearby_status_code_mapping(monkeypatch: pytest.MonkeyPatch) -> None:
    """새 분기가 상태코드 매핑까지 새로 짜지 않는다 — 기존 `_error_for_status`를 그대로 탄다."""
    _patch_requests(monkeypatch, _respond(_FakeResponse(404, None, text="대여소 없음")))

    result = HttpAdapter(base_url="http://be.test").call(
        BIKE_STATIONS_NEARBY, {"lat": 37.5, "lng": 127.0}
    )

    assert isinstance(result, ToolError)
    assert result.error is ToolErrorCode.NOT_FOUND


def test_http_missing_required_arg_is_invalid_input(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = _patch_requests(monkeypatch, _respond(_FakeResponse(200, {"data": {}})))

    result = HttpAdapter(base_url="http://be.test").call(REPLAN_ROUTE, {"step": 1})

    assert isinstance(result, ToolError)
    assert result.error is ToolErrorCode.INVALID_INPUT
    assert captured == []  # 인자가 모자라면 BE를 부르지도 않는다


# ── 알 수 없는 도구 · 라우팅 ──


@pytest.mark.parametrize(
    "adapter",
    [LocalAdapter(), HttpAdapter(base_url="http://be.test"), CompositeAdapter()],
    ids=["local", "http", "composite"],
)
def test_unknown_tool_name_is_invalid_input(adapter) -> None:
    """LLM이 없는 도구 이름을 지어내는 것은 흔한 실패다. detail에 쓸 수 있는 이름을 담아
    다음 턴에 고쳐 부를 수 있게 한다."""
    result = adapter.call("get_weather", {})

    assert isinstance(result, ToolError)
    assert result.error is ToolErrorCode.INVALID_INPUT
    assert GET_LINE_CONGESTION in result.detail


def test_composite_routes_by_tool_name(monkeypatch: pytest.MonkeyPatch) -> None:
    """이름만 보고 Local/Http 중 맞는 쪽으로 간다 — 호출자가 경로를 몰라도 되게 하는 것이
    CompositeAdapter의 존재 이유다."""
    _fake_crowd(monkeypatch, line_result={"stations": []})
    captured = _patch_requests(monkeypatch, _respond(_FakeResponse(200, {"data": {"trains": []}})))
    composite = CompositeAdapter(http=HttpAdapter(base_url="http://be.test"))

    local_result = composite.call(
        GET_LINE_CONGESTION,
        {"date": "2026-09-20", "line": "2호선", "time_slot_30min": "08:30"},
    )
    http_result = composite.call(GET_ARRIVALS, {"station_id": "S-239"})

    assert local_result == {"stations": []}
    assert http_result == {"trains": []}
    assert len(captured) == 1  # 로컬 도구가 네트워크를 타지 않았다


# ── 불변식 마무리(S15P21A104-202 후속) ──
# 아래 둘은 어댑터 구현 후 발견된 구멍이다. 명시적으로 번역하지 않은 예외가 새면 루프가 죽고,
# date 객체가 섞여 나가면 LLM 요청 body를 만들 때 터진다.


def test_예상하지_못한_예외도_ToolError가_된다(monkeypatch: pytest.MonkeyPatch) -> None:
    """서비스가 새 예외를 추가해도(예: AvgDataMissing) 어댑터 밖으로 새지 않아야 한다.
    `LiveStockMissing`·`ModelUnavailable`만 잡으면 그때 루프가 통째로 죽는다."""
    module = types.ModuleType("app.CROWD.service")

    def line_congestion(day: date, line: str, time_slot_30min: str) -> dict:
        raise RuntimeError("배율표 로딩 실패")

    module.line_congestion = line_congestion  # type: ignore[attr-defined]
    _install(monkeypatch, "app.CROWD.service", module)

    result = LocalAdapter().call(
        GET_LINE_CONGESTION,
        {"date": "2026-09-20", "line": "2호선", "time_slot_30min": "08:30"},
    )

    assert isinstance(result, ToolError)
    assert result.error is ToolErrorCode.UPSTREAM_UNAVAILABLE
    assert "RuntimeError" in result.detail


def test_성공_결과가_JSON_직렬화된다(monkeypatch: pytest.MonkeyPatch) -> None:
    """CROWD 서비스는 `date` 컬럼을 datetime.date 객체로 돌려준다. 도구 결과는 그대로 LLM
    요청 body에 들어가므로 여기서 문자열이 돼 있어야 한다 — output_schema의 약속이기도 하다."""
    _fake_crowd(
        monkeypatch,
        line_result={
            "date": date(2026, 9, 20),
            "line": "2호선",
            "stations": [{"station_no": 239, "congestion_pct": 88.5, "data_status": "ok"}],
        },
    )

    result = LocalAdapter().call(
        GET_LINE_CONGESTION,
        {"date": "2026-09-20", "line": "2호선", "time_slot_30min": "08:30"},
    )

    assert isinstance(result, dict)
    assert result["date"] == "2026-09-20"
    # 숫자·문자열은 손대지 않는다 — 직렬화 가능한 모양으로만 맞춘다.
    assert result["stations"][0]["congestion_pct"] == 88.5
    json.dumps(result, ensure_ascii=False)
