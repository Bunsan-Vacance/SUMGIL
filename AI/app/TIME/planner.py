"""도구 프리페치(S15P21A104-203) — ③.

LLM에 넘기기 전에 **필요한 조회를 여기서 다 끝낸다.** 에이전트가 스스로 도구를 고르게 하면
LLM 턴이 2~3회(5~15초)가 되는데, 트리거(①)가 이미 "어느 역이 문제인지"를 알고 있어서 그럴
이유가 없다. 결과를 한 번에 모아 주면 LLM은 1턴으로 끝난다(계획 1.1절). 같은 이유로
`AgentContext`는 두 전략(`RuleStrategy`·`AgentStrategy`)의 **완전히 같은 입력**이 된다 —
7절 비교의 동등 조건이 이 파일에서 보장된다(`AI/CLAUDE.md` 모델 비교 하드 룰 2·3번).

여기서 하는 일은 둘이다.

- `readings_for_trigger` — 앞쪽 역들의 '지금 vs 도착할 때' 혼잡도를 읽어 `StationReading`으로 만든다.
- `prefetch` — 하차 후보마다 잔여 경로를 순차로 받아 `AgentContext`를 조립한다.

**값을 지어내지 않는다.** 조회가 실패하거나 응답에 그 역이 없으면 그 자리는 `None`으로 두고
상태값으로 알린다. 실패를 빈 목록으로 감추지 않는 것도 같은 원칙이다(`CandidateContext.error`).

어댑터·가드는 **인자로 받는다.** 가드는 세션(요청 하나의 루프) 단위 인스턴스라 이 모듈이 만들면
예산이 사용자 사이에 섞인다(`guard.py` 첫 문단).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date as date_type
from datetime import datetime, timedelta
from typing import Any

from app.TIME.adapters import ToolAdapter, ToolResult
from app.TIME.context import AgentContext, CandidateContext, DropCandidate, Stop
from app.TIME.guard import ToolGuard
from app.TIME.registry import GET_LINE_CONGESTION, REPLAN_ROUTE
from app.TIME.schemas import ToolError, is_error
from app.TIME.trigger import STATUS_NO_DATA, SlotReading, StationReading, TriggerDecision

SLOT_MINUTES = 30
"""CROWD 예측 표의 슬롯 길이. `registry`의 `^([01][0-9]|2[0-3]):(00|30)$` 패턴과 같은 약속이다."""

STATUS_NOT_IN_RESPONSE = "not_in_response"
"""응답에는 표가 있는데 그 역 행이 없다.

CROWD 어휘(`SERVING_CONTRACT.md` 2절)에는 이 경우가 없다 — `no_lookup`은 '기준선이 없는 셀'이라
원인이 다른데 빌려 쓰면 둘이 뒤섞인다. 그래서 planner 전용 값을 둔다. `trigger`는
`USABLE_STATUSES` 밖의 값을 전부 결측으로 보므로 동작은 의도한 그대로다 — 그 역을 건너뛰되
연속 구간을 끊지는 않는다. `Stop.station_no`가 없어 조회 키를 만들 수 없는 역도 '응답에서 찾을 수
없다'는 점이 같아 이 값을 쓴다."""

STATUS_UNKNOWN = "unknown"
"""행은 왔는데 `data_status` 필드가 없다. 상태를 모르면 `ok`로 낙관하지 않는다 — 결측으로 본다."""


def slot_of(moment: datetime) -> str:
    """그 시각이 속한 30분 슬롯의 시작 시각('HH:MM')."""
    return f"{moment.hour:02d}:{moment.minute // SLOT_MINUTES * SLOT_MINUTES:02d}"


def readings_for_trigger(
    upcoming: Sequence[tuple[Stop, int]],
    *,
    adapter: ToolAdapter,
    guard: ToolGuard,
    line: str,
    now: datetime,
    direction: str | None = None,
) -> list[StationReading]:
    """앞쪽 역들의 '지금'과 '도착할 때' 혼잡도를 읽어 `trigger.evaluate`의 입력을 만든다.

    `upcoming`은 **(정차역, 도착까지 분) 쌍**을 진행 순서(가까운 역부터)로 받는다. `Stop`에
    eta를 넣지 않은 이유는 그 값이 역의 성질이 아니라 지금 타고 있는 열차의 성질이기 때문이고,
    `DropCandidate`를 쓰지 않은 이유는 그쪽이 ②의 **산출물**이라 ①의 입력으로 쓰면 의존이 거꾸로
    서기 때문이다. 반환 순서는 입력 순서를 그대로 지킨다 — 트리거의 연속 구간 판정이 순서에
    의존한다.

    **도구 호출 수가 이 함수의 핵심이다.** `get_line_congestion`은 노선 전체를 한 슬롯 단위로
    주므로 역마다 부를 필요가 없다. (날짜, 슬롯)로 캐시해 **현재 슬롯 1회 + 서로 다른 도착 슬롯
    수**만큼만 부른다. 앞쪽 10개 역이 두 슬롯에 걸쳐 있으면 3회다.

    날짜를 도착 시각에서 다시 뽑는 이유: 23:50에 15분 뒤 역은 **다음 날** 00:00 슬롯이고, CROWD
    표는 날짜별이라 같은 날로 물으면 다른 날 표를 읽는다.

    `direction`을 주면 그 방향 행만 쓴다. 안 주면 현재 슬롯 응답에서 한 번 고르고 **도착 슬롯에도
    같은 방향을 쓴다** — 상승폭은 같은 방향끼리 빼야 의미가 있고, 슬롯마다 따로 고르면 상선/하선이
    섞인 차이를 혼잡 급등으로 읽게 된다.
    """
    if not upcoming:
        return []  # 물어볼 역이 없으면 호출도 하지 않는다

    lookups: dict[tuple[str, str], ToolResult] = {}

    def lookup(on: date_type, slot: str) -> ToolResult:
        key = (on.isoformat(), slot)
        if key not in lookups:  # `None`이 실패 표시가 아니므로 키 존재로 판단한다
            args = {"date": key[0], "line": line, "time_slot_30min": slot}
            lookups[key] = guard.run(
                GET_LINE_CONGESTION, lambda: adapter.call(GET_LINE_CONGESTION, args), args
            )
        return lookups[key]

    now_slot = slot_of(now)
    now_rows = _rows_by_station(lookup(now.date(), now_slot))

    readings: list[StationReading] = []
    for stop, eta_minutes in upcoming:
        arrival = now + timedelta(minutes=eta_minutes)
        arrival_slot = slot_of(arrival)
        arrival_rows = _rows_by_station(lookup(arrival.date(), arrival_slot))
        readings.append(
            _reading(
                stop,
                eta_minutes,
                now_slot=now_slot,
                now_rows=now_rows,
                arrival_slot=arrival_slot,
                arrival_rows=arrival_rows,
                direction=direction,
            )
        )
    return readings


def prefetch(
    decision: TriggerDecision,
    candidates: Sequence[DropCandidate],
    *,
    adapter: ToolAdapter,
    guard: ToolGuard,
    dest_station_id: str,
    step: int = 0,
    current_route_id: str | None = None,
    modes: Sequence[str] | None = None,
    priority: str | None = None,
) -> AgentContext:
    """후보마다 `replan_route`를 불러 잔여 경로를 모으고 `AgentContext`를 만든다.

    **순차로 부른다.** 원래는 스레드 풀로 병렬 호출했다(대기 시간을 줄이는 게 목적이었다). BE
    회신(`FROM_BE-time-reroute-contract-01` 8번)에 따르면 prod BE는 CPU 1개 전제라 동시에 쏴도 BE
    스레드에서 실질적으로 줄을 서고, 오히려 한 재안내 요청이 BE 스레드 여러 개를 동시에 점유해
    일반 탐색 요청을 굶긴다 — 그래서 BE가 클라이언트(여기) 쪽 순차 호출을 명시적으로 권했다.
    결과 순서는 후보 순서를 지킨다(순차 호출이라 이제는 자연히 보장된다) — 후보 순서에
    `rank_hint`가 들어 있고, 전략이 `chosen_index`로 후보를 가리킨다(6.2절).

    `step`은 원본 legs 인덱스다. 후보역이 legs의 몇 번째 구간에 속하는지는 정차역 목록 공급원이
    정해져야 알 수 있어(`TO_BE-time-station-sequence-01`) 지금은 호출자가 넘기는 값을 모든 후보에
    같이 쓴다.
    """
    context_of = _replan_caller(
        adapter=adapter,
        guard=guard,
        dest_station_id=dest_station_id,
        step=step,
        current_route_id=current_route_id,
        modes=modes,
        priority=priority,
    )

    contexts: list[CandidateContext] = [context_of(candidate) for candidate in candidates]

    return AgentContext(
        decision=decision,
        candidates=contexts,
        current_route_id=current_route_id,
        dest_station_id=dest_station_id,
    )


# ── 내부: 혼잡도 읽기 ──


def _rows_by_station(result: ToolResult) -> dict[int, list[Mapping[str, Any]]] | None:
    """`get_line_congestion` 응답을 역번호별 행 목록으로 바꾼다.

    `None`은 **"조회하지 못했다"**를 뜻하고(오류이거나 스키마와 다른 응답), 빈 dict는 "표는 받았는데
    행이 없다"를 뜻한다. 둘을 섞으면 실패가 '혼잡하지 않음'으로 읽힌다.
    같은 역이 상·하선 두 행으로 오므로 값 하나가 아니라 목록으로 담는다.
    """
    if is_error(result) or not isinstance(result, Mapping):
        return None
    grouped: dict[int, list[Mapping[str, Any]]] = {}
    for row in result.get("stations") or []:
        if not isinstance(row, Mapping):
            continue
        try:
            station_no = int(row["station_no"])
        except (KeyError, TypeError, ValueError):
            continue  # 역번호를 못 읽는 행은 어느 역인지 모른다 — 추측해서 붙이지 않는다
        grouped.setdefault(station_no, []).append(row)
    return grouped


def _reading(
    stop: Stop,
    eta_minutes: int,
    *,
    now_slot: str,
    now_rows: dict[int, list[Mapping[str, Any]]] | None,
    arrival_slot: str,
    arrival_rows: dict[int, list[Mapping[str, Any]]] | None,
    direction: str | None,
) -> StationReading:
    """역 하나의 `StationReading`. 못 찾은 역도 **빼지 않고** 값을 비워 만든다.

    빼면 트리거가 보는 목록이 짧아져 결측이 "여기는 문제없다"처럼 보이고, 연속 구간 판정의
    이웃 관계도 어긋난다. 남겨 두면 `trigger._alerting_runs`가 결측으로 건너뛴다(끊지도, 세지도
    않는다). 이 정책은 계획 3절 결측 표와 같은 판단이다.
    """
    if stop.station_no is None:
        # 조회 키가 없어 응답에서 찾을 수조차 없다(`context.Stop`의 두 ID는 둘 다 nullable이다).
        # `StationReading.station_no`는 필수 int라 자리표시자 -1을 넣는데, 이 역은 상태가
        # 결측이라 `comparable`이 False고 따라서 구간에 들어가지 못한다 — `_facts`가 인용하는
        # 숫자에 -1이 새어나갈 경로가 없다.
        return StationReading(
            station_no=-1,
            station_name=stop.name,
            eta_minutes=eta_minutes,
            now=_missing(now_slot, STATUS_NOT_IN_RESPONSE),
            on_arrival=_missing(arrival_slot, STATUS_NOT_IN_RESPONSE),
        )

    now_row, resolved_direction = _pick_row(now_rows, stop.station_no, direction)
    arrival_row, _ = _pick_row(arrival_rows, stop.station_no, resolved_direction)
    return StationReading(
        station_no=stop.station_no,
        station_name=stop.name or _name_of(now_row) or _name_of(arrival_row),
        eta_minutes=eta_minutes,
        now=_slot_reading(now_slot, now_row, now_rows),
        on_arrival=_slot_reading(arrival_slot, arrival_row, arrival_rows),
    )


def _pick_row(
    rows: dict[int, list[Mapping[str, Any]]] | None,
    station_no: int,
    direction: str | None,
) -> tuple[Mapping[str, Any] | None, str | None]:
    """역·방향에 맞는 행 하나와 실제로 고른 방향.

    요청한 방향이 없으면 **다른 방향 행으로 대체하지 않는다** — 반대 방향 혼잡도는 이 사용자가
    겪을 값이 아니다. 방향이 지정되지 않았으면 첫 행을 쓰고 그 방향을 돌려준다 — 더 혼잡한 쪽을
    고르면 트리거가 방향 선택만으로 더 자주 뜬다. 첫 행이 임의값이 아닌 이유는
    `app.CROWD.service.line_congestion`이 `direction`·`station_no`로 정렬해 주기 때문이다.
    """
    if rows is None:
        return None, direction
    for row in rows.get(station_no) or []:
        row_direction = row.get("direction")
        if direction is None:
            return row, (str(row_direction) if row_direction is not None else None)
        if str(row_direction) == direction:
            return row, direction
    return None, direction


def _slot_reading(
    slot: str,
    row: Mapping[str, Any] | None,
    rows: dict[int, list[Mapping[str, Any]]] | None,
) -> SlotReading:
    """행 하나를 `SlotReading`으로. 상태값으로 '왜 비었는지'를 남긴다."""
    if rows is None:
        # 조회 자체가 실패했다(ToolError·스키마 불일치). `no_data`를 쓰면 트리거가 조건을 보기
        # 전에 접어서 `SKIP_NO_DATA`("판단할 근거가 없다")로 끝난다 — 이게 맞는 결말이다.
        # 결측 셀처럼 처리하면 그 역만 빠지고 나머지로 트리거가 떠서 "일부만 보고 판정"이 되거나,
        # 아무것도 비교할 수 없을 때 `SKIP_BELOW_THRESHOLD`("확인했는데 잠잠하다")로 나가
        # 조회 실패를 '혼잡하지 않음'으로 읽게 된다. 실패의 실제 원인 코드는 가드 호출 로그
        # (`ToolCallLog.result_code`)에 남으므로 여기서 잃지 않는다.
        return _missing(slot, STATUS_NO_DATA)
    if row is None:
        return _missing(slot, STATUS_NOT_IN_RESPONSE)
    status = row.get("data_status")
    return SlotReading(
        time_slot_30min=slot,
        congestion_pct=_as_float(row.get("congestion_pct")),
        grade=_as_int(row.get("grade")),
        data_status=str(status) if status else STATUS_UNKNOWN,
    )


def _missing(slot: str, status: str) -> SlotReading:
    return SlotReading(time_slot_30min=slot, congestion_pct=None, grade=None, data_status=status)


def _name_of(row: Mapping[str, Any] | None) -> str | None:
    if row is None:
        return None
    name = row.get("station_name")
    return str(name) if name else None


def _as_float(value: Any) -> float | None:
    """숫자로 못 읽는 값은 0이 아니라 `None`이다 — 결측을 0으로 바꾸면 하락으로 세어진다."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


# ── 내부: 잔여 경로 프리페치 ──


def _replan_caller(
    *,
    adapter: ToolAdapter,
    guard: ToolGuard,
    dest_station_id: str,
    step: int,
    current_route_id: str | None,
    modes: Sequence[str] | None,
    priority: str | None,
):
    """후보 하나를 `CandidateContext`로 바꾸는 함수를 만든다(스레드 풀에 넘길 단위)."""

    def call(candidate: DropCandidate) -> CandidateContext:
        boundary_id = candidate.stop.station_id
        if boundary_id is None:
            # `station_id`는 nullable이다(`context.Stop`). 조회를 못 한 것도 결과이므로
            # 빈 후보로 조용히 흘리지 않고 오류로 남긴다.
            return CandidateContext(
                candidate=candidate,
                error=_as_error_dict(
                    ToolError.invalid_input(
                        f"후보역(seq={candidate.stop.seq})에 station_id가 없어 "
                        "replan_route를 부를 수 없다 — 역 ID 대응 규칙 확정 대기"
                    )
                ),
            )

        args: dict[str, Any] = {
            "step": step,
            "boundary_id": boundary_id,
            "dest_station_id": dest_station_id,
        }
        # None을 키로 넣지 않는 이유는 어댑터와 같다 — BE 기본값을 쓰게 둔다.
        if modes is not None:
            args["modes"] = list(modes)
        if priority is not None:
            args["priority"] = priority

        result = guard.run(REPLAN_ROUTE, lambda: adapter.call(REPLAN_ROUTE, args), args)
        if is_error(result):
            return CandidateContext(candidate=candidate, error=_as_error_dict(result))
        if not isinstance(result, list):
            # `replan_route`의 output_schema는 배열이다. 다른 모양이 오면 읽는 법을 지어내지 않고
            # 실패로 남긴다 — 잘못 해석한 경로를 안내하는 것보다 대안이 없는 편이 낫다.
            return CandidateContext(
                candidate=candidate,
                error=_as_error_dict(
                    ToolError.upstream_unavailable(
                        f"replan_route 응답이 배열이 아니다(type={type(result).__name__})"
                    )
                ),
            )

        routes = list(result)
        if current_route_id:
            # `exclude_route_ids`를 BE에 요청해 뒀지만 회신 전이라 사후 필터링한다
            # (`TO_BE-time-reroute-contract-01` 1번). 회신이 오면 이 블록을 지우고 요청
            # 파라미터로 옮긴다 — 그때는 BE가 아예 탐색에서 빼므로 대안 수가 늘어난다.
            routes = [alt for alt in routes if not _uses_route(alt, current_route_id)]
        # 필터 후 0개는 실패가 아니라 "대안 없음"이다. `error`를 채우지 않아야
        # `CandidateContext.usable`이 둘을 구분해 준다.
        return CandidateContext(candidate=candidate, routes=routes)

    return call


def _uses_route(alternative: Any, route_id: str) -> bool:
    """이 대안이 지금 타고 있는 노선을 다시 쓰는지. legs의 `routeId`로 본다.

    판단할 수 없으면(legs가 없거나 모양이 다르면) **버리지 않는다** — 읽지 못한 것을 '같은 노선'으로
    단정하면 멀쩡한 대안이 사라진다.
    """
    for leg in _legs_of(alternative):
        if not isinstance(leg, Mapping):
            continue
        leg_route = leg.get("routeId")
        if leg_route is not None and str(leg_route) == route_id:
            return True
    return False


def _legs_of(alternative: Any) -> list[Any]:
    """대안 하나의 legs. BE 응답은 `{reason, source, route:{legs}}`지만, 래퍼 없이 경로 객체가
    그대로 오는 경우도 받아 둔다 — 응답 모양이 회신 대기 중이라(`TO_BE-time-reroute-contract-01`)
    한쪽만 보면 필터가 조용히 통과된다."""
    if not isinstance(alternative, Mapping):
        return []
    route = alternative.get("route")
    legs = route.get("legs") if isinstance(route, Mapping) else alternative.get("legs")
    return legs if isinstance(legs, list) else []


def _as_error_dict(result: Any) -> dict[str, Any]:
    """`ToolError`든 직렬화된 dict든 `CandidateContext.error`가 담을 모양으로 맞춘다.

    로컬 어댑터는 객체를, HTTP 경로는 dict를 돌려줄 수 있어 양쪽을 다 받는다
    (`guard.result_code_of`와 같은 이유).
    """
    if isinstance(result, ToolError):
        return result.model_dump(mode="json")
    if isinstance(result, Mapping):
        return dict(result)
    return {"error": "UPSTREAM_UNAVAILABLE", "detail": str(result), "retryable": True}


__all__ = [
    "SLOT_MINUTES",
    "STATUS_NOT_IN_RESPONSE",
    "STATUS_UNKNOWN",
    "prefetch",
    "readings_for_trigger",
    "slot_of",
]
