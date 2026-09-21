"""도구 이름 → 실제 구현을 잇는 어댑터(S15P21A104-202).

경로가 둘이다. **로컬**은 같은 프로세스의 `app.CROWD` / `app.BIKE` 서비스 함수를 직접 부르고
(네트워크 비용이 없다), **HTTP**는 BE API를 부른다. 이 구분은 도구 이름으로 고정돼 있어
(`registry.LOCAL_TOOLS` / `HTTP_TOOLS`) 호출자는 `CompositeAdapter` 하나만 쓰면 된다.

어댑터는 **예외를 밖으로 내보내지 않는다.** 서비스 예외도, HTTP 오류도, 인자 파싱 실패도 전부
`ToolError`라는 반환값으로 바꾼다 — 이유는 `schemas.py` 첫 문단에 있다. 그래서 이 파일의
`try/except`는 "숨기기"가 아니라 "번역"이다. 어떤 실패가 `NOT_FOUND`(없다는 걸 확인함)이고
어떤 실패가 `UPSTREAM_UNAVAILABLE`(물어보지 못함)인지가 이 파일의 핵심 판단이다.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date as date_type
from datetime import datetime
from typing import Any, Protocol
from zoneinfo import ZoneInfo

import requests

from app.TIME.registry import (
    BIKE_STATIONS_NEARBY,
    GET_ARRIVALS,
    GET_ETA_STOCK,
    GET_LINE_CONGESTION,
    GET_STATION_CONGESTION,
    HTTP_TOOLS,
    LOCAL_TOOLS,
    REPLAN_ROUTE,
)
from app.TIME.schemas import ToolError

# `app.BIKE.pipeline.calendar.KST`와 같은 값이지만 그 모듈은 pandas를 끌어온다 —
# 어댑터는 서빙 경로라 상수 하나 때문에 무거운 의존성을 물리지 않는다(AI/CLAUDE.md 디렉터리 규약).
KST = ZoneInfo("Asia/Seoul")

DEFAULT_HTTP_TIMEOUT_SECONDS = 2.0
"""BE 호출 타임아웃. 에이전트 루프 안에서 도는 호출이라 길게 기다리느니 빨리 포기하고
`UPSTREAM_UNAVAILABLE`로 알려주는 편이 낫다 — 루프가 다른 경로를 택할 수 있다."""

ToolResult = dict[str, Any] | list[Any] | ToolError
"""도구 반환값. replan_route만 배열이고 나머지는 객체다(`registry.TOOLS`의 output_schema)."""


class ToolAdapter(Protocol):
    """도구 하나를 실행하는 객체. 구현체는 예외 대신 `ToolError`를 돌려준다."""

    def call(self, name: str, args: Mapping[str, Any]) -> ToolResult: ...


class _ArgError(ValueError):
    """인자 파싱 실패. 어댑터 밖으로 새지 않고 `ToolError.invalid_input`으로 바뀐다."""


def _unknown_tool(name: str) -> ToolError:
    """LLM이 없는 도구 이름을 지어내는 것은 흔한 실패다 — 쓸 수 있는 이름을 같이 돌려줘야
    다음 턴에 고쳐 부를 수 있다."""
    known = ", ".join(sorted(LOCAL_TOOLS | HTTP_TOOLS))
    return ToolError.invalid_input(f"알 수 없는 도구 이름 '{name}'. 사용 가능: {known}")


def _require(args: Mapping[str, Any], key: str) -> Any:
    value = args.get(key)
    if value is None:
        raise _ArgError(f"필수 인자 '{key}'가 없다")
    return value


def _as_date(args: Mapping[str, Any], key: str = "date") -> date_type:
    """도구 스키마의 `date`는 'YYYY-MM-DD' 문자열이지만, 서비스 함수는 `datetime.date`를 받는다.
    변환을 어댑터가 맡는다 — 서비스 시그니처를 LLM 쪽 표현에 맞춰 흔들지 않기 위해서다."""
    value = _require(args, key)
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date_type):
        return value
    try:
        return date_type.fromisoformat(str(value))
    except ValueError as exc:
        raise _ArgError(f"'{key}'는 YYYY-MM-DD 형식이어야 한다 (받은 값: {value!r})") from exc


def _as_int(args: Mapping[str, Any], key: str) -> int:
    value = _require(args, key)
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise _ArgError(f"'{key}'는 정수여야 한다 (받은 값: {value!r})") from exc


def _as_float(args: Mapping[str, Any], key: str) -> float:
    value = _require(args, key)
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise _ArgError(f"'{key}'는 숫자여야 한다 (받은 값: {value!r})") from exc


def _now_kst_iso() -> str:
    """BE DTO의 `requestedAt`(offset 포함 ISO-8601). AI EC2의 OS 시간대가 UTC라
    `datetime.now()`를 그냥 쓰면 KST 기준인 BE 데이터와 9시간 어긋난다 — 시간대를 명시한다."""
    return datetime.now(KST).isoformat(timespec="seconds")


def _jsonable(value: Any) -> Any:
    """도구 결과를 JSON 직렬화 가능한 모양으로 맞춘다.

    CROWD 서비스는 `date` 컬럼을 `datetime.date` 객체 그대로 돌려주는데, 도구 결과는 그대로
    LLM 요청 body로 나가므로 `json.dumps`에서 터진다. 값을 바꾸는 게 아니라 **선언한 스키마의
    표현으로 맞추는 것**이다 — `registry.TOOLS`의 output_schema가 `{"format": "date"}` 문자열로
    약속하고 있다. 없는 값을 채우거나 숫자를 손대지는 않는다.
    """
    if isinstance(value, datetime):
        return value.isoformat(timespec="seconds")
    if isinstance(value, date_type):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


class LocalAdapter:
    """CROWD·BIKE 서비스 함수를 같은 프로세스에서 직접 부른다.

    `app.CROWD.service` / `app.BIKE.service`는 pandas와 모델 아티팩트를 끌어오므로 **모듈
    최상단에서 import하지 않고 호출 시점에 지연 import한다** — 도구 계층을 import했다는
    이유만으로 서빙 프로세스의 기동이 느려지는 것을 막는다(AI/CLAUDE.md 서빙 경로 규약).
    """

    def call(self, name: str, args: Mapping[str, Any]) -> ToolResult:
        if name not in LOCAL_TOOLS:
            return _unknown_tool(name)
        try:
            if name == GET_LINE_CONGESTION:
                return _jsonable(self._line_congestion(args))
            if name == GET_STATION_CONGESTION:
                return _jsonable(self._station_congestion(args))
            if name == GET_ETA_STOCK:
                return _jsonable(self._eta_stock(args))
            return _unknown_tool(name)  # LOCAL_TOOLS에 이름이 늘었는데 분기를 안 붙인 경우
        except _ArgError as exc:
            return ToolError.invalid_input(str(exc))
        except Exception as exc:  # noqa: BLE001 - 불변식 유지가 목적이라 의도적으로 넓다
            # "도구는 예외를 던지지 않는다"(schemas.py)를 여기서 완성한다. 위 except들이
            # 번역하는 건 *예상한* 실패뿐이라, 서비스가 새 예외를 추가하면(예: AvgDataMissing)
            # 그대로 새어나가 에이전트 루프를 죽인다. 어느 예외가 샐지 미리 알 수 없으므로
            # 마지막 그물을 친다. 가드가 아니라 어댑터에 두는 이유: 가드 없이 어댑터만 쓰는
            # 호출 경로(203 PoC·테스트)에서도 불변식이 지켜져야 한다.
            return ToolError.upstream_unavailable(
                f"'{name}' 실행 중 예상 못 한 오류({type(exc).__name__}): {exc}"
            )

    def _line_congestion(self, args: Mapping[str, Any]) -> ToolResult:
        from app.CROWD import service as crowd_service  # 지연 import (pandas)

        day = _as_date(args)
        line = str(_require(args, "line"))
        time_slot = str(_require(args, "time_slot_30min"))
        result = crowd_service.line_congestion(day, line, time_slot)
        if result is None:
            return self._no_table(day)
        return result

    def _station_congestion(self, args: Mapping[str, Any]) -> ToolResult:
        from app.CROWD import service as crowd_service  # 지연 import (pandas)

        day = _as_date(args)
        station_no = _as_int(args, "station_no")
        direction = args.get("direction")
        result = crowd_service.station_congestion(
            day, station_no, str(direction) if direction else None
        )
        if result is None:
            return self._no_table(day)
        return result

    @staticmethod
    def _no_table(day: date_type) -> ToolError:
        """CROWD 서비스의 `None`은 "그 날짜 예측 표 자체가 없다"(= 배치 미실행)는 뜻이다.
        역이 없는 경우는 `None`이 아니라 빈 `slots`/`stations`로 오므로 둘이 섞이지 않는다.
        배치 미실행은 다시 물어봐도 같은 답이라 retryable=False인 `NOT_FOUND`가 맞다 —
        detail에 이유를 적어둬야 에이전트가 같은 날짜로 재시도하지 않는다."""
        return ToolError.not_found(
            f"{day.isoformat()} 혼잡도 예측 표가 없다 — 그 날짜 배치가 실행되지 않았다. "
            "다른 날짜를 쓰거나 혼잡도 근거 없이 판단할 것."
        )

    def _eta_stock(self, args: Mapping[str, Any]) -> ToolResult:
        from app.BIKE import service as bike_service  # 지연 import (pandas·모델 아티팩트)

        rental_id = str(_require(args, "rental_id"))
        eta_minutes = _as_int(args, "eta_minutes")
        try:
            return bike_service.predict_eta_stock(rental_id, eta_minutes)
        except bike_service.LiveStockMissing as exc:
            # 실시간 스냅샷에 그 대여소가 없거나 값이 오래됐다 — "없다"는 것은 확인된 상태다.
            return ToolError.not_found(f"{rental_id} 실시간 재고를 확인할 수 없다: {exc}")
        except bike_service.ModelUnavailable as exc:
            # 모델 아티팩트 장애. 재고가 얼마인지 "모르는" 상태라 NOT_FOUND와 구분한다.
            return ToolError.upstream_unavailable(f"따릉이 예측 모델을 쓸 수 없다: {exc}")


class HttpAdapter:
    """BE HTTP API를 부른다.

    `base_url`이 없어도 **생성·import는 성공한다.** BE 주소가 아직 확정되지 않았고
    (`TO_BE-time-reroute-contract-01` 회신 대기), 주소가 없다는 이유로 도구 계층 전체가
    죽으면 로컬 도구 3종까지 같이 못 쓰게 된다. 주소 미설정은 호출 시점에
    `UPSTREAM_UNAVAILABLE`로 드러낸다 — 에이전트 입장에서 "BE가 안 뜬 것"과 같은 상황이다.
    """

    def __init__(
        self,
        base_url: str | None = None,
        timeout: float = DEFAULT_HTTP_TIMEOUT_SECONDS,
    ) -> None:
        self.base_url = (base_url or "").rstrip("/")
        self.timeout = timeout

    def call(self, name: str, args: Mapping[str, Any]) -> ToolResult:
        if name not in HTTP_TOOLS:
            return _unknown_tool(name)
        if not self.base_url:
            return ToolError.upstream_unavailable(
                f"BE base_url이 설정되지 않아 '{name}'을 호출할 수 없다 — BE 주소 확정 대기 중."
            )

        try:
            request = self._build(name, args)
        except _ArgError as exc:
            return ToolError.invalid_input(str(exc))

        try:
            response = requests.request(timeout=self.timeout, **request)
        except (requests.Timeout, requests.ConnectionError) as exc:
            # 요청이 닿지 않았거나 응답을 못 받았다 — 답이 없는지 늦은 건지 모르므로 재시도 가치가 있다.
            return ToolError.upstream_unavailable(f"BE 호출 실패({type(exc).__name__}): {exc}")
        except requests.RequestException as exc:
            return ToolError.upstream_unavailable(f"BE 호출 실패: {exc}")

        if response.status_code >= 400:
            return self._error_for_status(name, response)

        try:
            payload = response.json()
        except ValueError:
            return ToolError.upstream_unavailable(f"BE '{name}' 응답이 JSON이 아니다")
        except Exception as exc:  # noqa: BLE001 - LocalAdapter.call과 같은 이유의 마지막 그물
            # requests 구현체가 ValueError 밖의 예외를 던지는 경우(응답 스트림 끊김 등).
            return ToolError.upstream_unavailable(
                f"BE '{name}' 응답 해석 실패({type(exc).__name__}): {exc}"
            )
        return _unwrap(payload)

    def _build(self, name: str, args: Mapping[str, Any]) -> dict[str, Any]:
        """`requests.request()` 인자를 만든다. 도구 스키마는 snake_case, BE DTO는 camelCase라
        그 변환이 여기서 한 번만 일어난다 — 호출부마다 키를 다시 쓰면 한쪽만 고쳐져 엇갈린다."""
        if name == GET_ARRIVALS:
            params: dict[str, Any] = {"stationId": str(_require(args, "station_id"))}
            route_id = args.get("route_id")
            if route_id is not None:
                params["routeId"] = str(route_id)
            return {
                "method": "GET",
                "url": f"{self.base_url}/api/transit/arrivals",
                "params": params,
            }

        if name == BIKE_STATIONS_NEARBY:
            params = {
                "lat": _as_float(args, "lat"),
                "lng": _as_float(args, "lng"),
            }
            # radius_meters·limit은 선택값이다 — modes·priority와 같은 이유로 None이면 키
            # 자체를 뺀다(BE 기본값 500m/20건이 적용되게 한다).
            radius_meters = args.get("radius_meters")
            if radius_meters is not None:
                params["radiusMeters"] = radius_meters
            limit = args.get("limit")
            if limit is not None:
                params["limit"] = limit
            return {
                "method": "GET",
                "url": f"{self.base_url}/api/bike-stations/nearby",
                "params": params,
            }

        if name != REPLAN_ROUTE:  # HTTP_TOOLS에 이름이 늘었는데 분기를 안 붙인 경우
            raise _ArgError(f"HTTP 어댑터가 처리할 줄 모르는 도구 '{name}'")

        body: dict[str, Any] = {
            "step": _as_int(args, "step"),
            "boundaryId": str(_require(args, "boundary_id")),
            "destStationId": str(_require(args, "dest_station_id")),
            "requestedAt": _now_kst_iso(),
        }
        # modes·priority는 선택값이다. None을 그대로 보내지 않고 키를 빼서 BE 기본값
        # (전 수단 / fast)이 적용되게 한다 — 명시적 null과 미지정을 BE가 다르게 볼 수 있다.
        modes = args.get("modes")
        if modes is not None:
            body["modes"] = list(modes)
        priority = args.get("priority")
        if priority is not None:
            body["priority"] = str(priority)
        return {"method": "POST", "url": f"{self.base_url}/api/routes/replan", "json": body}

    @staticmethod
    def _error_for_status(name: str, response: Any) -> ToolError:
        """HTTP 상태코드를 ToolErrorCode로 옮긴다. 404만 "없다"(NOT_FOUND)이고 나머지 실패는
        전부 "모른다"(UPSTREAM_UNAVAILABLE)로 본다 — 서버가 답을 못 준 것을 '대안 없음'으로
        읽으면 에이전트가 없는 사실을 단정하게 된다."""
        status = response.status_code
        detail = f"BE '{name}' 응답 {status}: {_snippet(response)}"
        if status == 404:
            return ToolError.not_found(detail)
        if status == 400:
            return ToolError.invalid_input(detail)
        return ToolError.upstream_unavailable(detail)


def _snippet(response: Any, limit: int = 200) -> str:
    """오류 본문 앞부분. 그대로 LLM 입력에 들어가므로 길이를 자른다."""
    try:
        return str(response.text)[:limit]
    except Exception:
        # 본문을 못 읽는 것(인코딩 깨짐 등)이 오류 보고 자체를 막으면 안 된다.
        return "(본문 없음)"


def _unwrap(payload: Any) -> Any:
    """BE 공통 응답 래퍼(`ApiResult`)를 벗긴다.

    BE는 `{"data": ...}` 형태로 감싸 주는 엔드포인트와 본문을 그대로 주는 엔드포인트가 섞여
    있다. 둘을 어댑터에서 흡수해 도구 출력은 항상 `registry.TOOLS`의 output_schema 모양이
    되게 한다 — 래퍼 유무를 LLM이 판단하게 두면 프롬프트마다 다르게 읽는다.
    `data` 키가 없으면 응답 전체를 그대로 돌려준다.
    """
    if isinstance(payload, dict) and "data" in payload:
        return payload["data"]
    return payload


class CompositeAdapter:
    """도구 이름을 보고 Local/Http 중 맞는 쪽으로 보내는 진입점.

    에이전트 루프(203)는 도구가 어느 경로인지 알 필요가 없다. 로컬/HTTP 구분은 배치 사정이지
    도구의 의미가 아니므로, 그 지식을 여기 한곳에 가둔다.
    """

    def __init__(self, local: ToolAdapter | None = None, http: ToolAdapter | None = None) -> None:
        self.local = local if local is not None else LocalAdapter()
        self.http = http if http is not None else HttpAdapter()

    def call(self, name: str, args: Mapping[str, Any]) -> ToolResult:
        if name in LOCAL_TOOLS:
            return self.local.call(name, args)
        if name in HTTP_TOOLS:
            return self.http.call(name, args)
        return _unknown_tool(name)


__all__ = [
    "DEFAULT_HTTP_TIMEOUT_SECONDS",
    "CompositeAdapter",
    "HttpAdapter",
    "LocalAdapter",
    "ToolAdapter",
    "ToolResult",
]
