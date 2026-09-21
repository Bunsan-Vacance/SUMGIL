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

import json
import re
from collections import Counter
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Mapping, Protocol, Sequence

from app.TIME.context import AgentContext, CandidateContext
from app.TIME.llm import LlmClient, LlmError, LlmResult
from app.TIME.llm_budget import LlmBudget

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
        return _score_route(route, self.weights)


def _score_route(route: Mapping[str, Any], weights: ScoreWeights) -> float | None:
    """`RuleStrategy.score`의 실제 계산. 모듈 함수로 뺀 이유는 `_best_route`(아래)도 같은
    식으로 후보 안의 경로를 고르게 하기 위해서다 — `describe_candidate`와 `AgentStrategy`가
    "선택 후보의 경로"를 규칙 전략과 같은 방식으로 고르게 한다."""
    minutes = _total_minutes(route)
    if minutes is None:
        return None
    transfers = _transfer_count(route) or 0
    grade = _max_grade(route) or 0
    return (
        minutes + transfers * weights.transfer_penalty_min + grade * weights.congestion_penalty_min
    )


def _best_route(
    routes: Sequence[Mapping[str, Any]], weights: ScoreWeights
) -> Mapping[str, Any] | None:
    """후보 안에서 점수가 가장 낮은 경로. 점수를 못 낸 경로는 건너뛴다(`RuleStrategy.decide`와
    같은 규칙). `describe_candidate`·`AgentStrategy`가 같은 방식으로 경로를 고르는 한곳이다."""
    best: tuple[float, Mapping[str, Any]] | None = None
    for route in routes:
        score = _score_route(route, weights)
        if score is None:
            continue
        if best is None or score < best[0]:
            best = (score, route)
    return best[1] if best else None


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


# ── 후보 요약(LLM 프롬프트·A/C 접점) ──


def describe_candidate(ctx: AgentContext, index: int, weights: ScoreWeights | None = None) -> str:
    """후보 하나(`ctx.usable_candidates[index]`)를 한 줄 한국어 요약으로 바꾼다.

    **이 함수가 `AgentStrategy`와 다른 청크(C, 따릉이 트리거·후보) 사이의 유일한 접점이다.**
    203 마스터 설계 3.0절대로 트리거 원천이 혼잡도에서 따릉이로 바뀌면 후보의 정체가 "경로"에서
    "대여소"로 바뀌지만, 프롬프트가 후보를 문장으로 읽는 자리는 여기 하나뿐이다 — C는 이 함수만
    확장하고(예: 대여소 재고 문구 추가) `AgentStrategy` 본문은 건드리지 않는다.

    `RuleStrategy`가 점수 매기는 것과 같은 경로 선택(`_best_route`)을 쓴다 — 프롬프트에 보여주는
    경로와 규칙 전략이 실제로 고르는 경로가 다르면 LLM이 잘못된 근거로 판단하게 된다. `weights`를
    받는 이유도 같다 — 호출자가 `RuleStrategy`와 다른 가중치를 쓰면 "규칙과 같은 경로"라는 위
    약속이 깨지므로, 기본값(`None` → `ScoreWeights()`)에 기대지 말고 실제로 쓰는 가중치를 전달할
    것. 값을 못 읽은 항목은 자리를 통째로 뺀다(`build_reason`과 같은 원칙 — 없는 숫자를 지어내지
    않는다).
    """
    candidate = ctx.usable_candidates[index]
    where = candidate.candidate.stop.name or "이름 미상 역"
    eta = candidate.candidate.eta_minutes

    bits = [f"{index}. {where} — {eta}분 후 도착"]

    route = _best_route(candidate.routes, weights or ScoreWeights())
    if route is not None:
        minutes = _total_minutes(route)
        if minutes is not None:
            bits.append(f"잔여 {round(minutes)}분")
        transfers = _transfer_count(route)
        if transfers is not None:
            bits.append(f"환승 {transfers}회")
        grade = _max_grade(route)
        if grade is not None:
            bits.append(f"최고 혼잡 {grade}등급")

    return ", ".join(bits)


# ── LLM 전략 ──


class RejectReason(StrEnum):
    """LLM 출력이 탈락한 이유. `AgentStrategy.rejections`가 이 값으로 센다(204 평가 입력)."""

    LLM_ERROR = "LLM_ERROR"
    """게이트웨이 호출 자체가 실패했다(`llm.LlmError`) — 설정 없음·타임아웃·5xx 등."""

    BAD_JSON = "BAD_JSON"
    """응답이 JSON이 아니거나 `chosen_index`/`reason` 필드가 없거나 타입이 안 맞는다."""

    INDEX_OUT_OF_RANGE = "INDEX_OUT_OF_RANGE"
    """`chosen_index`가 `usable_candidates` 범위 밖이다."""

    UNKNOWN_NUMBER = "UNKNOWN_NUMBER"
    """`reason`에 facts·후보 요약 어디에도 없는 숫자가 나왔다 — 지어낸 값일 가능성이 크다."""

    WRONG_CANDIDATE_NAME = "WRONG_CANDIDATE_NAME"
    """선택하지 않은 다른 후보의 역 이름이 `reason`에 등장한다."""

    MISSING_CHOSEN_NAME = "MISSING_CHOSEN_NAME"
    """선택한 후보에 역 이름이 있는데 `reason`이 그 이름을 언급하지 않는다."""

    TOO_LONG = "TOO_LONG"
    """문장 수·글자 수 상한을 넘었다(잠정값, `Settings.time_agent_reason_max_*`)."""

    BUDGET_EXCEEDED = "BUDGET_EXCEEDED"
    """이 세션의 LLM 호출·토큰 예산을 다 썼다(`llm_budget.LlmBudget`)."""


def _system_prompt(max_sentences: int, max_chars: int) -> str:
    """역할·출력 규칙. 문장·글자 상한은 `AgentStrategy`가 실제로 검사하는 값과 어긋나지
    않도록 인자로 받아 그대로 박아 넣는다 — 프롬프트 문구와 검증 로직의 숫자가 따로 놀면
    LLM은 지켰다고 생각한 규칙에 걸려 탈락한다."""
    return (
        "당신은 지하철 실시간 재탐색 안내 에이전트다. 아래 [사실]과 [후보] 목록만 보고 후보 중 "
        '하나를 골라 정확히 이 JSON 형식으로만 답하라: {"chosen_index": <정수>, "reason": <문자열>}. '
        "chosen_index는 [후보] 목록의 번호 그대로여야 한다. "
        "reason에는 경로·역 이름·숫자를 새로 만들지 말고 [사실]과 [후보]에 실제로 나온 값만 "
        f"인용해 한국어 {max_sentences}문장 이내, {max_chars}자 이내로 써라. "
        "data_status가 'calibration_fallback'이면 그 사실을 밝히고, "
        "'no_lookup'류 결측값은 혼잡으로 해석하지 말 것 — 각 필드의 의미는 도구 설명을 따른다."
    )


def _build_user_prompt(ctx: AgentContext, weights: ScoreWeights) -> str:
    """`decision.facts`를 표로, `describe_candidate()` 결과를 번호 목록으로 늘어놓는다.

    두 전략이 같은 입력을 보게 하는 `AgentContext`(`context.py` 모듈 docstring)를 그대로
    문장으로 옮기는 자리라, 여기서 값을 가공하지 않는다 — facts에 없는 값을 계산해 넣으면
    `AgentStrategy`와 `RuleStrategy`가 보는 "사실"이 달라진다. `weights`는 `describe_candidate`로
    그대로 넘겨 프롬프트에 보여주는 경로가 실제 폴백(`RuleStrategy`)이 고르는 경로와 같게 한다.
    """
    lines = ["[사실]"]
    for key, value in ctx.decision.facts.items():
        lines.append(f"- {key}: {value}")
    lines.append("")
    lines.append("[후보]")
    for i in range(len(ctx.usable_candidates)):
        lines.append(describe_candidate(ctx, i, weights))
    return "\n".join(lines)


_NUMBER_RE = re.compile(r"-?\d+(?:\.\d+)?")


def _numbers_in(text: str) -> set[float]:
    """문자열에 나오는 정수·소수를 전부 뽑는다. 부호·소수점 형식 차이를 흡수하려고 float로
    정규화한다 — `"6"`과 `"6.0"`이 같은 숫자로 비교돼야 한다."""
    return {float(m) for m in _NUMBER_RE.findall(text)}


def _allowed_numbers(ctx: AgentContext, weights: ScoreWeights) -> set[float]:
    """`reason`이 지어내지 않았는지 검사할 숫자 허용집합.

    `decision.facts`의 수치 값 + 프롬프트에 실제로 보여준 후보 요약(`describe_candidate`)에
    나온 숫자를 모은다 — 둘 다 LLM이 프롬프트에서 **실제로 본** 숫자라 안전한 허용집합이다.
    facts의 불린 값은 `isinstance(x, int)`가 True로 나와 숫자로 섞일 수 있어 따로 뺀다.
    `weights`는 `describe_candidate`가 프롬프트에 보여준 것과 같은 경로를 고르도록
    `_build_user_prompt`와 같은 값을 받는다 — 안 그러면 프롬프트에는 없던 숫자가 허용집합에
    섞이거나, 프롬프트에 있던 숫자가 빠질 수 있다.
    """
    numbers: set[float] = set()
    for value in ctx.decision.facts.values():
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            numbers.add(float(value))
    for i in range(len(ctx.usable_candidates)):
        numbers |= _numbers_in(describe_candidate(ctx, i, weights))
    return numbers


_SENTENCE_SPLIT_RE = re.compile(r"(?<!\d)\.(?!\d)|[!?]+")
"""문장 구분자. 숫자 사이의 마침표(`0.62`)는 걸러야 한다 — 그냥 `[.!?]+`로 자르면 `p_empty`
같은 0~1 소수 하나가 낀 정상 한 문장이 두 문장으로 세어져 TOO_LONG으로 잘못 탈락한다."""


def _sentence_count(text: str) -> int:
    """대략적인 문장 수. 마침표·물음표·느낌표로 끊고 빈 조각은 세지 않는다."""
    return len([piece for piece in _SENTENCE_SPLIT_RE.split(text) if piece.strip()])


def _parse_decision(text: str) -> tuple[int, str] | None:
    """LLM 응답 본문에서 `(chosen_index, reason)`을 뽑는다. 형식이 조금이라도 어긋나면
    전부 `None`이다 — 호출자가 `RejectReason.BAD_JSON` 하나로 묶어 폴백으로 넘어간다."""
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(data, dict):
        return None

    chosen_index = data.get("chosen_index")
    reason = data.get("reason")
    if not isinstance(chosen_index, int) or isinstance(chosen_index, bool):
        return None
    if not isinstance(reason, str) or not reason.strip():
        return None
    return chosen_index, reason


class AgentStrategy:
    """LLM이 후보를 고르고 이유를 쓰는 전략. `chosen_index`와 `reason`만 받는다 — 모듈
    docstring이 못박은 "LLM을 갈아끼우는 유일한 자리"의 실제 구현이다.

    환각 검사(`RejectReason` 6종 — LLM 오류·예산 초과 포함 8종)를 통과해야 LLM의 선택을 쓴다.
    **하나라도 탈락하면 `fallback`의 결과를 그대로 돌려준다**(source도 `fallback`이 정한 값
    그대로, 보통 `RuleStrategy`라 `SOURCE_ALGORITHM`). 이 청크(203-A)가 끝나도 서비스 동작이
    나빠질 수 없다는 계획 전제가 여기서 지켜진다.

    `weights`를 안 주면 `fallback`의 가중치를 물려받는다 — 프롬프트에 보여주는 경로·최종
    채택 경로가 `fallback`이 실제로 고르는 경로와 어긋나면 안 되기 때문이다(`describe_candidate`
    docstring 참고).
    """

    def __init__(
        self,
        client: LlmClient,
        fallback: RerouteStrategy,
        *,
        budget: LlmBudget | None = None,
        weights: ScoreWeights | None = None,
        max_sentences: int = 2,
        max_chars: int = 120,
    ) -> None:
        self.client = client
        self.fallback = fallback
        self.budget = budget if budget is not None else LlmBudget()
        # weights를 안 주면 fallback(보통 RuleStrategy)의 가중치를 그대로 물려받는다 —
        # 그래야 이 전략이 프롬프트에 보여주고 최종 route로 고르는 경로가 fallback이 실제로
        # 고르는 경로와 같아진다. RuleStrategy가 아닌 폴백처럼 `weights` 속성이 없으면
        # 기본값으로 떨어진다.
        self.weights = (
            weights
            if weights is not None
            else (getattr(fallback, "weights", None) or ScoreWeights())
        )
        self.max_sentences = max_sentences
        self.max_chars = max_chars
        self.rejections: Counter[RejectReason] = Counter()
        """탈락 사유 누적 카운터. 204 평가 하네스가 읽는다 — 공개 속성이라 세션이 끝난 뒤
        그대로 집계에 쓸 수 있다."""
        self.last_usage: LlmResult | None = None
        """가장 최근 **성공한** LLM 호출의 사용량·지연. 실패 호출은 갱신하지 않는다 — 실패에는
        낼 토큰 수 자체가 없다."""

    def decide(self, ctx: AgentContext) -> RerouteProposal | None:
        # "대안 없음"은 규칙 전략과 같은 판단이다 — LLM을 불러도 고를 것이 없다.
        if not ctx.has_alternative:
            return None

        budget_error = self.budget.check()
        if budget_error is not None:
            return self._reject(RejectReason.BUDGET_EXCEEDED, ctx)

        system = _system_prompt(self.max_sentences, self.max_chars)
        outcome = self.client.complete(system=system, user=_build_user_prompt(ctx, self.weights))
        if isinstance(outcome, LlmError):
            return self._reject(RejectReason.LLM_ERROR, ctx)
        self.last_usage = outcome
        self.budget.record(outcome)

        parsed = _parse_decision(outcome.text)
        if parsed is None:
            return self._reject(RejectReason.BAD_JSON, ctx)
        chosen_index, reason = parsed

        candidates = ctx.usable_candidates
        if not (0 <= chosen_index < len(candidates)):
            return self._reject(RejectReason.INDEX_OUT_OF_RANGE, ctx)

        if not _numbers_in(reason) <= _allowed_numbers(ctx, self.weights):
            return self._reject(RejectReason.UNKNOWN_NUMBER, ctx)

        chosen_name = candidates[chosen_index].candidate.stop.name
        other_names = {
            c.candidate.stop.name
            for i, c in enumerate(candidates)
            if i != chosen_index and c.candidate.stop.name
        }
        if any(name in reason for name in other_names):
            return self._reject(RejectReason.WRONG_CANDIDATE_NAME, ctx)

        if chosen_name and chosen_name not in reason:
            return self._reject(RejectReason.MISSING_CHOSEN_NAME, ctx)

        if _sentence_count(reason) > self.max_sentences or len(reason) > self.max_chars:
            return self._reject(RejectReason.TOO_LONG, ctx)

        chosen = candidates[chosen_index]
        # RuleStrategy와 같은 방식·같은 가중치로 고른 경로. 못 고르면(응답 모양이 예상과
        # 다르면) 첫 경로로 물러난다 — `usable`이 보장하듯 routes는 비어 있지 않다.
        best = _best_route(chosen.routes, self.weights)
        route = best if best is not None else chosen.routes[0]
        return RerouteProposal(
            candidate_index=chosen_index,
            route=route,
            reason=reason,
            source=SOURCE_AGENT,
            score=None,
        )

    def _reject(self, reason: RejectReason, ctx: AgentContext) -> RerouteProposal | None:
        self.rejections[reason] += 1
        return self.fallback.decide(ctx)
