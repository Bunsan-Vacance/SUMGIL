"""후보 생성·프리페치가 주고받는 타입(S15P21A104-203/302).

**입력이 대여소로 바뀌었다.** 이전 판(경로상 하차 후보 `Stop`/`DropCandidate`)은 트리거 원천이
CROWD 혼잡 급등에서 따릉이 재고 고갈로 바뀌면서 폐기했다(`AI/app/TIME/AGENT_DESIGN.md` 2.2절
결정). 여기서 '후보'는 하차역이 아니라 **주변 따릉이 대여소**다.

`trigger.py`와 마찬가지로 **순수 데이터**다. 두 전략(`RuleStrategy`·`AgentStrategy`)이 완전히
같은 입력을 보게 하는 것이 목적이고, 그래야 7절 비교가 '표현의 차이'만 재게 된다
(`AI/CLAUDE.md` 모델 비교 하드 룰 2·3번).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.TIME.station_index import RentalStation
from app.TIME.trigger import StockReading, TriggerResult


@dataclass(frozen=True)
class RentalCandidate:
    """주변 대여소 후보 하나. `StationIndex.nearby()`가 낸 (역, 거리) 쌍을 그대로 옮겨 담는다."""

    station: RentalStation
    distance_m: float


@dataclass(frozen=True)
class CandidateContext:
    """후보 하나에 딸린 프리페치 결과."""

    candidate: RentalCandidate

    reading: StockReading | None = None
    """`get_eta_stock` 조회 결과. 조회가 실패했으면 `None`이고 `error`가 대신 채워진다."""

    error: dict[str, object] | None = None
    """조회가 실패했으면 `ToolError`를 직렬화한 것. 실패를 성공처럼 감추지 않는다."""

    @property
    def usable(self) -> bool:
        return self.error is None and self.reading is not None


@dataclass(frozen=True)
class AgentContext:
    """④⑤(후보 선택·문장 생성)에 넘어가는 완성된 입력.

    프리페치가 끝난 상태라 전략은 **도구를 더 부르지 않는다.** LLM 턴이 1회로 끝나는 근거이고
    (계획 1.1절), 두 전략이 같은 입력을 보는 근거이기도 하다.
    """

    decision: TriggerResult
    """트리거 판정. `facts`가 안내 문장이 인용할 사실 집합이다."""

    target: RentalStation
    """도착 시점에 비어 있을 것으로 예측된 대상 대여소."""

    target_reading: StockReading
    """대상 대여소의 `get_eta_stock` 결과. 트리거를 세운 바로 그 조회값이다."""

    eta_minutes: int
    """대상 대여소까지 남은 분. 후보마다 같은 값으로 `get_eta_stock`을 부른다(`planner.prefetch`)
    — 그래야 '지금 대상은 몇 분 뒤'와 '후보는 몇 분 뒤'가 다른 시점을 가리키지 않는다."""

    candidates: list[CandidateContext] = field(default_factory=list)
    dest_station_id: str | None = None

    @property
    def usable_candidates(self) -> list[CandidateContext]:
        return [c for c in self.candidates if c.usable]

    @property
    def has_alternative(self) -> bool:
        """쓸 수 있는 대안이 하나라도 있는지. False면 전략을 부르지 않고 기존 안내를 유지한다 —
        '대안 없음'과 '조회 실패'를 뭉개지 않으려고 `usable`이 둘 다 본다."""
        return bool(self.usable_candidates)


__all__ = ["AgentContext", "CandidateContext", "RentalCandidate"]
