"""규칙 기준선 전략 검증(S15P21A104-203/302).

가중치(도보속도 80m/분·고갈페널티 10분)는 **잠정값**이라 "10분이 옳은가"를 검증하지 않는다.
대신 가중치가 무엇으로 바뀌든 지켜져야 하는 성질을 고정한다 — 점수 단조성, 동점 처리, 읽지
못한 값의 처리, 문장이 없는 숫자를 만들지 않는 것.

특히 마지막이 중요하다. 이 전략이 LLM보다 정직한 이유가 "자리에 넣을 값이 없으면 문장을 통째로
뺀다"인데, 그게 깨지면 기준선으로서의 의미가 없다.

`candidate`·`fired_ctx`는 `test_time_agent_strategy.py`가 그대로 가져다 쓴다 — 두 전략이 같은
`AgentContext`를 보게 하는 것이 203 설계의 전제이므로, 픽스처를 따로 만들면 그 전제를 테스트가
스스로 어기게 된다.
"""

from __future__ import annotations

import logging

import pytest

from app.TIME.context import AgentContext, CandidateContext, RentalCandidate
from app.TIME.llm import LlmError, LlmErrorCode, LlmResult
from app.TIME.station_index import RentalStation
from app.TIME.strategy import (
    DEFAULT_WALK_SPEED_M_PER_MIN,
    RECOMMENDED_BY_ALGORITHM,
    AgentStrategy,
    RuleStrategy,
    ScoreWeights,
    _allowed_numbers,
    _build_user_prompt,
    _numbers_in,
    _system_prompt,
    build_reason,
    describe_candidate,
)
from app.TIME.trigger import StockReading, TriggerResult

WEIGHTS = ScoreWeights(walk_speed_m_per_min=80.0, empty_penalty_min=10.0)


def station(
    rental_id: str = "S", *, name: str | None = "교대", lat: float = 37.5, lng: float = 127.0
) -> RentalStation:
    return RentalStation(
        rental_id=rental_id,
        name=name,
        lat=lat,
        lng=lng,
        rack_count=10,
        current_stock=5,
        updated_at=None,
    )


def reading(
    *,
    current_stock: int | None = 5,
    predicted_stock: float | None = 5.0,
    p_empty: float | None = 0.1,
    p_full: float | None = 0.0,
    source: str | None = "lightgbm",
    model_horizon_min: int | None = 10,
) -> StockReading:
    return StockReading(
        current_stock=current_stock,
        predicted_stock=predicted_stock,
        p_empty=p_empty,
        p_full=p_full,
        source=source,
        model_horizon_min=model_horizon_min,
    )


def candidate(
    name: str = "교대", *, rental_id: str | None = None, distance_m: float = 200.0, **reading_kwargs
) -> CandidateContext:
    rid = rental_id if rental_id is not None else name
    return CandidateContext(
        candidate=RentalCandidate(station=station(rid, name=name), distance_m=distance_m),
        reading=reading(**reading_kwargs),
    )


def fired_ctx(
    *candidates: CandidateContext,
    facts: dict | None = None,
    target_name: str | None = "역삼",
    eta_minutes: int = 11,
    target_reading_kwargs: dict | None = None,
) -> AgentContext:
    target = station("TARGET", name=target_name)
    t_reading = reading(**(target_reading_kwargs or {"p_empty": 0.9, "predicted_stock": 0.5}))
    default_facts = {
        "eta_minutes": eta_minutes,
        "current_stock": t_reading.current_stock,
        "predicted_stock": t_reading.predicted_stock,
        "p_empty": t_reading.p_empty,
        "p_full": t_reading.p_full,
        "source": t_reading.source,
        "model_horizon_min": t_reading.model_horizon_min,
    }
    decision = TriggerResult(
        fired=True, reason="p_empty", facts=facts if facts is not None else default_facts
    )
    return AgentContext(
        decision=decision,
        target=target,
        target_reading=t_reading,
        eta_minutes=eta_minutes,
        candidates=list(candidates),
    )


# ── 선택 ──


def test_점수가_가장_낮은_후보를_고른다():
    near = candidate("교대", distance_m=80.0, p_empty=0.1)  # 1.0 + 1.0 = 2.0
    far = candidate("강남", distance_m=800.0, p_empty=0.1)  # 10.0 + 1.0 = 11.0

    proposal = RuleStrategy(WEIGHTS).decide(fired_ctx(near, far))

    assert proposal is not None
    assert proposal.candidate_index == 0
    assert proposal.score == pytest.approx(2.0)
    assert proposal.recommended_by == RECOMMENDED_BY_ALGORITHM


def test_비어있을_확률이_높으면_가까워도_밀린다():
    risky = candidate("교대", distance_m=80.0, p_empty=0.9)  # 1.0 + 9.0 = 10.0
    safe = candidate("강남", distance_m=400.0, p_empty=0.0)  # 5.0 + 0.0 = 5.0

    proposal = RuleStrategy(WEIGHTS).decide(fired_ctx(risky, safe))

    assert proposal is not None
    assert proposal.candidate_index == 1


def test_점수가_같으면_거리가_가까운_쪽이_이긴다():
    a = candidate("교대", distance_m=80.0, p_empty=0.5)  # 1.0 + 5.0 = 6.0
    b = candidate("강남", distance_m=160.0, p_empty=0.4)  # 2.0 + 4.0 = 6.0

    proposal = RuleStrategy(WEIGHTS).decide(fired_ctx(a, b))

    assert proposal is not None
    assert proposal.score == pytest.approx(6.0)
    assert proposal.candidate_index == 0


def test_가중치를_바꾸면_선택이_바뀐다():
    risky = candidate("교대", distance_m=80.0, p_empty=0.9)
    safe = candidate("강남", distance_m=400.0, p_empty=0.0)
    ctx = fired_ctx(risky, safe)

    assert RuleStrategy(WEIGHTS).decide(ctx).candidate_index == 1
    lenient = ScoreWeights(walk_speed_m_per_min=80.0, empty_penalty_min=0.5)
    assert RuleStrategy(lenient).decide(ctx).candidate_index == 0


# ── p_empty 근사(proxy) ──


def test_p_empty가_None이고_예측재고가_1대_이하면_1로_근사한다():
    only = candidate("교대", distance_m=80.0, p_empty=None, predicted_stock=0.5)

    proposal = RuleStrategy(WEIGHTS).decide(fired_ctx(only))

    assert proposal is not None
    assert proposal.score == pytest.approx(80.0 / 80.0 + 1.0 * 10.0)


def test_p_empty가_None이고_예측재고가_1대_초과면_0으로_근사한다():
    only = candidate("교대", distance_m=80.0, p_empty=None, predicted_stock=5.0)

    proposal = RuleStrategy(WEIGHTS).decide(fired_ctx(only))

    assert proposal is not None
    assert proposal.score == pytest.approx(80.0 / 80.0)


def test_p_empty와_predicted_stock이_둘_다_없으면_점수를_못_낸다():
    unreadable = candidate("교대", distance_m=80.0, p_empty=None, predicted_stock=None)

    assert RuleStrategy(WEIGHTS).score(unreadable) is None


# ── 고를 게 없을 때 ──


def test_대안이_없으면_None이다():
    assert RuleStrategy(WEIGHTS).decide(fired_ctx()) is None


def test_조회_실패만_있으면_None이다():
    failed = CandidateContext(
        candidate=RentalCandidate(station=station("S1", name="교대"), distance_m=80.0),
        error={"error": "UPSTREAM_UNAVAILABLE", "detail": "BE 미기동", "retryable": True},
    )

    assert RuleStrategy(WEIGHTS).decide(fired_ctx(failed)) is None


def test_점수를_못_내는_후보만_있으면_None이다():
    unreadable = candidate("교대", distance_m=80.0, p_empty=None, predicted_stock=None)

    assert RuleStrategy(WEIGHTS).decide(fired_ctx(unreadable)) is None


# ── 안내 문장 — 없는 숫자를 만들지 않는다 ──


def test_문장에_대상과_대안이_담긴다():
    c = candidate("교대", distance_m=150.0)
    ctx = fired_ctx(
        c,
        target_name="역삼",
        target_reading_kwargs={"predicted_stock": 0.3, "p_empty": 0.9},
    )

    proposal = RuleStrategy(WEIGHTS).decide(ctx)

    assert proposal is not None
    reason = proposal.reason
    assert "역삼" in reason
    assert "교대" in reason
    assert "150m" in reason
    assert "0.3대" in reason


def test_예측재고가_없으면_괄호를_통째로_뺀다():
    c = candidate("교대", distance_m=150.0)
    ctx = fired_ctx(c, target_reading_kwargs={"predicted_stock": None, "p_empty": 0.9})

    reason = RuleStrategy(WEIGHTS).decide(ctx).reason

    assert "(" not in reason
    assert "역삼" in reason


def test_대상_이름이_없으면_이_대여소라고_쓴다():
    c = candidate("교대", distance_m=150.0)
    ctx = fired_ctx(
        c,
        target_name=None,
        target_reading_kwargs={"predicted_stock": 0.3, "p_empty": 0.9},
    )

    reason = RuleStrategy(WEIGHTS).decide(ctx).reason

    assert "이 대여소" in reason


def test_대안_이름이_없으면_이_대여소라고_쓴다():
    nameless = CandidateContext(
        candidate=RentalCandidate(station=station("S1", name=None), distance_m=150.0),
        reading=reading(p_empty=0.1, predicted_stock=5.0),
    )
    ctx = fired_ctx(nameless)

    reason = RuleStrategy(WEIGHTS).decide(ctx).reason

    assert "이 대여소로 바꾸시면" in reason


def test_build_reason을_직접_불러도_같은_문장이다():
    c = candidate("교대", distance_m=150.0)
    ctx = fired_ctx(c)

    proposal = RuleStrategy(WEIGHTS).decide(ctx)
    assert build_reason(ctx, ctx.usable_candidates[0]) == proposal.reason


# ── describe_candidate ──


def test_describe_candidate는_이름_거리_재고_확률을_담는다():
    c = candidate("교대", distance_m=133.0, current_stock=4, predicted_stock=2.3, p_empty=0.42)
    ctx = fired_ctx(c)

    text = describe_candidate(ctx, 0)

    assert text.startswith("0. 교대")
    assert "133m" in text
    assert "현재 4대" in text
    assert "2.3대" in text
    assert "42%" in text


def test_describe_candidate는_없는_값의_자리를_통째로_뺀다():
    c = candidate("교대", distance_m=133.0, current_stock=None, predicted_stock=None, p_empty=None)
    ctx = fired_ctx(c)

    text = describe_candidate(ctx, 0)

    assert "현재" not in text
    assert "예상" not in text
    assert "확률" not in text


# ── LLM 사용자 프롬프트 — 331 2단계: [사실] 블록 제거 ──
#
# `decision.facts`를 `- key: value`로 그대로 나열하던 [사실] 블록은 [대상 대여소] 블록
# (`_target_facts_lines`)과 값이 중복이었다(RESULTS.md real 절 토큰 분해). 블록을 없애도
# facts의 모든 항목이 [대상 대여소]에 남아 있는지, 환각 검사 허용 숫자가 줄지 않는지를 고정한다.


def test_프롬프트에_사실_블록이_없고_대상_블록이_facts_항목을_전부_담는다():
    c = candidate("교대", distance_m=150.0)
    ctx = fired_ctx(c, target_reading_kwargs={"predicted_stock": 1.5, "p_empty": 0.62})

    prompt = _build_user_prompt(ctx)

    assert "[사실]" not in prompt
    assert "[대상 대여소]" in prompt
    assert "[후보]" in prompt

    target_block = prompt.split("[후보]")[0]
    assert "도착까지" in target_block  # facts["eta_minutes"]
    assert "재고" in target_block  # facts["current_stock"]/["predicted_stock"]
    assert "확률" in target_block  # facts["p_empty"]/["p_full"]
    assert "horizon" in target_block  # facts["model_horizon_min"]
    assert "출처" in target_block  # facts["source"]


def test_사실_블록에_있던_숫자는_제거_후에도_허용된다():
    """제거한 [사실] 블록이 보여줬을 숫자(`decision.facts`를 `key: value`로 그대로 적은 것)가
    새 허용집합(`_allowed_numbers`)에서 빠지지 않는지 — 허용 숫자 집합이 줄지 않는다는 확인."""
    c = candidate("교대", distance_m=150.0)
    ctx = fired_ctx(c, target_reading_kwargs={"predicted_stock": 1.5, "p_empty": 0.62})

    old_block_numbers: set[float] = set()
    for key, value in ctx.decision.facts.items():
        old_block_numbers |= _numbers_in(f"- {key}: {value}")

    assert old_block_numbers  # 이 픽스처는 실제로 숫자를 낸다(공집합이면 검사가 무의미하다)
    assert old_block_numbers <= _allowed_numbers(ctx)


# ── 시스템 프롬프트 — 331 3단계: 260자 압축 + 선택 기준 1문장 ──


def test_시스템_프롬프트는_260자_이내이고_선택_기준과_형식_상한을_담는다():
    prompt = _system_prompt(2, 120)

    assert len(prompt) <= 260
    # 선택 기준(RuleStrategy.score와 같은 방향 — 낮은 p_empty 우선, 비슷하면 가까운 거리).
    assert "비어 있을 확률" in prompt
    assert "가까운" in prompt
    # JSON 형식 · chosen_index 규칙.
    assert '{"chosen_index": <정수>, "reason": <문자열>}' in prompt
    assert "chosen_index" in prompt
    assert "[후보]" in prompt
    # 문장·글자 상한 인자가 하드코딩이 아니라 그대로 박힌다 — 값을 바꾸면 문구도 바뀐다.
    assert "2문장" in prompt
    assert "120자" in prompt
    prompt2 = _system_prompt(3, 150)
    assert "3문장" in prompt2
    assert "150자" in prompt2
    assert len(prompt2) <= 260


# ── 설정 ──


def test_설정에서_고갈_페널티를_읽는다():
    class FakeSettings:
        time_score_empty_penalty_min = 4.0

    weights = ScoreWeights.from_settings(FakeSettings())

    assert weights.empty_penalty_min == 4.0
    assert weights.walk_speed_m_per_min == DEFAULT_WALK_SPEED_M_PER_MIN


def test_설정에_없으면_기본값을_쓴다():
    class EmptySettings:
        pass

    assert ScoreWeights.from_settings(EmptySettings()) == ScoreWeights()


# ── 에이전트 전략 탈락 로그 — 331 운영 후속 2-1 ──
#
# `AgentStrategy.rejections`는 요청마다 새 인스턴스에 쌓여 버려지므로(`registry._strategy`),
# 운영에서 "왜 규칙으로 떨어졌나"는 `_reject`가 남기는 INFO 한 줄이 유일한 단서다. 형식은
# 라우터 `reroute_check` 줄과 같은 `key=value`를 고정한다. 환각 가드 자체의 판정은
# `test_time_agent_strategy.py`가 보고, 여기서는 로그 줄만 본다.

STRATEGY_LOGGER = "app.TIME.strategy"


class _FakeLlmClient:
    """정해진 값을 그대로 돌려주는 가짜 게이트웨이."""

    def __init__(self, outcome: LlmResult | LlmError) -> None:
        self.outcome = outcome
        self.calls = 0

    def complete(self, system: str, user: str, *, json_schema=None):
        self.calls += 1
        return self.outcome


def _llm_result(text: str) -> LlmResult:
    return LlmResult(text=text, input_tokens=100, output_tokens=20, latency_ms=5.0, model="fake")


def _agent(outcome: LlmResult | LlmError) -> AgentStrategy:
    return AgentStrategy(_FakeLlmClient(outcome), RuleStrategy(WEIGHTS))


def _two_candidates() -> AgentContext:
    return fired_ctx(
        candidate("교대", distance_m=80.0, p_empty=0.2, current_stock=4, predicted_stock=3.0),
        candidate("사당", distance_m=400.0, p_empty=0.5, current_stock=2, predicted_stock=2.5),
    )


def _reject_lines(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.getMessage().startswith("agent_reject ")]


def test_LLM_오류_탈락은_사유와_LlmError_코드를_INFO로_남긴다(caplog):
    error = LlmError(code=LlmErrorCode.TIMEOUT, detail="응답 없음", retryable=True)
    with caplog.at_level(logging.INFO, logger=STRATEGY_LOGGER):
        proposal = _agent(error).decide(_two_candidates())

    assert proposal is not None and proposal.recommended_by == RECOMMENDED_BY_ALGORITHM
    lines = _reject_lines(caplog)
    assert lines == ["agent_reject reason=LLM_ERROR rental=TARGET candidates=2 llm=TIMEOUT"]
    assert caplog.records[0].levelno == logging.INFO


def test_BAD_JSON_탈락은_llm_칸을_대시로_남긴다(caplog):
    with caplog.at_level(logging.INFO, logger=STRATEGY_LOGGER):
        _agent(_llm_result("이건 JSON이 아니다")).decide(_two_candidates())

    assert _reject_lines(caplog) == [
        "agent_reject reason=BAD_JSON rental=TARGET candidates=2 llm=-"
    ]


def test_WRONG_CANDIDATE_NAME_탈락도_같은_형식으로_남긴다(caplog):
    text = '{"chosen_index": 0, "reason": "교대로 가세요. 사당은 멀어요."}'
    with caplog.at_level(logging.INFO, logger=STRATEGY_LOGGER):
        _agent(_llm_result(text)).decide(_two_candidates())

    assert _reject_lines(caplog) == [
        "agent_reject reason=WRONG_CANDIDATE_NAME rental=TARGET candidates=2 llm=-"
    ]


def test_후보가_하나라_LLM을_생략한_경우는_탈락_로그를_남기지_않는다(caplog):
    error = LlmError(code=LlmErrorCode.TIMEOUT, detail="응답 없음", retryable=True)
    with caplog.at_level(logging.INFO, logger=STRATEGY_LOGGER):
        proposal = _agent(error).decide(fired_ctx(candidate("교대", distance_m=80.0)))

    assert proposal is not None
    assert _reject_lines(caplog) == []


def test_정상_채택이면_탈락_로그가_없다(caplog):
    text = '{"chosen_index": 0, "reason": "역삼은 비어 있을 확률 90%입니다. 교대로 가세요."}'
    with caplog.at_level(logging.INFO, logger=STRATEGY_LOGGER):
        proposal = _agent(_llm_result(text)).decide(_two_candidates())

    assert proposal is not None and proposal.recommended_by == "AGENT"
    assert _reject_lines(caplog) == []
