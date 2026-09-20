"""도구 프리페치 검증(S15P21A104-203).

여기서 고정하려는 것은 넷이다.

1. **호출 수** — `get_line_congestion`은 노선 전체를 한 슬롯 단위로 주므로 역 수가 아니라
   슬롯 수만큼만 불러야 한다. 이 성질이 깨지면 폴링마다 BE·CROWD 호출이 역 수만큼 늘어난다.
2. **값을 지어내지 않는다** — 조회 실패·응답에 없는 역이 값으로 채워지지 않고 상태로 드러나는지.
3. **실패를 감추지 않는다** — 후보 하나가 실패해도 나머지가 살아남고, 그 실패가 `error`에 남는지.
4. **사후 필터링** — `exclude_route_ids` 회신 전까지 현재 노선을 쓰는 경로를 걸러내는지.

테스트는 **실제 네트워크·parquet·LLM을 쓰지 않는다.** 어댑터는 호출을 기록하고 미리 정한 응답을
돌려주는 가짜다(202 `test_time_adapters.py`와 같은 방침).
"""

from __future__ import annotations

import threading
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from app.TIME.context import DropCandidate, Stop
from app.TIME.guard import ToolGuard
from app.TIME.planner import (
    STATUS_NOT_IN_RESPONSE,
    prefetch,
    readings_for_trigger,
    slot_of,
)
from app.TIME.registry import GET_LINE_CONGESTION, REPLAN_ROUTE
from app.TIME.schemas import ToolError, ToolErrorCode
from app.TIME.trigger import SKIP_NO_DATA, STATUS_NO_DATA, TriggerDecision, evaluate

NOW = datetime(2026, 9, 20, 8, 20)
"""고정 시각. 08:20이면 현재 슬롯은 08:00이고 15분 뒤는 08:30 슬롯이다."""

DECISION = TriggerDecision(fired=True)
"""프리페치는 트리거 판정을 그대로 싣고 다니기만 한다 — 내용은 이 파일의 관심사가 아니다."""


# ── 가짜 어댑터 ──


class FakeAdapter:
    """도구 이름·인자를 기록하고 미리 정한 응답을 돌려준다.

    `replan_route`는 스레드 풀에서 동시에 불리므로 기록에 락을 건다 — 호출 수를 세는 테스트가
    경쟁 때문에 드물게 틀리는 일을 막는다.
    """

    def __init__(
        self,
        *,
        line: Mapping[tuple[str, str], Any] | None = None,
        replan: Mapping[str, Any] | None = None,
    ) -> None:
        self.line = dict(line or {})
        self.replan = dict(replan or {})
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self._lock = threading.Lock()

    def call(self, name: str, args: Mapping[str, Any]) -> Any:
        with self._lock:
            self.calls.append((name, dict(args)))
        if name == GET_LINE_CONGESTION:
            key = (str(args["date"]), str(args["time_slot_30min"]))
            return self.line.get(key, _line_response(key[0], key[1], []))
        if name == REPLAN_ROUTE:
            return self.replan.get(str(args["boundary_id"]), [])
        return ToolError.invalid_input(f"가짜 어댑터가 모르는 도구 '{name}'")

    def names(self, name: str) -> list[dict[str, Any]]:
        return [args for called, args in self.calls if called == name]


def _line_response(date: str, slot: str, stations: list[dict[str, Any]]) -> dict[str, Any]:
    return {"date": date, "line": "2호선", "time_slot_30min": slot, "stations": stations}


def _station_row(
    station_no: int,
    *,
    pct: float = 50.0,
    grade: int = 1,
    status: str = "ok",
    direction: str = "내선",
) -> dict[str, Any]:
    return {
        "station_no": station_no,
        "station_name": f"역{station_no}",
        "direction": direction,
        "congestion_pct": pct,
        "grade": grade,
        "data_status": status,
        "pred_source": "model",
    }


def _stop(seq: int, *, station_no: int | None = None, station_id: str | None = None) -> Stop:
    return Stop(
        seq=seq,
        station_id=station_id if station_id is not None else f"S{seq}",
        station_no=station_no if station_no is not None else 200 + seq,
        name=f"역{200 + seq}",
    )


def _candidate(seq: int, **kwargs: Any) -> DropCandidate:
    return DropCandidate(stop=_stop(seq, **kwargs), eta_minutes=seq * 2)


def _route(route_id: str, *, minutes: float = 12.0) -> dict[str, Any]:
    """BE `replan` 대안 하나. legs의 `routeId`가 사후 필터링의 판단 근거다."""
    return {
        "reason": "테스트용 대안",
        "source": "ALGORITHM",
        "route": {
            "totalMinutes": minutes,
            "legs": [
                {"mode": "SUBWAY", "routeId": route_id, "fromNodeId": "A", "toNodeId": "B"},
            ],
        },
    }


def _guard() -> ToolGuard:
    return ToolGuard()


# ── 슬롯 계산 ──


def test_슬롯은_30분_단위_시작_시각으로_내림한다():
    assert slot_of(datetime(2026, 9, 20, 8, 0)) == "08:00"
    assert slot_of(datetime(2026, 9, 20, 8, 29, 59)) == "08:00"
    assert slot_of(datetime(2026, 9, 20, 8, 30)) == "08:30"
    assert slot_of(datetime(2026, 9, 20, 0, 5)) == "00:00"
    assert slot_of(datetime(2026, 9, 20, 23, 59)) == "23:30"


def test_도착_슬롯은_eta를_더한_시각으로_정해진다():
    adapter = FakeAdapter(
        line={
            ("2026-09-20", "08:00"): _line_response("2026-09-20", "08:00", [_station_row(201)]),
            ("2026-09-20", "08:30"): _line_response("2026-09-20", "08:30", [_station_row(201)]),
        }
    )

    readings = readings_for_trigger(
        [(_stop(1, station_no=201), 15)],
        adapter=adapter,
        guard=_guard(),
        line="2호선",
        now=NOW,  # 08:20 + 15분 = 08:35 → 08:30 슬롯
    )

    assert readings[0].now.time_slot_30min == "08:00"
    assert readings[0].on_arrival.time_slot_30min == "08:30"


def test_자정을_넘는_도착은_다음_날_표를_조회한다():
    """CROWD 표는 날짜별이라 같은 날로 물으면 다른 날 값을 읽는다."""
    adapter = FakeAdapter()

    readings = readings_for_trigger(
        [(_stop(1, station_no=201), 15)],
        adapter=adapter,
        guard=_guard(),
        line="2호선",
        now=datetime(2026, 9, 20, 23, 50),
    )

    dates = {args["date"] for args in adapter.names(GET_LINE_CONGESTION)}
    assert dates == {"2026-09-20", "2026-09-21"}
    assert readings[0].on_arrival.time_slot_30min == "00:00"


# ── 호출 수 ──


def test_역이_많아도_서로_다른_슬롯_수만큼만_조회한다():
    """`get_line_congestion`은 노선 전체를 한 슬롯 단위로 준다 — 역마다 부르면 안 된다."""
    rows = [_station_row(200 + i) for i in range(1, 11)]
    adapter = FakeAdapter(
        line={
            ("2026-09-20", "08:00"): _line_response("2026-09-20", "08:00", rows),
            ("2026-09-20", "08:30"): _line_response("2026-09-20", "08:30", rows),
            ("2026-09-20", "09:00"): _line_response("2026-09-20", "09:00", rows),
        }
    )
    # 앞쪽 10개 역: 절반은 08:30 슬롯, 절반은 09:00 슬롯에 도착한다.
    upcoming = [(_stop(i, station_no=200 + i), 15 if i <= 5 else 45) for i in range(1, 11)]

    readings = readings_for_trigger(
        upcoming, adapter=adapter, guard=_guard(), line="2호선", now=NOW
    )

    assert len(readings) == 10
    calls = adapter.names(GET_LINE_CONGESTION)
    assert len(calls) == 3  # 현재 슬롯 1 + 도착 슬롯 2
    assert {args["time_slot_30min"] for args in calls} == {"08:00", "08:30", "09:00"}


def test_조회할_역이_없으면_도구를_아예_부르지_않는다():
    adapter = FakeAdapter()

    assert readings_for_trigger([], adapter=adapter, guard=_guard(), line="2호선", now=NOW) == []
    assert adapter.calls == []


# ── 결측 처리 ──


def test_응답에_없는_역은_빼지_않고_값만_비운다():
    """빼면 트리거가 보는 목록이 짧아져 결측이 '문제없음'처럼 보인다. 남기면 결측으로 건너뛴다."""
    present = [_station_row(201), _station_row(203)]
    adapter = FakeAdapter(
        line={
            ("2026-09-20", "08:00"): _line_response("2026-09-20", "08:00", present),
            ("2026-09-20", "08:30"): _line_response("2026-09-20", "08:30", present),
        }
    )
    upcoming = [(_stop(i, station_no=200 + i), 15) for i in (1, 2, 3)]

    readings = readings_for_trigger(
        upcoming, adapter=adapter, guard=_guard(), line="2호선", now=NOW
    )

    assert [r.station_no for r in readings] == [201, 202, 203]
    missing = readings[1]
    assert missing.now.congestion_pct is None and missing.now.grade is None
    assert missing.now.data_status == STATUS_NOT_IN_RESPONSE
    assert missing.on_arrival.data_status == STATUS_NOT_IN_RESPONSE
    assert not missing.comparable  # 트리거가 결측으로 건너뛴다
    assert readings[0].comparable and readings[2].comparable


def test_조회가_실패하면_값을_지어내지_않고_판단_근거_없음이_된다():
    adapter = FakeAdapter(
        line={
            ("2026-09-20", "08:00"): ToolError.upstream_unavailable("CROWD 표를 읽지 못했다"),
            ("2026-09-20", "08:30"): ToolError.upstream_unavailable("CROWD 표를 읽지 못했다"),
        }
    )
    guard = _guard()
    upcoming = [(_stop(i, station_no=200 + i), 15) for i in (1, 2)]

    readings = readings_for_trigger(upcoming, adapter=adapter, guard=guard, line="2호선", now=NOW)

    assert len(readings) == 2
    for reading in readings:
        assert reading.now.congestion_pct is None and reading.now.grade is None
        assert reading.on_arrival.congestion_pct is None and reading.on_arrival.grade is None
        assert reading.now.data_status == STATUS_NO_DATA
    # '조회 실패'가 '혼잡하지 않음'으로 읽히면 안 된다 — 트리거는 근거 없음으로 접는다.
    assert evaluate(readings).skip_reason == SKIP_NO_DATA
    # 실패의 실제 원인은 가드 호출 로그에 남는다.
    codes = {log.result_code for log in guard.logs()}
    assert codes == {ToolErrorCode.UPSTREAM_UNAVAILABLE.value}


def test_방향을_지정하면_그_방향_행만_쓰고_반대_방향으로_대체하지_않는다():
    adapter = FakeAdapter(
        line={
            ("2026-09-20", "08:00"): _line_response(
                "2026-09-20",
                "08:00",
                [
                    _station_row(201, pct=30.0, direction="내선"),
                    _station_row(201, pct=90.0, direction="외선"),
                ],
            ),
            ("2026-09-20", "08:30"): _line_response(
                "2026-09-20", "08:30", [_station_row(201, pct=95.0, direction="외선")]
            ),
        }
    )

    readings = readings_for_trigger(
        [(_stop(1, station_no=201), 15)],
        adapter=adapter,
        guard=_guard(),
        line="2호선",
        now=NOW,
        direction="내선",
    )

    assert readings[0].now.congestion_pct == 30.0
    # 도착 슬롯에 '내선'이 없다 — 외선 값(95.0)으로 대체하면 상승폭이 통째로 가짜가 된다.
    assert readings[0].on_arrival.congestion_pct is None
    assert readings[0].on_arrival.data_status == STATUS_NOT_IN_RESPONSE


# ── 후보별 프리페치 ──


def test_후보_수만큼_replan을_부른다():
    candidates = [_candidate(i) for i in range(1, 4)]
    adapter = FakeAdapter(replan={f"S{i}": [_route("2호선")] for i in range(1, 4)})

    context = prefetch(
        DECISION,
        candidates,
        adapter=adapter,
        guard=_guard(),
        dest_station_id="DEST",
    )

    calls = adapter.names(REPLAN_ROUTE)
    assert len(calls) == 3
    # 병렬이라 호출 **순서**는 보장하지 않는다 — 후보마다 한 번씩 불렸는지만 본다.
    assert sorted(args["boundary_id"] for args in calls) == ["S1", "S2", "S3"]
    assert [c.candidate for c in context.candidates] == candidates  # 결과 순서는 후보 순서
    assert context.has_alternative
    assert all(args["dest_station_id"] == "DEST" for args in calls)


def test_후보_하나가_실패해도_나머지는_살아남는다():
    adapter = FakeAdapter(
        replan={
            "S1": [_route("2호선")],
            "S2": ToolError.upstream_unavailable("BE가 응답하지 않는다"),
            "S3": [_route("2호선")],
        }
    )

    context = prefetch(
        DECISION,
        [_candidate(i) for i in range(1, 4)],
        adapter=adapter,
        guard=_guard(),
        dest_station_id="DEST",
    )

    failed = context.candidates[1]
    assert failed.error is not None
    assert failed.error["error"] == ToolErrorCode.UPSTREAM_UNAVAILABLE.value
    assert failed.routes == []  # 실패를 빈 목록 '대안 없음'으로 감추지 않는다
    assert not failed.usable
    assert [c.candidate.stop.station_id for c in context.usable_candidates] == ["S1", "S3"]


def test_현재_노선을_쓰는_경로는_사후_필터링된다():
    """`exclude_route_ids` 회신 전까지의 우회(TO_BE-time-reroute-contract-01 1번)."""
    adapter = FakeAdapter(
        replan={"S1": [_route("2호선"), _route("9호선"), _route("2호선", minutes=30.0)]}
    )

    context = prefetch(
        DECISION,
        [_candidate(1)],
        adapter=adapter,
        guard=_guard(),
        dest_station_id="DEST",
        current_route_id="2호선",
    )

    routes = context.candidates[0].routes
    assert len(routes) == 1
    assert routes[0]["route"]["legs"][0]["routeId"] == "9호선"
    assert context.current_route_id == "2호선"
    # 요청 파라미터가 아니라 응답을 걸러서 처리한다 — 회신이 오면 이 단언이 바뀐다.
    assert "exclude_route_ids" not in adapter.names(REPLAN_ROUTE)[0]


def test_필터_후_0개면_그_후보는_쓸_수_없지만_실패는_아니다():
    adapter = FakeAdapter(replan={"S1": [_route("2호선")], "S2": [_route("9호선")]})

    context = prefetch(
        DECISION,
        [_candidate(1), _candidate(2)],
        adapter=adapter,
        guard=_guard(),
        dest_station_id="DEST",
        current_route_id="2호선",
    )

    filtered_out = context.candidates[0]
    assert filtered_out.routes == []
    assert filtered_out.error is None  # '대안 없음'이지 '조회 실패'가 아니다
    assert not filtered_out.usable
    assert context.has_alternative  # 두 번째 후보는 남았다


def test_모든_후보가_걸러지면_대안이_없다():
    adapter = FakeAdapter(replan={"S1": [_route("2호선")], "S2": [_route("2호선")]})

    context = prefetch(
        DECISION,
        [_candidate(1), _candidate(2)],
        adapter=adapter,
        guard=_guard(),
        dest_station_id="DEST",
        current_route_id="2호선",
    )

    assert not context.has_alternative
    assert all(c.error is None for c in context.candidates)


def test_가드가_막으면_예산_초과가_error에_드러난다():
    adapter = FakeAdapter(replan={"S1": [_route("9호선")]})
    guard = ToolGuard(tool_budgets={REPLAN_ROUTE: 0})

    context = prefetch(
        DECISION,
        [_candidate(1)],
        adapter=adapter,
        guard=guard,
        dest_station_id="DEST",
    )

    error = context.candidates[0].error
    assert error is not None
    assert error["error"] == ToolErrorCode.BUDGET_EXCEEDED.value
    assert error["retryable"] is False
    assert not context.has_alternative
    assert adapter.calls == []  # 막힌 호출은 어댑터까지 가지 않는다
    assert guard.logs()[0].blocked


def test_후보가_없으면_도구를_부르지_않고_대안도_없다():
    adapter = FakeAdapter()

    context = prefetch(DECISION, [], adapter=adapter, guard=_guard(), dest_station_id="DEST")

    assert context.candidates == []
    assert not context.has_alternative
    assert context.decision is DECISION
    assert adapter.calls == []


def test_station_id가_없는_후보는_조용히_빠지지_않고_오류로_남는다():
    adapter = FakeAdapter(replan={"S2": [_route("9호선")]})
    candidates = [
        DropCandidate(stop=Stop(seq=1, station_id=None, station_no=201), eta_minutes=4),
        _candidate(2),
    ]

    context = prefetch(
        DECISION, candidates, adapter=adapter, guard=_guard(), dest_station_id="DEST"
    )

    assert context.candidates[0].error is not None
    assert context.candidates[0].error["error"] == ToolErrorCode.INVALID_INPUT.value
    assert len(adapter.names(REPLAN_ROUTE)) == 1  # 부를 수 있는 후보만 불렀다
    assert [c.candidate.stop.seq for c in context.usable_candidates] == [2]


def test_배열이_아닌_replan_응답은_해석하지_않고_실패로_남긴다():
    adapter = FakeAdapter(replan={"S1": {"routes": [_route("9호선")]}})

    context = prefetch(
        DECISION, [_candidate(1)], adapter=adapter, guard=_guard(), dest_station_id="DEST"
    )

    error = context.candidates[0].error
    assert error is not None
    assert error["error"] == ToolErrorCode.UPSTREAM_UNAVAILABLE.value
    assert context.candidates[0].routes == []
