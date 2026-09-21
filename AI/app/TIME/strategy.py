"""후보 선택·안내 문장 생성(S15P21A104-203) — 계획 1절의 ④⑤ 노드.

여기가 **LLM을 갈아끼우는 유일한 자리**다. ①트리거·②후보·③프리페치는 두 구현에서 완전히
같고, 이 모듈만 바뀐다. 그래야 7절 비교가 '표현의 차이'만 재고 '입력의 차이'를 재지 않는다
(`AI/CLAUDE.md` 모델 비교 하드 룰 2·3번).

`RuleStrategy`는 LLM·API 키 없이 완전히 동작한다. 기준선이면서 동시에 **운영 폴백**이다 —
게이트웨이가 죽어도 재안내는 계속 나간다.

**경로를 다시 쓰지 않는다.** 전략은 후보를 *가리키기만* 하고, legs·소요시간·거리는 BE 응답을
그대로 들고 나간다. `AgentStrategy`가 `chosen_index`만 받는 것도 같은 이유다 — LLM이 경로를
다시 쓰게 두면 역 이름과 분이 조용히 각색된다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol, Sequence

from app.TIME.context import AgentContext, CandidateContext

DEFAULT_TRANSFER_PENALTY_MIN = 4.0
DEFAULT_CONGESTION_PENALTY_MIN = 3.0
"""점수 가중치 기본값. **잠정값**이다 — 근거는 `app/core/config.py`의 time_score_* 주석."""


@dataclass(frozen=True)
class ScoreWeights:
    transfer_penalty_min: float = DEFAULT_TRANSFER_PENALTY_MIN
    congestion_penalty_min: float = DEFAULT_CONGESTION_PENALTY_MIN

    @classmethod
    def from_settings(cls, settings: object) -> ScoreWeights:
        return cls(
            transfer_penalty_min=getattr(
                settings, "time_score_transfer_penalty_min", DEFAULT_TRANSFER_PENALTY_MIN
            ),
            congestion_penalty_min=getattr(
                settings, "time_score_congestion_penalty_min", DEFAULT_CONGESTION_PENALTY_MIN
            ),
        )


@dataclass(frozen=True)
class RerouteProposal:
    """재안내 하나. FE 팝업에 그대로 대응한다."""

    candidate_index: int
    """`AgentContext.usable_candidates`에서의 위치. 경로 본문이 아니라 **가리키는 값**이다."""

    route: dict[str, Any]
    """고른 잔여 경로. BE 응답 그대로 — 전략이 가공하지 않는다."""

    reason: str
    """안내 문장. `RerouteResponse.reason` 자리에 들어간다."""

    source: str
    """`ALGORITHM`(규칙) 또는 `AGENT`(LLM). 후자는 BE 회신 대기 중이다
    (`TO_BE-time-reroute-contract-01` 2번)."""

    score: float | None = None
    """규칙 전략이 매긴 점수. LLM 전략은 None. 204 평가에서 두 선택을 견줄 때 쓴다."""


SOURCE_ALGORITHM = "ALGORITHM"
SOURCE_AGENT = "AGENT"


class RerouteStrategy(Protocol):
    """후보들 중 하나를 고르고 문장을 만든다. 고를 게 없으면 None."""

    def decide(self, ctx: AgentContext) -> RerouteProposal | None: ...


class RuleStrategy:
    """LLM 없는 기준선. 점수가 가장 낮은 후보를 고르고 템플릿으로 문장을 만든다.

    점수식: `잔여소요(분) + 환승 횟수 × 환승페널티 + 혼잡등급 × 혼잡페널티` (작을수록 좋다)

    **가중치는 잠정값이다.** 실제 후보 분포를 보지 못했다 — 트리거 임계값과 같은 처지라
    `Settings` 노브로 빼두고, 표를 확보하면 같이 다시 정한다.
    """

    def __init__(self, weights: ScoreWeights | None = None) -> None:
        self.weights = weights or ScoreWeights()

    def decide(self, ctx: AgentContext) -> RerouteProposal | None:
        # "대안 없음"과 "조회 실패"를 뭉개지 않는다 — usable이 둘 다 본다(`context.py`).
        if not ctx.has_alternative:
            return None

        best: tuple[float, int, dict[str, Any]] | None = None
        for index, candidate in enumerate(ctx.usable_candidates):
            for route in candidate.routes:
                score = self.score(route)
                if score is None:
                    continue  # 소요시간을 못 읽은 경로는 점수를 매길 수 없다. 지어내지 않는다
                if best is None or score < best[0]:
                    best = (score, index, route)

        if best is None:
            # 후보는 있는데 하나도 점수를 못 냈다 — 응답 모양이 예상과 다르다는 뜻이라
            # 임의로 하나를 고르지 않는다(모르는 채로 안내하지 않는다).
            return None

        score, index, route = best
        candidate = ctx.usable_candidates[index]
        return RerouteProposal(
            candidate_index=index,
            route=route,
            reason=build_reason(ctx, candidate, route),
            source=SOURCE_ALGORITHM,
            score=score,
        )

    def score(self, route: Mapping[str, Any]) -> float | None:
        """작을수록 좋다. 소요시간을 못 읽으면 None."""
        minutes = _total_minutes(route)
        if minutes is None:
            return None
        transfers = _transfer_count(route) or 0
        grade = _max_grade(route) or 0
        return (
            minutes
            + transfers * self.weights.transfer_penalty_min
            + grade * self.weights.congestion_penalty_min
        )


# ── 안내 문장 ──


def build_reason(ctx: AgentContext, candidate: CandidateContext, route: Mapping[str, Any]) -> str:
    """템플릿으로 문장을 만든다. **`decision.facts`와 경로에 실제로 있는 값만 쓴다.**

    규칙 전략이 LLM보다 정직한 지점이 여기다 — 템플릿은 자리에 넣을 값이 없으면 그 문장을
    통째로 빼지, 그럴듯한 숫자를 만들지 않는다.

    문구가 **"지금 혼잡하다"가 아니라 "도착할 시점에 혼잡해진다"**인 이유는 CROWD가 하루 1회
    배치 산출물이기 때문이다(`facts["is_prediction"]`). 실시간인 척하면 데이터-검증-리포트의
    "추정 데이터는 변화율로 쓴다" 원칙을 깨는 것이다.
    """
    facts = ctx.decision.facts
    parts: list[str] = []

    where = candidate.candidate.stop.name
    eta = candidate.candidate.eta_minutes
    if where:
        parts.append(f"{where}에서 내려 갈아타시는 건 어떨까요.")
    else:
        parts.append("다음 역에서 내려 갈아타시는 건 어떨까요.")

    worst = facts.get("worst_station_name")
    worst_eta = facts.get("worst_eta_minutes")
    grade_from = facts.get("worst_grade_from")
    grade_to = facts.get("worst_grade_to")
    if worst and worst_eta is not None and grade_from is not None and grade_to is not None:
        parts.append(
            f"{worst_eta}분 뒤 {worst} 도착 시점에 혼잡도가 "
            f"{grade_from}등급에서 {grade_to}등급으로 올라갈 것으로 보입니다."
        )
    elif worst:
        parts.append(f"{worst} 부근이 지금보다 혼잡해질 것으로 보입니다.")

    minutes = _total_minutes(route)
    transfers = _transfer_count(route)
    if minutes is not None:
        tail = f"갈아타면 남은 거리는 약 {round(minutes)}분"
        if transfers is not None:
            tail += f", 환승 {transfers}회"
        parts.append(tail + "입니다.")

    if eta is not None and where:
        parts.append(f"{where}까지는 약 {eta}분 남았습니다.")

    # 공휴일에 일요일 배율을 빌려 쓴 값이면 그 사실을 밝힌다(SERVING_CONTRACT.md 2절).
    # 숨기면 사용자가 평소와 같은 정확도로 믿는다.
    if facts.get("calibration_fallback_used"):
        parts.append("(공휴일이라 일요일 기준 혼잡도로 추정한 값입니다.)")

    return " ".join(parts)


# ── 경로 읽기 ──
# BE 응답은 `{reason, source, route:{...}}`이지만 래퍼 없이 경로 객체가 오는 모양도 받아 둔다 —
# 응답 모양이 회신 대기 중이라(`TO_BE-time-reroute-contract-01`) 한쪽만 보면 조용히 0점이 된다.


def _route_body(route: Mapping[str, Any]) -> Mapping[str, Any]:
    inner = route.get("route")
    return inner if isinstance(inner, Mapping) else route


def _total_minutes(route: Mapping[str, Any]) -> float | None:
    body = _route_body(route)
    value = body.get("totalMinutes")
    if isinstance(value, (int, float)):
        return float(value)
    # totalMinutes가 없으면 legs 합으로 낸다. 계약상 둘은 0.01분 이내로 일치한다.
    legs = body.get("legs")
    if not isinstance(legs, Sequence) or isinstance(legs, (str, bytes)):
        return None
    total = 0.0
    found = False
    for leg in legs:
        if isinstance(leg, Mapping) and isinstance(leg.get("minutes"), (int, float)):
            total += float(leg["minutes"])
            found = True
    return total if found else None


def _transfer_count(route: Mapping[str, Any]) -> int | None:
    value = _route_body(route).get("transferCount")
    return int(value) if isinstance(value, int) else None


def _max_grade(route: Mapping[str, Any]) -> int | None:
    """경로 구간 중 가장 혼잡한 등급. BE 응답에 없으면 None(0으로 치지 않는다).

    없는 것을 0(=쾌적)으로 치면 혼잡 정보가 없는 경로가 가장 좋아 보인다. None을 돌려주고
    호출자가 `or 0`으로 중립 처리하되, 그 선택이 보이는 자리에 있게 한다.
    """
    legs = _route_body(route).get("legs")
    if not isinstance(legs, Sequence) or isinstance(legs, (str, bytes)):
        return None
    grades = [
        int(leg["congestionGrade"])
        for leg in legs
        if isinstance(leg, Mapping) and isinstance(leg.get("congestionGrade"), int)
    ]
    return max(grades) if grades else None
