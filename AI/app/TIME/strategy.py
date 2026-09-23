"""후보 선택·안내 문장 생성(S15P21A104-203/302) — 계획 1절의 ④⑤ 노드.

여기가 **LLM을 갈아끼우는 유일한 자리**다. ①트리거·②후보·③프리페치는 두 구현에서 완전히
같고, 이 모듈만 바뀐다. 그래야 7절 비교가 '표현의 차이'만 재고 '입력의 차이'를 재지 않는다
(`AI/CLAUDE.md` 모델 비교 하드 룰 2·3번).

`RuleStrategy`는 LLM·API 키 없이 완전히 동작한다. 기준선이면서 동시에 **운영 폴백**이다 —
게이트웨이가 죽어도 재안내는 계속 나간다.

**후보를 가리키기만 한다.** 전략은 `candidate_index`만 내고, 하차역→대안 도보 합성과
대안→목적지 경로 연결(⑥)은 `service.py`가 선택 **이후**에 한다(계획 2.5절) — 전략 자리에서는
아직 경로가 없다.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from app.TIME.context import AgentContext, CandidateContext
from app.TIME.llm import LlmClient, LlmError, LlmResult
from app.TIME.llm_budget import LlmBudget
from app.TIME.station_index import WALK_SPEED_M_PER_MIN
from app.TIME.trigger import StockReading

DEFAULT_WALK_SPEED_M_PER_MIN = WALK_SPEED_M_PER_MIN
"""`station_index.WALK_SPEED_M_PER_MIN`과 같은 값이다 — 후보 순위 근사(여기)와 실제 `walkLeg`
합성(`service.build_walk_leg`)이 다른 속도를 쓰면 순위와 표시 분(分)이 어긋난다."""
DEFAULT_EMPTY_PENALTY_MIN = 10.0
"""점수 가중치 기본값. **잠정값**이다 — 근거는 `app/core/config.py`의 time_score_* 주석."""


@dataclass(frozen=True)
class ScoreWeights:
    walk_speed_m_per_min: float = DEFAULT_WALK_SPEED_M_PER_MIN
    empty_penalty_min: float = DEFAULT_EMPTY_PENALTY_MIN

    @classmethod
    def from_settings(cls, settings: object) -> ScoreWeights:
        # walk_speed_m_per_min은 `Settings`에 대응 노브가 없다 — `station_index.WALK_SPEED_M_PER_MIN`
        # (67)을 상수로 박아뒀다(도보 속도는 후보 사이 상대 순위에만 쓰여 절댓값 튜닝 필요성이
        # 낮다). 고갈 페널티만 `Settings` 노브다.
        return cls(
            empty_penalty_min=getattr(
                settings, "time_score_empty_penalty_min", DEFAULT_EMPTY_PENALTY_MIN
            ),
        )


@dataclass(frozen=True)
class RerouteProposal:
    """재안내 하나. FE 팝업에 그대로 대응한다."""

    candidate_index: int
    """`AgentContext.usable_candidates`에서의 위치. 경로 본문이 아니라 **가리키는 값**이다."""

    reason: str
    """안내 문장. `RerouteResponse.reason` 자리에 들어간다."""

    recommended_by: str
    """`ALGORITHM`(규칙) 또는 `AGENT`(LLM). BE `replan_route`의 `source`(=탐색 주체, 항상
    `ALGORITHM`)와는 다른 축이다 — "누가 골랐나"는 별도 필드로 싣기로 했다
    (`TOOL_CONTRACT.md` 6절 2번)."""

    score: float | None = None
    """규칙 전략이 매긴 점수. LLM 전략은 None. 204 평가에서 두 선택을 견줄 때 쓴다."""


RECOMMENDED_BY_ALGORITHM = "ALGORITHM"
RECOMMENDED_BY_AGENT = "AGENT"


class RerouteStrategy(Protocol):
    """후보들 중 하나를 고르고 문장을 만든다. 고를 게 없으면 None."""

    def decide(self, ctx: AgentContext) -> RerouteProposal | None: ...


class RuleStrategy:
    """LLM 없는 기준선. 점수가 가장 낮은 후보를 고르고 템플릿으로 문장을 만든다.

    점수식: `도보소요(분) + p_empty × 고갈페널티` (작을수록 좋다). 도보소요는
    `distance_m / walk_speed_m_per_min`으로 근사한다(직선거리 기준 — 계획 2.5절의 도보 합성
    ×1.3 보정은 ⑥에서 실제 `walkLeg`를 만들 때만 쓰고, 여기 점수식은 후보 사이 상대 비교용이라
    보정 없이도 순위는 같다).

    **가중치는 잠정값이다.** 실제 후보 분포를 보지 못했다 — 트리거 임계값과 같은 처지라
    `Settings` 노브로 빼두고, 표를 확보하면 같이 다시 정한다.
    """

    def __init__(self, weights: ScoreWeights | None = None) -> None:
        self.weights = weights or ScoreWeights()

    def decide(self, ctx: AgentContext) -> RerouteProposal | None:
        # "대안 없음"과 "조회 실패"를 뭉개지 않는다 — usable이 둘 다 본다(`context.py`).
        if not ctx.has_alternative:
            return None

        best_index: int | None = None
        best_key: tuple[float, float] | None = None
        for index, candidate_ctx in enumerate(ctx.usable_candidates):
            score = self.score(candidate_ctx)
            if score is None:
                continue  # 값을 못 읽은 후보는 점수를 매길 수 없다. 지어내지 않는다
            key = (score, candidate_ctx.candidate.distance_m)  # 동점이면 가까운 쪽
            if best_key is None or key < best_key:
                best_key = key
                best_index = index

        if best_index is None or best_key is None:
            # 후보는 있는데 하나도 점수를 못 냈다 — 응답 모양이 예상과 다르다는 뜻이라
            # 임의로 하나를 고르지 않는다(모르는 채로 안내하지 않는다).
            return None

        candidate_ctx = ctx.usable_candidates[best_index]
        return RerouteProposal(
            candidate_index=best_index,
            reason=build_reason(ctx, candidate_ctx),
            recommended_by=RECOMMENDED_BY_ALGORITHM,
            score=best_key[0],
        )

    def score(self, candidate_ctx: CandidateContext) -> float | None:
        """작을수록 좋다. 판단 근거(비어 있을 확률)를 아예 못 읽으면 None."""
        return _score_candidate(candidate_ctx, self.weights)


def _score_candidate(candidate_ctx: CandidateContext, weights: ScoreWeights) -> float | None:
    reading = candidate_ctx.reading
    if reading is None:
        return None
    p_empty = _p_empty_or_proxy(reading)
    if p_empty is None:
        return None
    walk_minutes = candidate_ctx.candidate.distance_m / weights.walk_speed_m_per_min
    return walk_minutes + p_empty * weights.empty_penalty_min


def _p_empty_or_proxy(reading: StockReading) -> float | None:
    """`p_empty`가 없으면(분류기 미탑재) `predicted_stock`으로 거친 근사치를 쓴다.

    근사 규칙을 값을 지어내는 것과 구분해 명시적으로 남긴다 — 예측 재고가 1대 이하면 "거의
    확실히 빈다"(1.0), 그 밖이면 "비지 않을 것"(0.0)으로 본다. `predicted_stock`마저 없으면
    판단 근거가 아예 없어 `None`을 돌려주고, 그 후보는 점수를 매기지 않는다(지어내지 않는다).
    """
    if reading.p_empty is not None:
        return reading.p_empty
    if reading.predicted_stock is not None:
        return 1.0 if reading.predicted_stock <= 1 else 0.0
    return None


# ── 안내 문장 ──


def build_reason(ctx: AgentContext, candidate_ctx: CandidateContext) -> str:
    """템플릿으로 문장을 만든다. **대상·후보에 실제로 있는 값만 쓴다.**

    규칙 전략이 LLM보다 정직한 지점이 여기다 — 자리에 넣을 값이 없으면 그 괄호를 통째로 빼지,
    그럴듯한 숫자를 만들지 않는다. 두 문장(대상 상태 → 대안 제안) 이내, 120자 이내를 겨냥한다
    (`Settings.time_agent_reason_max_*`와 같은 잠정 상한).
    """
    target_name = ctx.target.name or "이 대여소"
    sentence1 = f"{target_name}은 도착 시점에 자전거가 없을 가능성이 높습니다"
    predicted_stock = ctx.target_reading.predicted_stock
    if predicted_stock is not None:
        sentence1 += f"(예상 재고 {predicted_stock:.1f}대)"
    sentence1 += "."

    alt = candidate_ctx.candidate.station
    alt_name = alt.name or "이 대여소"
    distance_m = round(candidate_ctx.candidate.distance_m)
    sentence2 = f"{distance_m}m 떨어진 {alt_name}로 바꾸시면 어떨까요."

    return f"{sentence1} {sentence2}"


# ── 후보 요약(LLM 프롬프트·204 평가 접점) ──


def describe_candidate(ctx: AgentContext, index: int) -> str:
    """후보 하나(`ctx.usable_candidates[index]`)를 한 줄 한국어 요약으로 바꾼다.

    값을 못 읽은 항목은 자리를 통째로 뺀다(`build_reason`과 같은 원칙 — 없는 숫자를 지어내지
    않는다). `usable_candidates`만 대상이라 `reading`은 항상 채워져 있지만, 그 안의 개별 필드
    (`current_stock`·`predicted_stock`·`p_empty`)는 여전히 `None`일 수 있다.
    """
    candidate_ctx = ctx.usable_candidates[index]
    station = candidate_ctx.candidate.station
    reading = candidate_ctx.reading
    name = station.name or "이름 미상 대여소"
    distance_m = round(candidate_ctx.candidate.distance_m)

    bits = [f"{index}. {name} — 도보 약 {distance_m}m"]
    if reading is not None:
        if reading.current_stock is not None:
            bits.append(f"현재 {reading.current_stock}대")
        if reading.predicted_stock is not None:
            bits.append(f"도착 시 예상 {reading.predicted_stock:.1f}대")
        if reading.p_empty is not None:
            bits.append(f"비어 있을 확률 {reading.p_empty * 100:.0f}%")

    return ", ".join(bits)


def _target_facts_lines(ctx: AgentContext) -> list[str]:
    """대상 대여소 사실을 줄 목록으로. `describe_candidate`와 같은 원칙 — 없는 값은 줄 자체를
    뺀다. `_build_user_prompt`와 `_allowed_numbers`가 같은 줄을 본다(둘이 어긋나면 프롬프트에
    안 보여준 숫자가 허용되거나, 보여준 숫자가 막힌다).

    331 2단계 — `decision.facts`를 그대로 나열하던 `[사실]` 블록을 없애면서, 여기 없던
    `p_full`·`source`를 흡수했다(값을 새로 계산하지 않고 그대로 옮기기만 한다). `facts`의
    나머지 키(`eta_minutes`·`current_stock`·`predicted_stock`·`p_empty`·`model_horizon_min`)는
    원래부터 이미 여기 있었다."""
    reading = ctx.target_reading
    lines = [f"- 대여소: {ctx.target.name or '이 대여소'}", f"- 도착까지: {ctx.eta_minutes}분"]
    if reading.current_stock is not None:
        lines.append(f"- 현재 재고: {reading.current_stock}대")
    if reading.predicted_stock is not None:
        lines.append(f"- 도착 시 예상 재고: {reading.predicted_stock:.1f}대")
    if reading.p_empty is not None:
        lines.append(f"- 비어 있을 확률: {reading.p_empty * 100:.0f}%")
    if reading.p_full is not None:
        lines.append(f"- 가득 찰 확률: {reading.p_full * 100:.0f}%")
    if reading.model_horizon_min is not None:
        lines.append(f"- 예측 horizon: {reading.model_horizon_min}분")
    if reading.source is not None:
        lines.append(f"- 예측 출처: {reading.source}")
    return lines


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
    """선택하지 않은 다른 후보의 대여소 이름이 `reason`에 등장한다."""

    MISSING_CHOSEN_NAME = "MISSING_CHOSEN_NAME"
    """선택한 후보에 이름이 있는데 `reason`이 그 이름을 언급하지 않는다."""

    TOO_LONG = "TOO_LONG"
    """문장 수·글자 수 상한을 넘었다(잠정값, `Settings.time_agent_reason_max_*`)."""

    BUDGET_EXCEEDED = "BUDGET_EXCEEDED"
    """이 세션의 LLM 호출·토큰 예산을 다 썼다(`llm_budget.LlmBudget`)."""


def _system_prompt(max_sentences: int, max_chars: int) -> str:
    """역할·출력 규칙. 문장·글자 상한은 `AgentStrategy`가 실제로 검사하는 값과 어긋나지
    않도록 인자로 받아 그대로 박아 넣는다 — 프롬프트 문구와 검증 로직의 숫자가 따로 놀면
    LLM은 지켰다고 생각한 규칙에 걸려 탈락한다.

    331 2단계 — `[사실]` 블록을 없앤 뒤로 목록이 `[대상 대여소]`·`[후보]` 둘이다. 문장은
    압축하지 않는다(3단계 몫)."""
    return (
        "당신은 따릉이 재고 고갈 재안내 에이전트다. 아래 [대상 대여소]·[후보] 목록만 "
        "보고 후보 중 하나를 골라 정확히 이 JSON 형식으로만 답하라: "
        '{"chosen_index": <정수>, "reason": <문자열>}. '
        "chosen_index는 [후보] 목록의 번호 그대로여야 한다. "
        "reason에는 대여소 이름·숫자를 새로 만들지 말고 [대상 대여소]·[후보]에 실제로 "
        f"나온 값만 인용해 한국어 {max_sentences}문장 이내, {max_chars}자 이내로 써라."
    )


def _build_user_prompt(ctx: AgentContext) -> str:
    """대상 사실·`describe_candidate()` 결과를 그대로 문장으로 옮긴다.

    두 전략이 같은 입력을 보게 하는 `AgentContext`(`context.py` 모듈 docstring)를 그대로
    옮기는 자리라, 여기서 값을 가공하지 않는다 — 없는 값을 계산해 넣으면 `AgentStrategy`와
    `RuleStrategy`가 보는 "사실"이 달라진다.

    331 2단계 — `decision.facts`를 `- key: value`로 그대로 나열하던 `[사실]` 블록을 없앴다.
    `[대상 대여소]`(`_target_facts_lines`)가 이미 `facts`와 같은 값을 한국어 문장으로 보여주고
    있었고(`source`·`p_full`만 흡수해 보강했다), 두 블록이 같은 숫자를 중복해 보여줬을 뿐이다
    (`validation/TIME/reroute-baseline-check/RESULTS.md` real 절 토큰 분해). `[대상 대여소]`·
    `[후보]` 둘만 남는다.
    """
    lines = ["[대상 대여소]"]
    lines.extend(_target_facts_lines(ctx))
    lines.append("")
    lines.append("[후보]")
    for i in range(len(ctx.usable_candidates)):
        lines.append(describe_candidate(ctx, i))
    return "\n".join(lines)


_NUMBER_RE = re.compile(r"-?\d+(?:\.\d+)?")


def _numbers_in(text: str) -> set[float]:
    """문자열에 나오는 정수·소수를 전부 뽑는다. 부호·소수점 형식 차이를 흡수하려고 float로
    정규화한다 — `"6"`과 `"6.0"`이 같은 숫자로 비교돼야 한다."""
    return {float(m) for m in _NUMBER_RE.findall(text)}


def _allowed_numbers(ctx: AgentContext) -> set[float]:
    """`reason`이 지어내지 않았는지 검사할 숫자 허용집합.

    프롬프트에 실제로 보여준 대상 사실 줄(`_target_facts_lines`) + 후보 요약
    (`describe_candidate`)에 나온 숫자를 모은다 — 전부 LLM이 프롬프트에서 **실제로 본** 숫자라
    안전한 허용집합이다.

    331 2단계 이전에는 `decision.facts`의 수치 값을 여기 더 더했다 — 그때는 `[사실]` 블록이
    그 값을 그대로(반올림 없이) 보여줬기 때문이다. 그 블록을 없앤 지금은 `facts`를 직접 보지
    않는다 — 프롬프트에 안 보여준 raw 정밀도 숫자까지 허용하면 "LLM이 실제로 본 숫자"라는
    이 함수의 전제가 깨진다. `_target_facts_lines`가 `facts`의 모든 값을 이미 문장으로
    옮기므로(같은 파일의 그 함수 docstring), 허용집합이 줄지는 않는다.

    `p_empty`·`p_full`은 프롬프트에 **퍼센트로 보여준다**(예: "62%") — 하지만 LLM이 원값
    (0.62)을 그대로 인용할 수도 있어 텍스트에서 뽑은 숫자만으로는 부족하다. 그래서 대상·후보
    각각의 원본 값도 직접 허용집합에 더한다(퍼센트로 보여준 값과 원값을 **둘 다** 허용). 대상의
    `p_full`은 `_target_facts_lines`에만 있고 후보 요약에는 없어 대상 것만 더한다.
    """
    numbers: set[float] = set()

    for line in _target_facts_lines(ctx):
        numbers |= _numbers_in(line)
    if ctx.target_reading.p_empty is not None:
        numbers.add(float(ctx.target_reading.p_empty))
    if ctx.target_reading.p_full is not None:
        numbers.add(float(ctx.target_reading.p_full))

    for i in range(len(ctx.usable_candidates)):
        numbers |= _numbers_in(describe_candidate(ctx, i))
        reading = ctx.usable_candidates[i].reading
        if reading is not None and reading.p_empty is not None:
            numbers.add(float(reading.p_empty))

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
    **하나라도 탈락하면 `fallback`의 결과를 그대로 돌려준다**(`recommended_by`도 `fallback`이
    정한 값 그대로, 보통 `RuleStrategy`라 `RECOMMENDED_BY_ALGORITHM`). 이 청크가 끝나도 서비스
    동작이 나빠질 수 없다는 계획 전제가 여기서 지켜진다.
    """

    def __init__(
        self,
        client: LlmClient,
        fallback: RerouteStrategy,
        *,
        budget: LlmBudget | None = None,
        max_sentences: int = 2,
        max_chars: int = 120,
    ) -> None:
        self.client = client
        self.fallback = fallback
        self.budget = budget if budget is not None else LlmBudget()
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

        # 후보가 하나뿐이면 고를 게 없다 — LLM을 부르는 것 자체가 낭비이고, 탈락으로 세면
        # 204 집계에 "판단을 못 했다"는 잘못된 신호가 섞인다(판단할 필요가 없었을 뿐이다).
        if len(ctx.usable_candidates) == 1:
            return self.fallback.decide(ctx)

        budget_error = self.budget.check()
        if budget_error is not None:
            return self._reject(RejectReason.BUDGET_EXCEEDED, ctx)

        system = _system_prompt(self.max_sentences, self.max_chars)
        outcome = self.client.complete(system=system, user=_build_user_prompt(ctx))
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

        if not _numbers_in(reason) <= _allowed_numbers(ctx):
            return self._reject(RejectReason.UNKNOWN_NUMBER, ctx)

        chosen_name = candidates[chosen_index].candidate.station.name
        other_names = {
            c.candidate.station.name
            for i, c in enumerate(candidates)
            if i != chosen_index and c.candidate.station.name
        }
        if any(name in reason for name in other_names):
            return self._reject(RejectReason.WRONG_CANDIDATE_NAME, ctx)

        if chosen_name and chosen_name not in reason:
            return self._reject(RejectReason.MISSING_CHOSEN_NAME, ctx)

        if _sentence_count(reason) > self.max_sentences or len(reason) > self.max_chars:
            return self._reject(RejectReason.TOO_LONG, ctx)

        return RerouteProposal(
            candidate_index=chosen_index,
            reason=reason,
            recommended_by=RECOMMENDED_BY_AGENT,
            score=None,
        )

    def _reject(self, reason: RejectReason, ctx: AgentContext) -> RerouteProposal | None:
        self.rejections[reason] += 1
        return self.fallback.decide(ctx)


__all__ = [
    "RECOMMENDED_BY_AGENT",
    "RECOMMENDED_BY_ALGORITHM",
    "AgentStrategy",
    "RejectReason",
    "RerouteProposal",
    "RerouteStrategy",
    "RuleStrategy",
    "ScoreWeights",
    "build_reason",
    "describe_candidate",
]
