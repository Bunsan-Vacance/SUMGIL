"""재안내 판정 진입점(S15P21A104-302) — ①~⑤를 잇는 유일한 자리.

```
① 트리거 판정   trigger.evaluate       규칙
② 하차 후보     candidates.generate    규칙
③ 도구 프리페치  planner.prefetch       BE 순차 호출
④ 후보 선택     strategy.decide        규칙 또는 LLM  ← 주입받는다
⑤ 안내 문장     〃                     〃
```

**여기까지가 순수 라이브러리다.** FastAPI·세션 보관소·HTTP 모양은 `router.py`의 몫이고, 이
모듈은 그것을 모른다 — 호출 방향(FE→BE→AI / FE→AI)이 아직 결정 대기라
(`FROM_BE-time-reroute-contract-01` 6번) 그 결정이 바뀌어도 이 파일은 안 바뀌어야 한다.

**상태를 갖지 않는다.** 쿨다운(`seconds_since_last_fire`)·`ToolGuard`·전략은 전부 인자다.
세션 단위로 살아야 하는 것들이라 여기서 만들면 동시 사용자끼리 예산과 쿨다운을 공유한다
(`TOOL_CONTRACT.md` 5절).

**예외를 밖으로 내보내지 않는다.** 재안내는 "있으면 좋은 것"이라, 어디서 무엇이 실패하든
호출자는 기존 안내를 그대로 유지하면 된다. 실패는 `RerouteStatus.UNAVAILABLE`이라는 값으로 나온다.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

from app.TIME import candidates as candidates_module
from app.TIME import planner, trigger
from app.TIME.adapters import ToolAdapter
from app.TIME.context import AgentContext, Stop
from app.TIME.guard import ToolGuard
from app.TIME.registry import GET_ARRIVALS
from app.TIME.schemas import is_error
from app.TIME.strategy import RerouteProposal, RerouteStrategy
from app.TIME.trigger import SKIP_NO_DATA, TriggerDecision, TriggerThresholds

_log = logging.getLogger(__name__)

ARRIVAL_STATUS_LIVE = candidates_module.ARRIVAL_STATUS_LIVE


class RerouteStatus(StrEnum):
    """호출자가 구분해야 하는 네 가지 결과.

    `NO_ALTERNATIVE`와 `UNAVAILABLE`을 굳이 나누는 이유는 `ToolErrorCode`의
    `NOT_FOUND`/`UPSTREAM_UNAVAILABLE` 구분과 같다(`TOOL_CONTRACT.md` 2.1절) — **"대안이 없다"와
    "대안이 있는지 물어보지 못했다"는 다르다.** 뭉개면 조회 장애를 "이 경로가 최선"이라고
    사용자에게 말하게 된다.
    """

    NO_TRIGGER = "no_trigger"
    """평소 상태. 대부분의 폴링이 여기서 끝난다 — 도구도 LLM도 부르지 않는다."""

    NO_ALTERNATIVE = "no_alternative"
    """트리거는 섰는데 갈아탈 만한 경로가 실제로 없었다. 조회는 정상이었다."""

    UNAVAILABLE = "unavailable"
    """조회·판정을 끝내지 못했다. 호출자는 **조용히 무시**하고 기존 안내를 유지한다."""

    PROPOSAL = "proposal"
    """추천이 있다. `RerouteOutcome.proposal`이 채워진다."""


@dataclass(frozen=True)
class RerouteOutcome:
    """판정 결과 한 벌. `status` 외의 필드는 로그·204 평가 하네스가 읽는 부산물이다."""

    status: RerouteStatus
    proposal: RerouteProposal | None = None
    decision: TriggerDecision | None = None
    """트리거 판정. `skip_reason`이 "왜 안 떴나"의 원본이다 — 임계값 튜닝의 근거가 된다."""

    context: AgentContext | None = None
    """프리페치까지 끝난 입력. 두 전략(규칙·LLM)이 같은 입력을 봤는지 확인하는 자리이기도 하다
    (`AI/CLAUDE.md` 모델 비교 하드 룰 2·3번)."""

    detail: str | None = None
    """어디서 멈췄는지. **사용자에게 보여주는 문장이 아니다** — 안내 문장은 `proposal.reason`뿐이다."""

    @property
    def fired(self) -> bool:
        return self.decision is not None and self.decision.fired


def propose_reroute(
    *,
    stops: Sequence[Stop],
    current_seq: int,
    current_station_id: str,
    eta_minutes_by_seq: Mapping[int, int],
    line: str,
    now: datetime,
    dest_station_id: str,
    adapter: ToolAdapter,
    guard: ToolGuard,
    strategy: RerouteStrategy,
    dest_seq: int | None = None,
    current_route_id: str | None = None,
    direction: str | None = None,
    thresholds: TriggerThresholds | None = None,
    seconds_since_last_fire: float | None = None,
    step: int = 0,
    modes: Sequence[str] | None = None,
    priority: str | None = None,
    candidate_limit: int = candidates_module.MAX_CANDIDATES,
) -> RerouteOutcome:
    """지금 재안내를 띄울지 판정하고, 띄운다면 어느 역에서 내릴지까지 정한다.

    `stops`는 **남은 경로의 정차역 전부**(진행 순서)다. BE `RouteLegResponse`는 같은 노선의
    연속 구간을 leg 하나로 합쳐서 중간 정차역이 없으므로(`TO_BE-time-station-sequence-01`)
    공급원은 아직 호출자 몫이다 — 그 공급원이 붙어도(S15P21A104-301) 이 함수는 안 바뀐다.

    `seconds_since_last_fire`는 같은 이동에서 팝업이 반복해 뜨는 것을 막는 쿨다운 입력이다.
    보관소를 여기 두지 않는 이유는 모듈 docstring 참고 — 세션 상태는 호출자가 들고 있는다.
    """
    try:
        return _propose(
            stops=stops,
            current_seq=current_seq,
            current_station_id=current_station_id,
            eta_minutes_by_seq=eta_minutes_by_seq,
            line=line,
            now=now,
            dest_station_id=dest_station_id,
            adapter=adapter,
            guard=guard,
            strategy=strategy,
            dest_seq=dest_seq,
            current_route_id=current_route_id,
            direction=direction,
            thresholds=thresholds,
            seconds_since_last_fire=seconds_since_last_fire,
            step=step,
            modes=modes,
            priority=priority,
            candidate_limit=candidate_limit,
        )
    except Exception as exc:  # noqa: BLE001 - 불변식 유지가 목적이라 의도적으로 넓다
        # 어댑터·가드는 이미 실패를 값으로 내지만(`TOOL_CONTRACT.md` 2.2절), 전략 구현이나
        # 호출자가 넘긴 자료구조에서 새 예외가 날 수 있다. 재안내 하나 때문에 폴링 요청 전체가
        # 500이 되는 일은 없어야 한다.
        _log.warning("재안내 판정 중 예상 못 한 오류(%s): %s", type(exc).__name__, exc)
        return RerouteOutcome(
            status=RerouteStatus.UNAVAILABLE,
            detail=f"예상 못 한 오류({type(exc).__name__})",
        )


def _propose(
    *,
    stops: Sequence[Stop],
    current_seq: int,
    current_station_id: str,
    eta_minutes_by_seq: Mapping[int, int],
    line: str,
    now: datetime,
    dest_station_id: str,
    adapter: ToolAdapter,
    guard: ToolGuard,
    strategy: RerouteStrategy,
    dest_seq: int | None,
    current_route_id: str | None,
    direction: str | None,
    thresholds: TriggerThresholds | None,
    seconds_since_last_fire: float | None,
    step: int,
    modes: Sequence[str] | None,
    priority: str | None,
    candidate_limit: int,
) -> RerouteOutcome:
    # ── ① 트리거 ──
    upcoming = _upcoming(stops, current_seq=current_seq, eta_minutes_by_seq=eta_minutes_by_seq)
    if not upcoming:
        # 목적지에 거의 다 왔거나 정차역 공급원이 아직 안 붙은 상태다. 둘 다 "재안내할 일이
        # 없다"이지 장애가 아니다.
        return RerouteOutcome(status=RerouteStatus.NO_TRIGGER, detail="앞쪽 정차역이 없다")

    readings = planner.readings_for_trigger(
        upcoming, adapter=adapter, guard=guard, line=line, now=now, direction=direction
    )
    decision = trigger.evaluate(
        readings,
        thresholds=thresholds,
        seconds_since_last_fire=seconds_since_last_fire,
    )
    if not decision.fired:
        # `no_data`는 "혼잡하지 않다"가 아니라 "배치 표가 없어 판단 못 했다"이다 — 나머지
        # skip 사유(쿨다운·임계 미달)와 같은 칸에 넣지 않는다.
        status = (
            RerouteStatus.UNAVAILABLE
            if decision.skip_reason == SKIP_NO_DATA
            else RerouteStatus.NO_TRIGGER
        )
        return RerouteOutcome(status=status, decision=decision, detail=decision.skip_reason)

    # ── ② 하차 후보 ──
    # `get_arrivals`는 여기서 한 번만 부른다. `candidates.generate`가 응답을 인자로만 받는 이유는
    # 도구 호출이 전부 가드를 지나게 하기 위해서다(`candidates.py` 첫 문단).
    arrivals = _arrivals(adapter=adapter, guard=guard, station_id=current_station_id)
    arrivals_live = arrivals is not None and arrivals.get("status") == ARRIVAL_STATUS_LIVE

    drops = candidates_module.generate(
        stops,
        decision,
        current_seq=current_seq,
        eta_minutes_by_seq=eta_minutes_by_seq,
        arrivals=arrivals,
        dest_station_id=dest_station_id,
        dest_seq=dest_seq,
        limit=candidate_limit,
    )
    if not drops:
        # 도착 정보를 못 읽어서 후보가 0개인 것과, 읽었는데 내릴 역이 없는 것은 다르다.
        status = RerouteStatus.NO_ALTERNATIVE if arrivals_live else RerouteStatus.UNAVAILABLE
        detail = "하차 후보 없음" if arrivals_live else "도착 정보를 읽지 못했다"
        return RerouteOutcome(status=status, decision=decision, detail=detail)

    # ── ③ 프리페치 ──
    ctx = planner.prefetch(
        decision,
        drops,
        adapter=adapter,
        guard=guard,
        dest_station_id=dest_station_id,
        step=step,
        current_route_id=current_route_id,
        modes=modes,
        priority=priority,
    )
    if not ctx.has_alternative:
        # 후보마다 조회가 실패했는지, 조회는 됐는데 대안이 빈 배열이었는지를 구분한다.
        # 빈 배열은 BE 계약상 오류가 아니라 "대안 없음"이다(`TOOL_CONTRACT.md` 3.4절).
        all_failed = bool(ctx.candidates) and all(c.error is not None for c in ctx.candidates)
        return RerouteOutcome(
            status=RerouteStatus.UNAVAILABLE if all_failed else RerouteStatus.NO_ALTERNATIVE,
            decision=decision,
            context=ctx,
            detail="후보 경로 조회 실패" if all_failed else "대안 경로 없음",
        )

    # ── ④⑤ 선택·문장 ──
    proposal = strategy.decide(ctx)
    if proposal is None:
        # `has_alternative`가 True인데 전략이 못 골랐다 = 경로 응답 모양이 예상과 다르다.
        # "대안이 없다"고 단정할 근거가 아니라 "읽지 못했다"이다.
        return RerouteOutcome(
            status=RerouteStatus.UNAVAILABLE,
            decision=decision,
            context=ctx,
            detail="전략이 경로를 하나도 읽지 못했다",
        )

    return RerouteOutcome(
        status=RerouteStatus.PROPOSAL, proposal=proposal, decision=decision, context=ctx
    )


def _upcoming(
    stops: Sequence[Stop], *, current_seq: int, eta_minutes_by_seq: Mapping[int, int]
) -> list[tuple[Stop, int]]:
    """앞쪽 역과 그 역까지 남은 분. 진행 순서를 지킨다 — 연속 구간 판정이 순서에 의존한다.

    소요시간을 모르는 역은 뺀다. 도착 슬롯을 계산할 수 없어 '도착할 때'를 읽을 수 없고,
    0분으로 채우면 지금 혼잡도를 도착 혼잡도로 쓰는 셈이 된다.
    """
    ahead = [stop for stop in stops if stop.seq > current_seq]
    ahead.sort(key=lambda stop: stop.seq)
    return [
        (stop, eta_minutes_by_seq[stop.seq]) for stop in ahead if stop.seq in eta_minutes_by_seq
    ]


def _arrivals(
    *, adapter: ToolAdapter, guard: ToolGuard, station_id: str, route_id: str | None = None
) -> dict[str, Any] | None:
    """`get_arrivals` 한 번. 실패하면 None이고, 그 실패는 후보 생성 쪽에서 `unavailable`이 된다.

    실패를 빈 응답으로 바꾸지 않는다 — `candidates.generate`는 `status`가 `LIVE`가 아니면 후보를
    만들지 않으므로, 여기서 `{"status": "NO_INFO"}` 같은 것을 지어내면 조회 장애가 "탈 열차가
    없다"로 둔갑한다.
    """
    args = {"station_id": station_id}
    if route_id is not None:
        args["route_id"] = route_id
    result = guard.run(GET_ARRIVALS, lambda: adapter.call(GET_ARRIVALS, args), args)
    if is_error(result) or not isinstance(result, Mapping):
        return None
    return dict(result)


__all__ = [
    "ARRIVAL_STATUS_LIVE",
    "RerouteOutcome",
    "RerouteStatus",
    "propose_reroute",
]
