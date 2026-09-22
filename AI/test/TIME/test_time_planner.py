"""도구 프리페치 검증(S15P21A104-203/302).

여기서 고정하려는 것은 넷이다.

1. **dict → StockReading 변환** — `get_eta_stock` 응답 필드가 tolerant하게 옮겨지는지(없는
   필드는 0이 아니라 `None`).
2. **`ToolError` 통과** — 실패는 그대로 `ToolError`로 돌아온다.
3. **같은 eta_minutes** — 후보 전부가 대상과 같은 도착 시각 기준으로 조회되는지.
4. **부분 실패를 감추지 않는다** — 후보 하나가 실패해도 나머지는 살아남고, 그 실패가 `error`에
   남아 `usable`이 False가 된다.

테스트는 **실제 네트워크·parquet를 쓰지 않는다.** 어댑터는 호출을 기록하고 미리 정한 응답을
돌려주는 가짜다(202 `test_time_adapters.py`와 같은 방침).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.TIME.context import RentalCandidate
from app.TIME.guard import ToolGuard
from app.TIME.planner import prefetch, read_stock
from app.TIME.registry import GET_ETA_STOCK
from app.TIME.schemas import ToolError, ToolErrorCode
from app.TIME.station_index import RentalStation
from app.TIME.trigger import StockReading, TriggerResult


class FakeAdapter:
    """도구 이름·인자를 기록하고 `rental_id`별 미리 정한 응답을 돌려준다."""

    def __init__(self, responses: Mapping[str, Any] | None = None) -> None:
        self.responses = dict(responses or {})
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def call(self, name: str, args: Mapping[str, Any]) -> Any:
        self.calls.append((name, dict(args)))
        if name != GET_ETA_STOCK:
            return ToolError.invalid_input(f"가짜 어댑터가 모르는 도구 '{name}'")
        rental_id = str(args["rental_id"])
        if rental_id not in self.responses:
            return ToolError.not_found(f"{rental_id} 실시간 재고를 확인할 수 없다")
        return self.responses[rental_id]

    def eta_calls(self) -> list[dict[str, Any]]:
        return [args for name, args in self.calls if name == GET_ETA_STOCK]


def _guard() -> ToolGuard:
    return ToolGuard()


def _station(rental_id: str, **overrides: Any) -> RentalStation:
    fields: dict[str, Any] = {
        "rental_id": rental_id,
        "name": rental_id,
        "lat": 37.5665,
        "lng": 126.9780,
        "rack_count": 10,
        "current_stock": 5,
        "updated_at": None,
    }
    fields.update(overrides)
    return RentalStation(**fields)


def _candidate(
    rental_id: str, *, distance_m: float = 100.0, **station_overrides: Any
) -> RentalCandidate:
    return RentalCandidate(station=_station(rental_id, **station_overrides), distance_m=distance_m)


def _eta_stock_response(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "rental_id": "X",
        "eta_minutes": 10,
        "current_stock": 3,
        "predicted_stock": 1.5,
        "p_empty": 0.6,
        "p_full": 0.0,
        "source": "lightgbm",
        "model_horizon_min": 10,
    }
    body.update(overrides)
    return body


def _target_reading() -> StockReading:
    return StockReading(
        current_stock=0,
        predicted_stock=0.2,
        p_empty=0.9,
        p_full=0.0,
        source="lightgbm",
        model_horizon_min=10,
    )


DECISION = TriggerResult(fired=True, reason="p_empty", facts={"eta_minutes": 10})
"""프리페치는 트리거 판정을 그대로 싣고 다니기만 한다 — 내용은 이 파일의 관심사가 아니다."""


# ── read_stock: dict → StockReading ──


def test_응답_딕셔너리가_StockReading으로_변환된다():
    adapter = FakeAdapter({"A": _eta_stock_response()})

    result = read_stock("A", 10, adapter=adapter, guard=_guard())

    assert isinstance(result, StockReading)
    assert result.current_stock == 3
    assert result.predicted_stock == 1.5
    assert result.p_empty == 0.6
    assert result.p_full == 0.0
    assert result.source == "lightgbm"
    assert result.model_horizon_min == 10


def test_없는_필드는_0이_아니라_None으로_읽힌다():
    adapter = FakeAdapter({"A": {"rental_id": "A", "eta_minutes": 10}})

    result = read_stock("A", 10, adapter=adapter, guard=_guard())

    assert isinstance(result, StockReading)
    assert result.current_stock is None
    assert result.predicted_stock is None
    assert result.p_empty is None
    assert result.p_full is None
    assert result.source is None
    assert result.model_horizon_min is None


def test_인자가_그대로_전달된다():
    adapter = FakeAdapter({"A": _eta_stock_response()})

    read_stock("A", 12, adapter=adapter, guard=_guard())

    assert adapter.eta_calls() == [{"rental_id": "A", "eta_minutes": 12}]


# ── read_stock: ToolError 통과 ──


def test_ToolError는_그대로_통과한다():
    adapter = FakeAdapter()  # "A"에 대한 응답이 없어 not_found

    result = read_stock("A", 10, adapter=adapter, guard=_guard())

    assert isinstance(result, ToolError)
    assert result.error == ToolErrorCode.NOT_FOUND


def test_예산이_없으면_BUDGET_EXCEEDED를_돌려준다():
    adapter = FakeAdapter({"A": _eta_stock_response()})
    guard = ToolGuard(tool_budgets={GET_ETA_STOCK: 0})

    result = read_stock("A", 10, adapter=adapter, guard=guard)

    assert isinstance(result, ToolError)
    assert result.error == ToolErrorCode.BUDGET_EXCEEDED
    assert adapter.calls == []  # 막힌 호출은 어댑터까지 가지 않는다


# ── prefetch: 같은 eta_minutes ──


def test_모든_후보가_같은_eta로_조회된다():
    adapter = FakeAdapter(
        {
            "A": _eta_stock_response(rental_id="A"),
            "B": _eta_stock_response(rental_id="B"),
            "C": _eta_stock_response(rental_id="C"),
        }
    )
    candidates = [_candidate("A"), _candidate("B"), _candidate("C")]

    ctx = prefetch(
        decision=DECISION,
        target=_station("TARGET"),
        target_reading=_target_reading(),
        eta_minutes=10,
        candidates=candidates,
        adapter=adapter,
        guard=_guard(),
    )

    calls = adapter.eta_calls()
    assert len(calls) == 3
    assert {c["eta_minutes"] for c in calls} == {10}
    # 순차 호출이라 어댑터가 받은 순서도 후보 순서와 같다.
    assert [c["rental_id"] for c in calls] == ["A", "B", "C"]
    assert len(ctx.candidates) == 3
    assert all(c.usable for c in ctx.candidates)


def test_context_필드가_그대로_담긴다():
    target = _station("TARGET")
    target_reading = _target_reading()
    adapter = FakeAdapter({"A": _eta_stock_response(rental_id="A")})

    ctx = prefetch(
        decision=DECISION,
        target=target,
        target_reading=target_reading,
        eta_minutes=10,
        candidates=[_candidate("A")],
        adapter=adapter,
        guard=_guard(),
        dest_station_id="DEST-1",
    )

    assert ctx.decision is DECISION
    assert ctx.target is target
    assert ctx.target_reading is target_reading
    assert ctx.eta_minutes == 10
    assert ctx.dest_station_id == "DEST-1"


# ── prefetch: 부분 실패를 감추지 않는다 ──


def test_후보_하나가_실패해도_나머지는_살아남는다():
    adapter = FakeAdapter(
        {"A": _eta_stock_response(rental_id="A"), "C": _eta_stock_response(rental_id="C")}
    )
    candidates = [_candidate("A"), _candidate("B"), _candidate("C")]

    ctx = prefetch(
        decision=DECISION,
        target=_station("TARGET"),
        target_reading=_target_reading(),
        eta_minutes=10,
        candidates=candidates,
        adapter=adapter,
        guard=_guard(),
    )

    failed = ctx.candidates[1]
    assert failed.error is not None
    assert failed.error["error"] == ToolErrorCode.NOT_FOUND.value
    assert failed.reading is None
    assert not failed.usable
    assert [c.candidate.station.rental_id for c in ctx.usable_candidates] == ["A", "C"]
    assert ctx.has_alternative


def test_후보가_없으면_도구를_부르지_않는다():
    adapter = FakeAdapter()

    ctx = prefetch(
        decision=DECISION,
        target=_station("TARGET"),
        target_reading=_target_reading(),
        eta_minutes=10,
        candidates=[],
        adapter=adapter,
        guard=_guard(),
    )

    assert ctx.candidates == []
    assert not ctx.has_alternative
    assert adapter.calls == []


# ── prefetch: 가드가 쓰인다 ──


def test_가드가_사용된다():
    adapter = FakeAdapter({"A": _eta_stock_response(rental_id="A")})
    guard = ToolGuard()

    prefetch(
        decision=DECISION,
        target=_station("TARGET"),
        target_reading=_target_reading(),
        eta_minutes=10,
        candidates=[_candidate("A")],
        adapter=adapter,
        guard=guard,
    )

    assert guard.total_calls == 1
    assert GET_ETA_STOCK in guard.stats()


def test_예산이_소진되면_후보가_예산_초과_오류로_남는다():
    adapter = FakeAdapter({"A": _eta_stock_response(rental_id="A")})
    guard = ToolGuard(tool_budgets={GET_ETA_STOCK: 0})

    ctx = prefetch(
        decision=DECISION,
        target=_station("TARGET"),
        target_reading=_target_reading(),
        eta_minutes=10,
        candidates=[_candidate("A")],
        adapter=adapter,
        guard=guard,
    )

    error = ctx.candidates[0].error
    assert error is not None
    assert error["error"] == ToolErrorCode.BUDGET_EXCEEDED.value
    assert adapter.calls == []  # 막힌 호출은 어댑터까지 가지 않는다
    assert not ctx.has_alternative
