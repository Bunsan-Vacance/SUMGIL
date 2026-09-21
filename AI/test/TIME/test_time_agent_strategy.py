"""`AgentStrategy` 선택·환각 검사·규칙 폴백 검증(S15P21A104-203-A).

가짜 `LlmClient`(정해진 문자열만 돌려주는 객체)를 주입해 네트워크 없이 돈다. 지키려는 것은
두 가지다.

1. **하나라도 탈락하면 서비스가 나빠지지 않는다.** 탈락 시 반환값이 `RuleStrategy().decide(ctx)`
   와 값으로(dataclass 비교) 동일해야 한다 — 실패해도 규칙 기준선과 똑같이 동작한다는 뜻이다.
2. **탈락 사유가 정확히 집계된다.** `rejections` 카운터가 204 평가 하네스의 입력이다.

픽스처는 `test_time_strategy.py`의 `route`·`candidate`·`fired_ctx`를 그대로 가져다 쓴다 — 두
전략이 같은 `AgentContext`를 보게 하는 것이 203 설계의 전제이므로, 픽스처를 따로 만들면 그
전제를 테스트가 스스로 어기게 된다.
"""

from __future__ import annotations

from test_time_strategy import candidate, fired_ctx, route

from app.TIME.llm import LlmError, LlmErrorCode, LlmResult
from app.TIME.llm_budget import LlmBudget
from app.TIME.strategy import (
    SOURCE_AGENT,
    AgentStrategy,
    RejectReason,
    RuleStrategy,
    ScoreWeights,
    describe_candidate,
)

MODEL = "test-model"

# 기본 facts에는 "강남"이 worst_station_name으로 들어 있어(test_time_strategy.fired_ctx 기본값)
# 후보 이름과 겹칠 수 있다 — 그 우연한 겹침이 WRONG_CANDIDATE_NAME/MISSING_CHOSEN_NAME 판정을
# 흐리지 않도록 여기서는 facts를 직접 지정해 후보 이름과 분리한다.
FACTS = {
    "worst_station_name": "역삼",
    "worst_eta_minutes": 11,
    "worst_grade_from": 1,
    "worst_grade_to": 2,
    "calibration_fallback_used": False,
    "is_prediction": True,
    # p_empty·predicted_stock·transfer_ratio는 소수 값이다 — `_sentence_count`가 숫자 안의
    # 마침표를 문장 끝으로 잘못 세는 회귀를 막는 테스트(아래 "소수" 절)에서만 쓴다.
    "p_empty": 0.62,
    "predicted_stock": 1.5,
    "transfer_ratio": 1.2,
}


def _ctx():
    """후보 두 개 — 0번 교대(환승 1회·2등급), 1번 사당(환승 0회·등급 정보 없음)."""
    jodae = candidate("교대", seq=3, eta=6, routes=[route(minutes=18.0, transfers=1, grades=(2,))])
    sadang = candidate("사당", seq=4, eta=9, routes=[route(minutes=30.0)])
    return fired_ctx(jodae, sadang, facts=FACTS)


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
    return AgentStrategy(_FakeLlmClient(outcome), RuleStrategy(), **kwargs)


# ── 정상 선택 ──


def test_정상_선택은_AGENT를_source로_쓴다() -> None:
    ctx = _ctx()
    reason = "교대에서 내려 갈아타면 6분 후 도착하며 잔여 18분입니다."
    strategy = _strategy(_llm_result(f'{{"chosen_index": 0, "reason": "{reason}"}}'))

    proposal = strategy.decide(ctx)

    assert proposal is not None
    assert proposal.candidate_index == 0
    assert proposal.reason == reason
    assert proposal.source == SOURCE_AGENT
    assert proposal.score is None
    assert proposal.route is ctx.usable_candidates[0].routes[0]
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


# ── 탈락 → 폴백과 동일 ──


def test_LLM_오류면_폴백과_동일하고_LLM_ERROR가_늘어난다() -> None:
    ctx = _ctx()
    error = LlmError(code=LlmErrorCode.TIMEOUT, detail="응답 없음", retryable=True)
    strategy = _strategy(error)

    result = strategy.decide(ctx)

    assert result == RuleStrategy().decide(ctx)
    assert strategy.rejections[RejectReason.LLM_ERROR] == 1
    assert strategy.last_usage is None  # 실패 호출은 사용량을 갱신하지 않는다


def test_예산_초과면_LLM을_부르지_않고_폴백과_동일하다() -> None:
    ctx = _ctx()
    client = _FakeLlmClient(_llm_result('{"chosen_index": 0, "reason": "교대"}'))
    strategy = AgentStrategy(client, RuleStrategy(), budget=LlmBudget(max_calls=0))

    result = strategy.decide(ctx)

    assert result == RuleStrategy().decide(ctx)
    assert strategy.rejections[RejectReason.BUDGET_EXCEEDED] == 1
    assert client.calls == []  # 예산 확인이 먼저라 게이트웨이를 부르지도 않는다


def test_JSON이_깨지면_BAD_JSON이고_폴백과_동일하다() -> None:
    ctx = _ctx()
    strategy = _strategy(_llm_result("이건 JSON이 아니다"))

    result = strategy.decide(ctx)

    assert result == RuleStrategy().decide(ctx)
    assert strategy.rejections[RejectReason.BAD_JSON] == 1
    assert strategy.budget.calls == 1  # 게이트웨이 호출 자체는 성공했으니 예산은 깎인다


def test_필드가_없어도_BAD_JSON이다() -> None:
    ctx = _ctx()
    strategy = _strategy(_llm_result('{"reason": "이유만 있음"}'))

    result = strategy.decide(ctx)

    assert result == RuleStrategy().decide(ctx)
    assert strategy.rejections[RejectReason.BAD_JSON] == 1


def test_범위_밖_인덱스면_INDEX_OUT_OF_RANGE고_폴백과_동일하다() -> None:
    ctx = _ctx()
    strategy = _strategy(_llm_result('{"chosen_index": 5, "reason": "교대에서 내리세요."}'))

    result = strategy.decide(ctx)

    assert result == RuleStrategy().decide(ctx)
    assert strategy.rejections[RejectReason.INDEX_OUT_OF_RANGE] == 1


def test_음수_인덱스도_INDEX_OUT_OF_RANGE다() -> None:
    ctx = _ctx()
    strategy = _strategy(_llm_result('{"chosen_index": -1, "reason": "교대에서 내리세요."}'))

    result = strategy.decide(ctx)

    assert result == RuleStrategy().decide(ctx)
    assert strategy.rejections[RejectReason.INDEX_OUT_OF_RANGE] == 1


def test_지어낸_숫자면_UNKNOWN_NUMBER고_폴백과_동일하다() -> None:
    ctx = _ctx()
    # 15는 facts에도, 후보 요약(교대: 0·6·18·1·2 / 사당: 1·9·30·0) 어디에도 없다.
    reason = "교대에서 내리면 15분 뒤 도착합니다."
    strategy = _strategy(_llm_result(f'{{"chosen_index": 0, "reason": "{reason}"}}'))

    result = strategy.decide(ctx)

    assert result == RuleStrategy().decide(ctx)
    assert strategy.rejections[RejectReason.UNKNOWN_NUMBER] == 1


def test_facts_숫자는_허용된다() -> None:
    # worst_eta_minutes=11이 facts에 있으므로 후보 요약에 없어도 UNKNOWN_NUMBER가 아니어야 한다.
    ctx = _ctx()
    reason = "교대에서 내려 갈아타세요. 11분 뒤 역삼이 혼잡해집니다."
    strategy = _strategy(_llm_result(f'{{"chosen_index": 0, "reason": "{reason}"}}'))

    result = strategy.decide(ctx)

    assert result is not None
    assert result.source == SOURCE_AGENT  # 탈락하지 않고 그대로 채택됐다


def test_다른_후보_이름이면_WRONG_CANDIDATE_NAME이고_폴백과_동일하다() -> None:
    ctx = _ctx()
    reason = "교대와 사당 중에서 고민하다 정했습니다."
    strategy = _strategy(_llm_result(f'{{"chosen_index": 0, "reason": "{reason}"}}'))

    result = strategy.decide(ctx)

    assert result == RuleStrategy().decide(ctx)
    assert strategy.rejections[RejectReason.WRONG_CANDIDATE_NAME] == 1


def test_선택_후보_이름이_없으면_MISSING_CHOSEN_NAME이고_폴백과_동일하다() -> None:
    ctx = _ctx()
    reason = "다음 역에서 내려 갈아타세요."
    strategy = _strategy(_llm_result(f'{{"chosen_index": 0, "reason": "{reason}"}}'))

    result = strategy.decide(ctx)

    assert result == RuleStrategy().decide(ctx)
    assert strategy.rejections[RejectReason.MISSING_CHOSEN_NAME] == 1


def test_문장수_초과면_TOO_LONG이고_폴백과_동일하다() -> None:
    ctx = _ctx()
    reason = "교대에서 내리세요. 그리고 다음 열차를 타세요. 그 다음 환승하세요."
    strategy = _strategy(_llm_result(f'{{"chosen_index": 0, "reason": "{reason}"}}'))

    result = strategy.decide(ctx)

    assert result == RuleStrategy().decide(ctx)
    assert strategy.rejections[RejectReason.TOO_LONG] == 1


def test_글자수_초과면_TOO_LONG이고_폴백과_동일하다() -> None:
    ctx = _ctx()
    filler = "교대에서 내려 갈아타시는 것을 추천합니다 " * 8
    reason = filler.strip() + "."  # 한 문장이지만 120자를 넘긴다
    assert len(reason) > 120
    strategy = _strategy(_llm_result(f'{{"chosen_index": 0, "reason": "{reason}"}}'))

    result = strategy.decide(ctx)

    assert result == RuleStrategy().decide(ctx)
    assert strategy.rejections[RejectReason.TOO_LONG] == 1


def test_상한을_바꾸면_그만큼_허용된다() -> None:
    ctx = _ctx()
    reason = "교대에서 내리세요. 잔여 18분입니다. 환승 1회입니다."  # 3문장
    strategy = _strategy(
        _llm_result(f'{{"chosen_index": 0, "reason": "{reason}"}}'), max_sentences=3
    )

    result = strategy.decide(ctx)

    assert result is not None
    assert result.source == SOURCE_AGENT


# ── describe_candidate ──


def test_describe_candidate는_이름_ETA_소요_환승_등급을_담는다() -> None:
    ctx = _ctx()

    text = describe_candidate(ctx, 0)

    assert text.startswith("0. 교대")
    assert "6분" in text
    assert "18분" in text
    assert "환승 1회" in text
    assert "2등급" in text


def test_describe_candidate는_없는_값의_자리를_통째로_뺀다() -> None:
    ctx = _ctx()

    text = describe_candidate(ctx, 1)  # 사당 — 등급 정보 없음

    assert "1. 사당" in text
    assert "등급" not in text


# ── 소수(`.`) — 문장 구분자와 헷갈리지 않는다 ──
#
# `re.split(r"[.!?]+", ...)`였던 옛 구현은 "0.62"의 마침표도 문장 끝으로 세어, 정상 한 문장이
# TOO_LONG으로 잘못 탈락했다(BIKE p_empty 같은 0~1 소수가 reason에 들어가면 재현된다). 숫자
# 사이의 마침표는 구분자로 보지 않는 정규식으로 고친 뒤에도 계속 지켜져야 하는 성질이다.


def test_소수_하나가_들어간_한_문장은_1문장으로_센다() -> None:
    ctx = _ctx()
    # 소수 두 개(0.62·1.5)가 낀 "한" 문장 — 옛 구현이면 마침표 3개(각 소수 안 1개씩 + 문장
    # 끝 1개)로 쪼개져 4문장으로 세어지고 기본 max_sentences=2를 넘어 TOO_LONG이 됐을 것이다.
    reason = "교대에서 내려 빈 확률 0.62, 예측 재고 1.5대로 도착합니다."
    strategy = _strategy(_llm_result(f'{{"chosen_index": 0, "reason": "{reason}"}}'))

    result = strategy.decide(ctx)

    assert result is not None
    assert result.source == SOURCE_AGENT  # 탈락하지 않고 그대로 채택됐다
    assert not strategy.rejections


def test_소수가_들어간_두_문장은_max_sentences_2에서_통과한다() -> None:
    ctx = _ctx()
    # 진짜 문장은 두 개(각각 소수 하나씩 포함)다. 옛 구현이면 마침표 4개로 쪼개져 4문장으로
    # 세어지고 기본 max_sentences=2를 넘어 TOO_LONG이 됐을 것이다.
    reason = "교대에서 내려 빈 확률 0.62로 도착합니다. 잔여 좌석 1.2배 여유가 있습니다."
    strategy = _strategy(_llm_result(f'{{"chosen_index": 0, "reason": "{reason}"}}'))

    result = strategy.decide(ctx)

    assert result is not None
    assert result.source == SOURCE_AGENT
    assert not strategy.rejections


# ── weights — fallback과 같은 경로를 고른다 ──


def test_weights를_안_주면_fallback의_가중치를_물려받는다() -> None:
    heavy = ScoreWeights(transfer_penalty_min=100.0)
    strategy = AgentStrategy(_FakeLlmClient(_llm_result("{}")), RuleStrategy(heavy))

    assert strategy.weights == heavy


def test_weights가_없는_fallback이면_기본값으로_떨어진다() -> None:
    class _NoWeightsFallback:
        def decide(self, ctx):  # pragma: no cover - 이 테스트에서는 불릴 일이 없다
            return None

    strategy = AgentStrategy(_FakeLlmClient(_llm_result("{}")), _NoWeightsFallback())

    assert strategy.weights == ScoreWeights()


def test_fallback_가중치를_물려받아_같은_경로를_고른다() -> None:
    """`RuleStrategy`가 극단적인 환승 페널티로 "환승 없지만 느린" 경로를 고르면,
    `AgentStrategy`도(LLM이 채택되더라도) 같은 경로를 골라야 한다 — 프롬프트에 보여준 경로와
    최종 채택 경로가 fallback과 어긋나면 `describe_candidate`/`decide` docstring의 약속이
    깨진다."""
    slow_no_transfer = route(minutes=15.0, transfers=0)
    fast_one_transfer = route(minutes=10.0, transfers=1)
    only = candidate("교대", seq=3, eta=6, routes=[fast_one_transfer, slow_no_transfer])
    ctx = fired_ctx(only, facts=FACTS)

    heavy_transfer_penalty = ScoreWeights(transfer_penalty_min=100.0)
    fallback = RuleStrategy(heavy_transfer_penalty)
    expected = fallback.decide(ctx)
    assert expected is not None
    assert expected.route is slow_no_transfer  # 기본 가중치였다면 fast_one_transfer가 이긴다

    reason = "교대에서 내려 갈아타세요."
    strategy = AgentStrategy(
        _FakeLlmClient(_llm_result(f'{{"chosen_index": 0, "reason": "{reason}"}}')),
        fallback,
    )
    assert strategy.weights == heavy_transfer_penalty

    proposal = strategy.decide(ctx)

    assert proposal is not None
    assert proposal.source == SOURCE_AGENT  # 탈락하지 않고 LLM 선택이 채택됐다
    assert proposal.route is expected.route
