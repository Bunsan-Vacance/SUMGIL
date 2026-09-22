"""`AgentStrategy` 선택·환각 검사·규칙 폴백 검증(S15P21A104-203-A/302).

가짜 `LlmClient`(정해진 문자열만 돌려주는 객체)를 주입해 네트워크 없이 돈다. 지키려는 것은
셋이다.

1. **하나라도 탈락하면 서비스가 나빠지지 않는다.** 탈락 시 반환값이 `RuleStrategy(WEIGHTS)
   .decide(ctx)`와 값으로(dataclass 비교) 동일해야 한다 — 실패해도 규칙 기준선과 똑같이
   동작한다는 뜻이다.
2. **탈락 사유가 정확히 집계된다.** `rejections` 카운터가 204 평가 하네스의 입력이다.
3. **후보가 하나뿐이면 LLM을 부르지 않는다.** 고를 게 없으니 판단이 필요 없고, 탈락으로 세면
   204 집계에 "판단을 못 했다"는 잘못된 신호가 섞인다.

픽스처는 `test_time_strategy.py`의 `candidate`·`fired_ctx`를 그대로 가져다 쓴다 — 두 전략이
같은 `AgentContext`를 보게 하는 것이 203 설계의 전제이므로, 픽스처를 따로 만들면 그 전제를
테스트가 스스로 어기게 된다.
"""

from __future__ import annotations

from test_time_strategy import WEIGHTS, candidate, fired_ctx

from app.TIME.llm import LlmError, LlmErrorCode, LlmResult
from app.TIME.llm_budget import LlmBudget
from app.TIME.strategy import (
    RECOMMENDED_BY_AGENT,
    AgentStrategy,
    RejectReason,
    RuleStrategy,
)

MODEL = "test-model"


def _ctx():
    """후보 두 개 — 0번 교대(가까움·재고 여유), 1번 사당(멀고 p_empty 없음).

    대상(역삼)의 `p_empty=0.62`·`predicted_stock=1.5`는 소수라 `_sentence_count`가 숫자 안의
    마침표를 문장 끝으로 잘못 세는 회귀를 막는 테스트(아래 "소수" 절)에서 쓴다.
    """
    jodae = candidate("교대", distance_m=80.0, p_empty=0.2, current_stock=4, predicted_stock=3.0)
    sadang = candidate("사당", distance_m=400.0, p_empty=None, predicted_stock=2.5, current_stock=2)
    return fired_ctx(
        jodae,
        sadang,
        target_name="역삼",
        target_reading_kwargs={"p_empty": 0.62, "predicted_stock": 1.5, "current_stock": 0},
    )


class _FakeLlmClient:
    """정해진 값을 그대로 돌려주는 가짜 게이트웨이. 인자를 기록만 하고 스스로 판단하지 않는다."""

    def __init__(self, outcome: LlmResult | LlmError) -> None:
        self.outcome = outcome
        self.calls: list[tuple[str, str]] = []

    def complete(self, system: str, user: str, *, json_schema=None):
        self.calls.append((system, user))
        return self.outcome


def _llm_result(text: str) -> LlmResult:
    return LlmResult(text=text, input_tokens=100, output_tokens=20, latency_ms=5.0, model=MODEL)


def _strategy(outcome: LlmResult | LlmError, **kwargs) -> AgentStrategy:
    return AgentStrategy(_FakeLlmClient(outcome), RuleStrategy(WEIGHTS), **kwargs)


# ── 정상 선택 ──


def test_정상_선택은_AGENT를_recommended_by로_쓴다() -> None:
    ctx = _ctx()
    reason = "교대에서 자전거를 빌리는 건 어떨까요. 80m 거리입니다."
    strategy = _strategy(_llm_result(f'{{"chosen_index": 0, "reason": "{reason}"}}'))

    proposal = strategy.decide(ctx)

    assert proposal is not None
    assert proposal.candidate_index == 0
    assert proposal.reason == reason
    assert proposal.recommended_by == RECOMMENDED_BY_AGENT
    assert proposal.score is None
    assert not strategy.rejections  # 탈락이 하나도 없어야 한다
    assert strategy.last_usage is not None
    assert strategy.last_usage.model == MODEL
    assert strategy.budget.calls == 1


def test_대안이_없으면_LLM을_부르지_않고_None이다() -> None:
    empty = fired_ctx()  # 후보 없음
    client = _FakeLlmClient(_llm_result("{}"))
    strategy = AgentStrategy(client, RuleStrategy())

    assert strategy.decide(empty) is None
    assert client.calls == []
    assert not strategy.rejections


def test_후보가_하나뿐이면_LLM을_부르지_않고_폴백을_쓴다() -> None:
    only = candidate("교대", distance_m=80.0, p_empty=0.8)
    ctx = fired_ctx(only)
    client = _FakeLlmClient(_llm_result('{"chosen_index": 0, "reason": "교대"}'))
    fallback = RuleStrategy(WEIGHTS)
    strategy = AgentStrategy(client, fallback)

    result = strategy.decide(ctx)

    assert result == fallback.decide(ctx)
    assert client.calls == []  # LLM을 부르지 않았다
    assert not strategy.rejections  # 판단을 못 한 게 아니라 판단할 필요가 없었다


# ── 탈락 → 폴백과 동일 ──


def test_LLM_오류면_폴백과_동일하고_LLM_ERROR가_늘어난다() -> None:
    ctx = _ctx()
    error = LlmError(code=LlmErrorCode.TIMEOUT, detail="응답 없음", retryable=True)
    strategy = _strategy(error)

    result = strategy.decide(ctx)

    assert result == RuleStrategy(WEIGHTS).decide(ctx)
    assert strategy.rejections[RejectReason.LLM_ERROR] == 1
    assert strategy.last_usage is None  # 실패 호출은 사용량을 갱신하지 않는다


def test_예산_초과면_LLM을_부르지_않고_폴백과_동일하다() -> None:
    ctx = _ctx()
    client = _FakeLlmClient(_llm_result('{"chosen_index": 0, "reason": "교대"}'))
    strategy = AgentStrategy(client, RuleStrategy(WEIGHTS), budget=LlmBudget(max_calls=0))

    result = strategy.decide(ctx)

    assert result == RuleStrategy(WEIGHTS).decide(ctx)
    assert strategy.rejections[RejectReason.BUDGET_EXCEEDED] == 1
    assert client.calls == []  # 예산 확인이 먼저라 게이트웨이를 부르지도 않는다


def test_JSON이_깨지면_BAD_JSON이고_폴백과_동일하다() -> None:
    ctx = _ctx()
    strategy = _strategy(_llm_result("이건 JSON이 아니다"))

    result = strategy.decide(ctx)

    assert result == RuleStrategy(WEIGHTS).decide(ctx)
    assert strategy.rejections[RejectReason.BAD_JSON] == 1
    assert strategy.budget.calls == 1  # 게이트웨이 호출 자체는 성공했으니 예산은 깎인다


def test_필드가_없어도_BAD_JSON이다() -> None:
    ctx = _ctx()
    strategy = _strategy(_llm_result('{"reason": "이유만 있음"}'))

    result = strategy.decide(ctx)

    assert result == RuleStrategy(WEIGHTS).decide(ctx)
    assert strategy.rejections[RejectReason.BAD_JSON] == 1


def test_범위_밖_인덱스면_INDEX_OUT_OF_RANGE고_폴백과_동일하다() -> None:
    ctx = _ctx()
    strategy = _strategy(_llm_result('{"chosen_index": 5, "reason": "교대에서 빌리세요."}'))

    result = strategy.decide(ctx)

    assert result == RuleStrategy(WEIGHTS).decide(ctx)
    assert strategy.rejections[RejectReason.INDEX_OUT_OF_RANGE] == 1


def test_음수_인덱스도_INDEX_OUT_OF_RANGE다() -> None:
    ctx = _ctx()
    strategy = _strategy(_llm_result('{"chosen_index": -1, "reason": "교대에서 빌리세요."}'))

    result = strategy.decide(ctx)

    assert result == RuleStrategy(WEIGHTS).decide(ctx)
    assert strategy.rejections[RejectReason.INDEX_OUT_OF_RANGE] == 1


def test_지어낸_숫자면_UNKNOWN_NUMBER고_폴백과_동일하다() -> None:
    ctx = _ctx()
    # 999는 facts에도, 후보 요약(교대: 0·80·4·3.0·20 / 사당: 1·400·2·2.5) 어디에도 없다.
    reason = "교대에서 내리면 999m 거리입니다."
    strategy = _strategy(_llm_result(f'{{"chosen_index": 0, "reason": "{reason}"}}'))

    result = strategy.decide(ctx)

    assert result == RuleStrategy(WEIGHTS).decide(ctx)
    assert strategy.rejections[RejectReason.UNKNOWN_NUMBER] == 1


def test_facts_숫자는_허용된다() -> None:
    # eta_minutes=11이 facts에 있으므로 후보 요약에 없어도 UNKNOWN_NUMBER가 아니어야 한다.
    ctx = _ctx()
    reason = "교대에서 자전거를 빌리세요. 11분 뒤 역삼 대여소가 빕니다."
    strategy = _strategy(_llm_result(f'{{"chosen_index": 0, "reason": "{reason}"}}'))

    result = strategy.decide(ctx)

    assert result is not None
    assert result.recommended_by == RECOMMENDED_BY_AGENT  # 탈락하지 않고 채택됐다


def test_다른_후보_이름이면_WRONG_CANDIDATE_NAME이고_폴백과_동일하다() -> None:
    ctx = _ctx()
    reason = "교대와 사당 중에서 고민하다 정했습니다."
    strategy = _strategy(_llm_result(f'{{"chosen_index": 0, "reason": "{reason}"}}'))

    result = strategy.decide(ctx)

    assert result == RuleStrategy(WEIGHTS).decide(ctx)
    assert strategy.rejections[RejectReason.WRONG_CANDIDATE_NAME] == 1


def test_선택_후보_이름이_없으면_MISSING_CHOSEN_NAME이고_폴백과_동일하다() -> None:
    ctx = _ctx()
    reason = "가까운 대여소로 바꿔보세요."
    strategy = _strategy(_llm_result(f'{{"chosen_index": 0, "reason": "{reason}"}}'))

    result = strategy.decide(ctx)

    assert result == RuleStrategy(WEIGHTS).decide(ctx)
    assert strategy.rejections[RejectReason.MISSING_CHOSEN_NAME] == 1


def test_문장수_초과면_TOO_LONG이고_폴백과_동일하다() -> None:
    ctx = _ctx()
    reason = "교대로 가세요. 가까운 곳입니다. 자전거가 있습니다."
    strategy = _strategy(_llm_result(f'{{"chosen_index": 0, "reason": "{reason}"}}'))

    result = strategy.decide(ctx)

    assert result == RuleStrategy(WEIGHTS).decide(ctx)
    assert strategy.rejections[RejectReason.TOO_LONG] == 1


def test_글자수_초과면_TOO_LONG이고_폴백과_동일하다() -> None:
    ctx = _ctx()
    filler = "교대에서 자전거를 빌리시는 것을 추천합니다 " * 8
    reason = filler.strip() + "."  # 한 문장이지만 120자를 넘긴다
    assert len(reason) > 120
    strategy = _strategy(_llm_result(f'{{"chosen_index": 0, "reason": "{reason}"}}'))

    result = strategy.decide(ctx)

    assert result == RuleStrategy(WEIGHTS).decide(ctx)
    assert strategy.rejections[RejectReason.TOO_LONG] == 1


def test_상한을_바꾸면_그만큼_허용된다() -> None:
    ctx = _ctx()
    reason = "교대로 가세요. 80m 거리입니다. 재고가 있습니다."  # 3문장
    strategy = _strategy(
        _llm_result(f'{{"chosen_index": 0, "reason": "{reason}"}}'), max_sentences=3
    )

    result = strategy.decide(ctx)

    assert result is not None
    assert result.recommended_by == RECOMMENDED_BY_AGENT


# ── 소수(`.`) — 문장 구분자와 헷갈리지 않는다 ──
#
# `re.split(r"[.!?]+", ...)`였던 옛 구현은 "0.62"의 마침표도 문장 끝으로 세어, 정상 한 문장이
# TOO_LONG으로 잘못 탈락했다(BIKE p_empty 같은 0~1 소수가 reason에 들어가면 재현된다). 숫자
# 사이의 마침표는 구분자로 보지 않는 정규식으로 고친 뒤에도 계속 지켜져야 하는 성질이다.


def test_소수_하나가_들어간_한_문장은_1문장으로_센다() -> None:
    ctx = _ctx()
    # 소수 두 개(0.62·1.5)가 낀 "한" 문장 — 옛 구현이면 마침표 3개(각 소수 안 1개씩 + 문장
    # 끝 1개)로 쪼개져 4문장으로 세어지고 기본 max_sentences=2를 넘어 TOO_LONG이 됐을 것이다.
    # (역삼의 p_empty 0.62·predicted_stock 1.5는 facts에 있어 허용된다 — 선택한 후보 이름
    # "교대"는 MISSING_CHOSEN_NAME을 피하려고 같이 넣는다.)
    reason = "교대로 바꾸세요, 원래 확률 0.62·재고 1.5대였습니다."
    strategy = _strategy(_llm_result(f'{{"chosen_index": 0, "reason": "{reason}"}}'))

    result = strategy.decide(ctx)

    assert result is not None
    assert result.recommended_by == RECOMMENDED_BY_AGENT
    assert not strategy.rejections


def test_소수가_들어간_두_문장은_max_sentences_2에서_통과한다() -> None:
    ctx = _ctx()
    # 진짜 문장은 두 개(각각 소수 하나씩 포함)다. 옛 구현이면 마침표 4개로 쪼개져 4문장으로
    # 세어지고 기본 max_sentences=2를 넘어 TOO_LONG이 됐을 것이다.
    reason = "역삼은 비어 있을 확률 0.62입니다. 교대는 재고 3.0대로 여유가 있습니다."
    strategy = _strategy(_llm_result(f'{{"chosen_index": 0, "reason": "{reason}"}}'))

    result = strategy.decide(ctx)

    assert result is not None
    assert result.recommended_by == RECOMMENDED_BY_AGENT
    assert not strategy.rejections
