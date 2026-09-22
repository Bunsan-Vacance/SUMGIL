"""따릉이 재고 고갈 트리거 판정 검증(S15P21A104-203/302).

임계값 자체는 **잠정값**이라(실제 재고·p_empty 분포 미확보) 여기서 "0.7이 옳은가"를 검증하지
않는다. 대신 **임계값이 무엇이든 지켜져야 하는 성질**을 고정한다 — 규칙 7개의 순서(먼저 맞는
것이 이긴다), 경계 동작, `None`을 0으로 읽지 않는 것, 쿨다운, `force`의 범위. 나중에 실제
분포를 보고 숫자를 바꿔도 이 테스트는 그대로 통과해야 한다.
"""

from __future__ import annotations

from app.TIME.schemas import ToolError
from app.TIME.trigger import (
    REASON_BELOW_THRESHOLD,
    REASON_COOLDOWN,
    REASON_FORCED,
    REASON_HORIZON_OUT_OF_RANGE,
    REASON_LOW_CONFIDENCE,
    REASON_LOW_PREDICTED_STOCK,
    REASON_P_EMPTY,
    REASON_STOCK_UNKNOWN,
    StockReading,
    Thresholds,
    evaluate,
)

LIMITS = Thresholds(p_empty=0.7, min_stock=1.0, max_eta_min=30, cooldown_sec=600.0)


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


# ── 1) 도구 오류 ──


def test_도구_오류면_stock_unknown이고_트리거하지_않는다():
    err = ToolError.upstream_unavailable("모델 아티팩트 장애")
    decision = evaluate(err, eta_minutes=10, thresholds=LIMITS)

    assert not decision.fired
    assert decision.reason == REASON_STOCK_UNKNOWN
    assert decision.facts == {}


def test_오류는_force여도_고갈로_읽지_않는다():
    # force는 1~4를 우회하지 않는다 — 오류를 "비었다"로 읽는 것은 값 지어내기다.
    err = ToolError.not_found("실시간 재고 없음")
    decision = evaluate(err, eta_minutes=10, thresholds=LIMITS, force=True)

    assert not decision.fired
    assert decision.reason == REASON_STOCK_UNKNOWN


# ── 2) horizon ──


def test_eta가_상한을_넘으면_horizon_out_of_range다():
    decision = evaluate(reading(), eta_minutes=31, thresholds=LIMITS)

    assert not decision.fired
    assert decision.reason == REASON_HORIZON_OUT_OF_RANGE


def test_eta가_상한과_같으면_넘지_않은_것으로_본다():
    decision = evaluate(reading(p_empty=0.9), eta_minutes=30, thresholds=LIMITS)

    assert decision.fired
    assert decision.reason == REASON_P_EMPTY


def test_model_horizon_min이_없으면_horizon_out_of_range다():
    decision = evaluate(reading(model_horizon_min=None), eta_minutes=10, thresholds=LIMITS)

    assert not decision.fired
    assert decision.reason == REASON_HORIZON_OUT_OF_RANGE


# ── 3) 신뢰도 ──


def test_전역_폴백_출처는_low_confidence다():
    decision = evaluate(
        reading(source="lightgbm_global_fallback", p_empty=0.9), eta_minutes=10, thresholds=LIMITS
    )

    assert not decision.fired
    assert decision.reason == REASON_LOW_CONFIDENCE


# ── 4) 쿨다운 ──


def test_쿨다운_안이면_조건을_보지_않고_접는다():
    decision = evaluate(
        reading(p_empty=0.9), eta_minutes=10, thresholds=LIMITS, seconds_since_last_fire=599.0
    )

    assert not decision.fired
    assert decision.reason == REASON_COOLDOWN


def test_쿨다운이_경계값과_같으면_막지_않는다():
    decision = evaluate(
        reading(p_empty=0.9), eta_minutes=10, thresholds=LIMITS, seconds_since_last_fire=600.0
    )

    assert decision.fired
    assert decision.reason == REASON_P_EMPTY


def test_쿨다운이_지나면_다시_트리거된다():
    decision = evaluate(
        reading(p_empty=0.9), eta_minutes=10, thresholds=LIMITS, seconds_since_last_fire=601.0
    )

    assert decision.fired


def test_직전_발동_기록이_없으면_쿨다운을_보지_않는다():
    decision = evaluate(reading(p_empty=0.9), eta_minutes=10, thresholds=LIMITS)

    assert decision.fired
    assert decision.reason == REASON_P_EMPTY


# ── 5) force ──


def test_force면_below_threshold_대신_강제로_뜬다():
    decision = evaluate(
        reading(p_empty=0.1, predicted_stock=5.0), eta_minutes=10, thresholds=LIMITS, force=True
    )

    assert decision.fired
    assert decision.reason == REASON_FORCED


def test_force여도_horizon_초과는_막는다():
    decision = evaluate(reading(), eta_minutes=31, thresholds=LIMITS, force=True)

    assert not decision.fired
    assert decision.reason == REASON_HORIZON_OUT_OF_RANGE


def test_force여도_신뢰도_낮은_출처는_막는다():
    decision = evaluate(
        reading(source="lightgbm_global_fallback"), eta_minutes=10, thresholds=LIMITS, force=True
    )

    assert not decision.fired
    assert decision.reason == REASON_LOW_CONFIDENCE


def test_force여도_쿨다운_안이면_막는다():
    decision = evaluate(
        reading(), eta_minutes=10, thresholds=LIMITS, seconds_since_last_fire=1.0, force=True
    )

    assert not decision.fired
    assert decision.reason == REASON_COOLDOWN


# ── 6) 고갈 판정 — p_empty 우선, predicted_stock 폴백 ──


def test_p_empty가_임계_이상이면_트리거된다():
    decision = evaluate(
        reading(p_empty=0.8, predicted_stock=5.0), eta_minutes=10, thresholds=LIMITS
    )

    assert decision.fired
    assert decision.reason == REASON_P_EMPTY


def test_p_empty가_경계값과_같으면_트리거된다():
    decision = evaluate(
        reading(p_empty=0.7, predicted_stock=5.0), eta_minutes=10, thresholds=LIMITS
    )

    assert decision.fired
    assert decision.reason == REASON_P_EMPTY


def test_predicted_stock이_경계값과_같으면_트리거된다():
    decision = evaluate(
        reading(p_empty=None, predicted_stock=1.0), eta_minutes=10, thresholds=LIMITS
    )

    assert decision.fired
    assert decision.reason == REASON_LOW_PREDICTED_STOCK


def test_p_empty가_None이면_predicted_stock으로_폴백한다():
    decision = evaluate(
        reading(p_empty=None, predicted_stock=0.5), eta_minutes=10, thresholds=LIMITS
    )

    assert decision.fired
    assert decision.reason == REASON_LOW_PREDICTED_STOCK


def test_p_empty가_낮아도_predicted_stock이_낮으면_트리거된다():
    # p_empty 조건은 안 맞았지만 predicted_stock 조건은 맞는 경우 — 6번 규칙 안에서 순서대로 본다.
    decision = evaluate(
        reading(p_empty=0.1, predicted_stock=1.0), eta_minutes=10, thresholds=LIMITS
    )

    assert decision.fired
    assert decision.reason == REASON_LOW_PREDICTED_STOCK


def test_None은_0으로_읽지_않는다():
    # p_empty·predicted_stock 둘 다 None이면 고갈 조건에 들어가지도 못하고 below_threshold다.
    decision = evaluate(
        reading(p_empty=None, predicted_stock=None), eta_minutes=10, thresholds=LIMITS
    )

    assert not decision.fired
    assert decision.reason == REASON_BELOW_THRESHOLD


# ── 7) 평소 상태 ──


def test_둘_다_임계를_못_넘으면_below_threshold다():
    decision = evaluate(
        reading(p_empty=0.2, predicted_stock=5.0), eta_minutes=10, thresholds=LIMITS
    )

    assert not decision.fired
    assert decision.reason == REASON_BELOW_THRESHOLD
    assert decision.facts == {}


# ── facts ──


def test_트리거되면_facts에_판단_근거가_담긴다():
    decision = evaluate(
        reading(
            current_stock=0,
            predicted_stock=0.5,
            p_empty=0.9,
            p_full=0.0,
            source="lightgbm",
            model_horizon_min=10,
        ),
        eta_minutes=8,
        thresholds=LIMITS,
    )

    assert decision.fired
    assert decision.facts == {
        "eta_minutes": 8,
        "current_stock": 0,
        "predicted_stock": 0.5,
        "p_empty": 0.9,
        "p_full": 0.0,
        "source": "lightgbm",
        "model_horizon_min": 10,
    }


# ── 임계값 주입 ──


def test_임계값을_낮추면_같은_입력이_트리거된다():
    r = reading(p_empty=0.5, predicted_stock=5.0)

    assert not evaluate(r, eta_minutes=10, thresholds=LIMITS).fired
    loosened = Thresholds(p_empty=0.4, min_stock=1.0, max_eta_min=30, cooldown_sec=600.0)
    assert evaluate(r, eta_minutes=10, thresholds=loosened).fired


def test_설정에서_임계값을_읽는다():
    class FakeSettings:
        time_trigger_p_empty = 0.5
        time_trigger_min_stock = 2.0
        time_trigger_max_eta_min = 20
        time_trigger_cooldown_sec = 120.0

    limits = Thresholds.from_settings(FakeSettings())

    assert limits.p_empty == 0.5
    assert limits.min_stock == 2.0
    assert limits.max_eta_min == 20
    assert limits.cooldown_sec == 120.0


def test_설정에_없으면_기본값을_쓴다():
    class EmptySettings:
        pass

    limits = Thresholds.from_settings(EmptySettings())

    assert limits == Thresholds()
