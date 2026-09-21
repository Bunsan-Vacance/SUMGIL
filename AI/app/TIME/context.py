"""후보 생성·프리페치가 주고받는 타입(S15P21A104-203).

`trigger.py`와 마찬가지로 **순수 데이터**다. 두 전략(`RuleStrategy`·`AgentStrategy`)이 완전히
같은 입력을 보게 하는 것이 목적이고, 그래야 7절 비교가 '표현의 차이'만 재게 된다
(`AI/CLAUDE.md` 모델 비교 하드 룰 2·3번).

**정차역 목록을 인자로 받는 이유**: BE `RouteLegResponse`는 같은 노선의 연속 구간을 leg 하나로
합쳐서(`RouteMapper.toLeg`) 중간 정차역이 응답에 남지 않는다. 그 목록을 어디서 얻을지는 BE 회신
대기 중이라(`TO_BE-time-station-sequence-01`), 공급원과 로직을 분리해 둔다 — 회신이 오면
공급원만 연결하면 된다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.TIME.trigger import TriggerDecision


@dataclass(frozen=True)
class Stop:
    """경로상 정차역 하나. 두 ID를 같이 들고 다닌다.

    `station_no`는 CROWD 혼잡도 조회 키(int), `station_id`는 BE `replan`의 `boundaryId`(str)다.
    대응 규칙이 아직 확정되지 않아(`TO_BE-time-station-sequence-01` 3절) 둘 중 하나만 채워질 수
    있다 — 그래서 각각 nullable이고, 쓰는 쪽이 필요한 것이 있는지 확인한다.
    """

    seq: int
    """경로 진행 순서. 작을수록 먼저 지난다."""

    station_id: str | None = None
    station_no: int | None = None
    name: str | None = None
    is_transfer: bool = False
    """환승 가능 역인지. 모르면 False — 모른다고 후보에서 빼지는 않는다(`candidates.py` 참고)."""


@dataclass(frozen=True)
class DropCandidate:
    """하차 후보역 하나. `replan`의 `boundaryId`가 될 자리다."""

    stop: Stop
    eta_minutes: int
    """현재 위치에서 이 역까지 걸리는 분. 도착 슬롯 계산과 안내 문장에 쓴다."""

    rank_hint: int = 0
    """정렬 힌트(작을수록 우선). 환승역 우대 같은 약한 선호만 담고, **최종 선택은 하지 않는다** —
    선택은 전략(④)의 몫이다."""


@dataclass(frozen=True)
class CandidateContext:
    """후보 하나에 딸린 프리페치 결과."""

    candidate: DropCandidate
    routes: list[dict[str, Any]] = field(default_factory=list)
    """`replan_route`가 준 잔여 경로 후보. **BE 응답 그대로**다 — legs·소요시간을 가공하지 않는다."""

    error: dict[str, Any] | None = None
    """조회가 실패했으면 `ToolError`를 직렬화한 것. 실패를 빈 목록으로 감추지 않는다."""

    @property
    def usable(self) -> bool:
        return self.error is None and bool(self.routes)


@dataclass(frozen=True)
class AgentContext:
    """④⑤(후보 선택·문장 생성)에 넘어가는 완성된 입력.

    프리페치가 끝난 상태라 전략은 **도구를 더 부르지 않는다.** LLM 턴이 1회로 끝나는 근거이고
    (계획 1.1절), 두 전략이 같은 입력을 보는 근거이기도 하다.
    """

    decision: TriggerDecision
    """트리거 판정. `facts`가 안내 문장이 인용할 사실 집합이다."""

    candidates: list[CandidateContext] = field(default_factory=list)
    current_route_id: str | None = None
    """지금 타고 있는 노선. `exclude_route_ids`가 확정되기 전까지는 이 값으로 사후 필터링한다
    (`TO_BE-time-reroute-contract-01` 1번)."""

    dest_station_id: str | None = None

    @property
    def usable_candidates(self) -> list[CandidateContext]:
        return [c for c in self.candidates if c.usable]

    @property
    def has_alternative(self) -> bool:
        """쓸 수 있는 대안이 하나라도 있는지. False면 전략을 부르지 않고 기존 안내를 유지한다 —
        '대안 없음'과 '조회 실패'를 뭉개지 않으려고 `usable`이 둘 다 본다."""
        return bool(self.usable_candidates)
