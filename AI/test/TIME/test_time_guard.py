"""`app/TIME/guard.py` 검증.

시계를 주입해서 잰다 — `time.sleep`으로 레이트리밋을 테스트하면 테스트가 느려지는 데다
CI 머신이 느릴 때 창 경계에서 간헐적으로 깨진다.

가장 중요한 테스트는 `test_log_keeps_arg_keys_but_never_values`다. 인자 값(좌표·역 ID)이
로그에 새는 것은 기능이 아니라 사고라, 로그 전체를 문자열로 만들어 값이 없다는 것까지 본다.
"""

from __future__ import annotations

import pytest

from app.TIME.guard import (
    RESULT_EXCEPTION,
    RESULT_OK,
    ToolGuard,
    arg_keys_of,
    result_code_of,
)
from app.TIME.registry import GET_ARRIVALS, GET_ETA_STOCK, REPLAN_ROUTE
from app.TIME.schemas import ToolError, ToolErrorCode

RATE_LIMIT_RECOVERY_SEC = 1.1
"""레이트 창(1초)을 확실히 넘기는 값."""


class FakeClock:
    """주입용 단조 시계. `advance()`로 시간을 앞으로 돌린다(초 단위)."""

    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _ok(guard: ToolGuard, name: str, count: int = 1) -> None:
    """성공 호출 `count`건을 기록한다."""
    for _ in range(count):
        guard.record(name, elapsed_ms=1.0, result_code=RESULT_OK, arg_keys=["step"])


# ── 예산 ──


def test_check_passes_within_budget() -> None:
    guard = ToolGuard(clock=FakeClock())
    assert guard.check(REPLAN_ROUTE) is None

    _ok(guard, REPLAN_ROUTE)
    assert guard.check(REPLAN_ROUTE) is None
    assert guard.total_calls == 1


def test_total_budget_exceeded_returns_budget_error() -> None:
    guard = ToolGuard(total_budget=3, clock=FakeClock())
    _ok(guard, GET_ARRIVALS, count=3)

    err = guard.check(GET_ARRIVALS)
    assert isinstance(err, ToolError)
    assert err.error is ToolErrorCode.BUDGET_EXCEEDED
    # 재시도해도 소용없다는 신호여야 한다 — retryable=True면 에이전트가 루프를 계속 돈다.
    assert err.retryable is False
    # 총 한도라 다른 도구도 같이 막힌다.
    assert guard.check(GET_ETA_STOCK) is not None


def test_replan_tool_budget_is_three_and_scoped_to_that_tool() -> None:
    guard = ToolGuard(clock=FakeClock())
    _ok(guard, REPLAN_ROUTE, count=3)  # BE 회신 K=3 + 순차 호출 권고(8번)

    err = guard.check(REPLAN_ROUTE)
    assert isinstance(err, ToolError)
    assert err.error is ToolErrorCode.BUDGET_EXCEEDED
    # 도구별 한도지 세션 한도가 아니다 — 다른 도구는 아직 부를 수 있어야 한다.
    assert guard.check(GET_ARRIVALS) is None


def test_failed_calls_also_consume_budget() -> None:
    """실패도 예산을 깎는다. 안 깎으면 상류 장애 때 같은 호출을 무한 재시도한다."""
    guard = ToolGuard(total_budget=2, clock=FakeClock())
    for _ in range(2):
        guard.record(
            GET_ETA_STOCK,
            elapsed_ms=5.0,
            result_code=ToolErrorCode.UPSTREAM_UNAVAILABLE.value,
            arg_keys=["rental_id"],
        )

    assert guard.check(GET_ETA_STOCK) is not None


# ── 레이트리밋 ──


def test_rate_limit_exceeded_returns_retryable_error() -> None:
    clock = FakeClock()
    guard = ToolGuard(max_per_second=2, clock=clock)
    _ok(guard, GET_ARRIVALS, count=2)

    err = guard.check(GET_ARRIVALS)
    assert isinstance(err, ToolError)
    assert err.error is ToolErrorCode.RATE_LIMITED
    # 잠시 뒤면 다시 되는 상황이라 재시도 가치가 있다.
    assert err.retryable is True


def test_rate_limit_recovers_when_window_passes() -> None:
    clock = FakeClock()
    guard = ToolGuard(max_per_second=2, clock=clock)
    _ok(guard, GET_ARRIVALS, count=2)
    assert guard.check(GET_ARRIVALS) is not None

    clock.advance(0.5)  # 창 안이라 아직 막혀 있다
    assert guard.check(GET_ARRIVALS) is not None

    clock.advance(0.6)  # 창(1초)을 넘겼다
    assert guard.check(GET_ARRIVALS) is None


def test_budget_error_wins_over_rate_error() -> None:
    """둘 다 걸리면 예산이 먼저다 — 재시도해도 소용없다는 쪽을 알려야 루프가 끊긴다."""
    clock = FakeClock()
    guard = ToolGuard(total_budget=2, max_per_second=1, clock=clock)
    _ok(guard, GET_ARRIVALS, count=2)

    err = guard.check(GET_ARRIVALS)
    assert isinstance(err, ToolError)
    assert err.error is ToolErrorCode.BUDGET_EXCEEDED


# ── 호출 로그 ──


def test_log_keeps_arg_keys_but_never_values() -> None:
    """인자 **키**는 남고 **값**은 어디에도 남지 않는다. 이 파일에서 가장 중요한 테스트다."""
    guard = ToolGuard(clock=FakeClock())
    args = {
        "step": 2,
        "boundary_id": "MT-1004-강남",
        "dest_station_id": "MT-1002-잠실",
        "lat": 37.5665,
    }

    guard.run(REPLAN_ROUTE, lambda: {"routes": []}, args)

    (entry,) = guard.logs()
    assert entry.tool == REPLAN_ROUTE
    assert entry.result_code == RESULT_OK
    assert entry.arg_keys == ("step", "boundary_id", "dest_station_id", "lat")

    # 로그 객체 전체를 문자열로 펴서 값이 한 조각도 없는지 본다.
    dumped = repr(guard.logs())
    for value in ("MT-1004-강남", "MT-1002-잠실", "37.5665"):
        assert value not in dumped


def test_arg_keys_of_drops_values() -> None:
    assert arg_keys_of({"station_id": "MT-1004-강남"}) == ("station_id",)
    assert arg_keys_of(None) == ()


def test_log_records_elapsed_and_error_code() -> None:
    clock = FakeClock()
    guard = ToolGuard(clock=clock)

    def slow_failure() -> ToolError:
        clock.advance(0.025)
        return ToolError.upstream_unavailable("BE 미기동")

    result = guard.run(GET_ARRIVALS, slow_failure, {"station_id": "MT-1004"})

    assert isinstance(result, ToolError)
    (entry,) = guard.logs()
    assert entry.elapsed_ms == pytest.approx(25.0)
    assert entry.result_code == ToolErrorCode.UPSTREAM_UNAVAILABLE.value
    assert entry.blocked is False


def test_logs_returns_copy() -> None:
    guard = ToolGuard(clock=FakeClock())
    _ok(guard, GET_ARRIVALS)

    snapshot = guard.logs()
    _ok(guard, GET_ARRIVALS)

    assert len(snapshot) == 1
    assert len(guard.logs()) == 2


# ── 집계 ──


def test_stats_aggregates_per_tool() -> None:
    guard = ToolGuard(clock=FakeClock())
    guard.record(GET_ARRIVALS, elapsed_ms=10.0, result_code=RESULT_OK, arg_keys=["station_id"])
    guard.record(GET_ARRIVALS, elapsed_ms=5.5, result_code=RESULT_OK, arg_keys=["station_id"])
    guard.record(
        GET_ARRIVALS,
        elapsed_ms=4.5,
        result_code=ToolErrorCode.UPSTREAM_UNAVAILABLE.value,
        arg_keys=["station_id"],
    )
    guard.record(REPLAN_ROUTE, elapsed_ms=2.0, result_code=RESULT_OK, arg_keys=["step"])

    stats = guard.stats()
    assert set(stats) == {GET_ARRIVALS, REPLAN_ROUTE}

    arrivals = stats[GET_ARRIVALS]
    assert (arrivals.calls, arrivals.ok, arrivals.failed) == (3, 2, 1)
    assert arrivals.total_ms == pytest.approx(20.0)
    assert stats[REPLAN_ROUTE].calls == 1
    assert guard.total_calls == 4

    # 사본이라 밖에서 고쳐도 가드 내부가 흔들리지 않는다.
    arrivals.calls = 999
    assert guard.stats()[GET_ARRIVALS].calls == 3


def test_stats_counts_blocked_separately_from_calls() -> None:
    guard = ToolGuard(total_budget=1, clock=FakeClock())
    guard.run(GET_ARRIVALS, lambda: {"status": "LIVE"}, {"station_id": "MT-1004"})
    guard.run(GET_ARRIVALS, lambda: {"status": "LIVE"}, {"station_id": "MT-1004"})

    stat = guard.stats()[GET_ARRIVALS]
    assert (stat.calls, stat.ok, stat.blocked) == (1, 1, 1)
    # 막힌 호출은 예산을 깎지 않는다 — 막혔다고 예산이 더 줄면 총량 해석이 어긋난다.
    assert guard.total_calls == 1


# ── run() ──


def test_run_returns_result_and_consumes_budget() -> None:
    guard = ToolGuard(clock=FakeClock())
    payload = {"status": "LIVE", "trains": []}

    result = guard.run(GET_ARRIVALS, lambda: payload, {"station_id": "MT-1004"})

    assert result is payload
    assert guard.total_calls == 1


def test_run_does_not_invoke_tool_when_blocked() -> None:
    guard = ToolGuard(total_budget=0, clock=FakeClock())
    invoked: list[int] = []

    result = guard.run(GET_ARRIVALS, lambda: invoked.append(1), {"station_id": "MT-1004"})

    assert isinstance(result, ToolError)
    assert result.error is ToolErrorCode.BUDGET_EXCEEDED
    assert invoked == []  # 막힌 호출은 도구에 닿지 않는다
    (entry,) = guard.logs()
    assert entry.blocked is True
    assert entry.arg_keys == ("station_id",)


def test_run_records_and_reraises_on_exception() -> None:
    guard = ToolGuard(clock=FakeClock())

    def broken() -> None:
        raise RuntimeError("어댑터 버그")

    with pytest.raises(RuntimeError):
        guard.run(GET_ETA_STOCK, broken, {"rental_id": "ST-1"})

    (entry,) = guard.logs()
    assert entry.result_code == RESULT_EXCEPTION
    assert guard.total_calls == 1  # 예외여도 예산은 깎인다


def test_run_respects_rate_limit_over_repeated_calls() -> None:
    clock = FakeClock()
    guard = ToolGuard(max_per_second=3, clock=clock)

    results = [guard.run(GET_ARRIVALS, lambda: {"status": "LIVE"}, None) for _ in range(4)]

    assert all(not isinstance(r, ToolError) for r in results[:3])
    assert isinstance(results[3], ToolError)
    assert results[3].error is ToolErrorCode.RATE_LIMITED

    clock.advance(RATE_LIMIT_RECOVERY_SEC)
    assert not isinstance(guard.run(GET_ARRIVALS, lambda: {"status": "LIVE"}, None), ToolError)


# ── 결과 코드 판정 ──


def test_result_code_of_handles_object_and_dict_errors() -> None:
    assert result_code_of({"status": "LIVE"}) == RESULT_OK
    assert result_code_of(ToolError.not_found("없는 역")) == ToolErrorCode.NOT_FOUND.value
    # HTTP 어댑터가 직렬화된 dict를 돌려줘도 실패로 집계돼야 한다.
    assert (
        result_code_of({"error": "RATE_LIMITED", "detail": "x", "retryable": True})
        == ToolErrorCode.RATE_LIMITED.value
    )


def test_guard_instances_do_not_share_budget() -> None:
    """세션 단위 인스턴스 — 전역 싱글턴이면 여기서 두 세션의 예산이 섞인다."""
    first = ToolGuard(total_budget=1, clock=FakeClock())
    second = ToolGuard(total_budget=1, clock=FakeClock())
    _ok(first, GET_ARRIVALS)

    assert first.check(GET_ARRIVALS) is not None
    assert second.check(GET_ARRIVALS) is None


def test_default_tool_budgets_are_not_shared_between_instances() -> None:
    """도구별 예산 dict가 모듈 전역과 이어져 있으면 한 세션의 수정이 전 세션에 번진다."""
    first = ToolGuard(clock=FakeClock())
    first.tool_budgets[REPLAN_ROUTE] = 1

    assert ToolGuard(clock=FakeClock()).budget_for(REPLAN_ROUTE) == 3


def test_동시_호출에서_카운터가_유실되지_않는다():
    """203 `planner.prefetch`가 후보별 replan을 ThreadPoolExecutor로 동시에 부른다.

    `_counts[name] = _counts.get(name, 0) + 1`은 read-modify-write라 락이 없으면 증가분이
    유실된다. 유실되면 예산이 실제보다 적게 세어져 **막으라고 만든 가드가 조용히 새기 때문에**
    실패해도 티가 나지 않는다 — 그래서 여기서 직접 잰다.
    """
    import threading
    from concurrent.futures import ThreadPoolExecutor

    calls = 200
    guard = ToolGuard(total_budget=calls * 2, per_tool_budget=calls * 2, max_per_second=10**9)
    ready = threading.Event()

    def hammer(_: int) -> None:
        ready.wait()  # 스레드가 한꺼번에 출발해야 경쟁이 실제로 난다
        guard.record("t", elapsed_ms=1.0, result_code=RESULT_OK, arg_keys=["k"])

    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(hammer, i) for i in range(calls)]
        ready.set()
        for future in futures:
            future.result()

    assert guard.total_calls == calls
    assert guard.stats()["t"].calls == calls
    assert len(guard.logs()) == calls
