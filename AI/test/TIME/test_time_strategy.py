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

import pytest

from app.TIME.context import AgentContext, CandidateContext, RentalCandidate
from app.TIME.station_index import RentalStation
from app.TIME.strategy import (
    DEFAULT_WALK_SPEED_M_PER_MIN,
    RECOMMENDED_BY_ALGORITHM,
    RuleStrategy,
    ScoreWeights,
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
