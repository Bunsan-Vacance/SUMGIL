"""도구 프리페치(S15P21A104-203/302) — ③.

LLM에 넘기기 전에 **필요한 조회를 여기서 다 끝낸다.** 에이전트가 스스로 도구를 고르게 하면
LLM 턴이 2~3회(5~15초)가 되는데, 트리거(①)가 이미 "어느 대여소가 문제인지"를 알고 있어서 그럴
이유가 없다. 결과를 한 번에 모아 주면 LLM은 1턴으로 끝난다(계획 1.1절). 같은 이유로
`AgentContext`는 두 전략(`RuleStrategy`·`AgentStrategy`)의 **완전히 같은 입력**이 된다 —
7절 비교의 동등 조건이 이 파일에서 보장된다(`AI/CLAUDE.md` 모델 비교 하드 룰 2·3번).

여기서 하는 일은 둘이다.

- `read_stock` — `get_eta_stock` 도구 결과 하나를 `trigger.StockReading`으로 옮긴다.
- `prefetch` — 후보 대여소마다 **대상과 같은 eta_minutes**로 `read_stock`을 불러
  `AgentContext`를 조립한다.

**값을 지어내지 않는다.** 조회가 실패하거나 응답 필드가 비어 있으면 그 자리는 `None`으로 두고
상태값으로 알린다. 실패를 성공처럼 감추지 않는 것도 같은 원칙이다(`CandidateContext.error`).

어댑터·가드는 **인자로 받는다.** 가드는 세션(요청 하나의 루프) 단위 인스턴스라 이 모듈이 만들면
예산이 사용자 사이에 섞인다(`guard.py` 첫 문단).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from app.TIME.adapters import ToolAdapter, ToolResult
from app.TIME.context import AgentContext, CandidateContext, RentalCandidate
from app.TIME.guard import ToolGuard
from app.TIME.registry import GET_ETA_STOCK
from app.TIME.schemas import ToolError, is_error
from app.TIME.station_index import RentalStation
from app.TIME.trigger import StockReading, TriggerResult


def read_stock(
    rental_id: str,
    eta_minutes: int,
    *,
    adapter: ToolAdapter,
    guard: ToolGuard,
) -> StockReading | ToolError:
    """`get_eta_stock` 하나를 부르고 `StockReading`으로 옮긴다. 실패는 `ToolError` 그대로 낸다.

    필드는 전부 tolerant하게 읽는다(`_as_int`/`_as_float`) — 응답이 스키마와 조금 어긋나도
    그 필드만 `None`이 될 뿐 함수 전체가 죽지 않는다. `trigger.evaluate`가 `None`을 값 없음으로
    다루므로 여기서 값을 채워 넣거나 0으로 대체하지 않는다.
    """
    args = {"rental_id": rental_id, "eta_minutes": eta_minutes}
    result: ToolResult = guard.run(GET_ETA_STOCK, lambda: adapter.call(GET_ETA_STOCK, args), args)

    if isinstance(result, ToolError):
        return result
    if is_error(result):
        # 로컬 어댑터·가드는 `ToolError` 객체를 돌려주지만, 직렬화된 dict가 올 수 있는 경로도
        # 있다(`schemas.is_error`가 그 경우까지 본다) — 어느 쪽이든 호출자는 같은 `ToolError`를
        # 받아야 한다.
        return ToolError.model_validate(dict(result))  # type: ignore[arg-type]
    if not isinstance(result, Mapping):
        return ToolError.upstream_unavailable(
            f"get_eta_stock 응답이 객체가 아니다(type={type(result).__name__})"
        )

    return StockReading(
        current_stock=_as_int(result.get("current_stock")),
        predicted_stock=_as_float(result.get("predicted_stock")),
        p_empty=_as_float(result.get("p_empty")),
        p_full=_as_float(result.get("p_full")),
        source=_as_str(result.get("source")),
        model_horizon_min=_as_int(result.get("model_horizon_min")),
    )


def prefetch(
    *,
    decision: TriggerResult,
    target: RentalStation,
    target_reading: StockReading,
    eta_minutes: int,
    candidates: Sequence[RentalCandidate],
    adapter: ToolAdapter,
    guard: ToolGuard,
    dest_station_id: str | None = None,
) -> AgentContext:
    """후보마다 `read_stock`을 불러 `AgentContext`를 조립한다.

    **순차로 부른다.** `planner.py`(구판)의 `replan_route` 프리페치와 같은 이유다 — BE 회신
    (`FROM_BE-time-reroute-contract-01` 8번)이 prod BE는 CPU 1개 전제라 순차 호출을 권했고,
    이 함수가 부르는 `get_eta_stock`도 같은 BE/모델 서빙을 거치므로 같은 근거를 따른다. 결과
    순서는 후보 순서를 그대로 지킨다 — 전략이 `candidate_index`로 후보를 가리킨다.

    **모든 후보가 대상과 같은 `eta_minutes`로 조회된다** — 트리거가 쓴 값과 다르면 "지금 대상은
    10분 뒤, 후보는 15분 뒤" 같은 서로 다른 시점을 비교하게 된다(`AGENT_DESIGN.md` 계획 2.3절).
    """
    contexts: list[CandidateContext] = []
    for candidate in candidates:
        outcome = read_stock(candidate.station.rental_id, eta_minutes, adapter=adapter, guard=guard)
        if isinstance(outcome, ToolError):
            contexts.append(CandidateContext(candidate=candidate, error=_as_error_dict(outcome)))
        else:
            contexts.append(CandidateContext(candidate=candidate, reading=outcome))

    return AgentContext(
        decision=decision,
        target=target,
        target_reading=target_reading,
        eta_minutes=eta_minutes,
        candidates=contexts,
        dest_station_id=dest_station_id,
    )


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


def _as_int(value: Any) -> int | None:
    """숫자로 못 읽는 값은 0이 아니라 `None`이다 — 결측을 0으로 바꾸면 트리거 판정이 뒤틀린다."""
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


__all__ = ["prefetch", "read_stock"]
