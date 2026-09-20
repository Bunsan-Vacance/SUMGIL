"""혼잡 급등 트리거 판정 검증(S15P21A104-203).

임계값 자체는 **잠정값**이라(CROWD 예측 표 미확보) 여기서 "15%p가 옳은가"를 검증하지 않는다.
대신 **임계값이 무엇이든 지켜져야 하는 성질**을 고정한다 — 경계 동작, 결측 처리, 연속 구간 판정,
쿨다운. 나중에 실제 분포를 보고 숫자를 바꿔도 이 테스트는 그대로 통과해야 한다.
"""

from __future__ import annotations

import pytest

from app.TIME.trigger import (
    SKIP_BELOW_THRESHOLD,
    SKIP_COOLDOWN,
    SKIP_NO_DATA,
    SKIP_NO_READINGS,
    SKIP_RUN_TOO_SHORT,
    SlotReading,
    StationReading,
    TriggerThresholds,
    evaluate,
)

LIMITS = TriggerThresholds(grade_rise=1, pct_rise=15.0, min_run=2, cooldown_sec=600.0)


def slot(
    pct: float | None, grade: int | None, status: str = "ok", at: str = "08:30"
) -> SlotReading:
    return SlotReading(time_slot_30min=at, congestion_pct=pct, grade=grade, data_status=status)


def station(
    no: int,
    *,
    now: SlotReading,
    on_arrival: SlotReading,
    name: str | None = None,
    eta: int = 10,
) -> StationReading:
    return StationReading(
        station_no=no,
        station_name=name or f"역{no}",
        eta_minutes=eta,
        now=now,
        on_arrival=on_arrival,
    )


def rising(no: int, **kwargs) -> StationReading:
    """임계를 넉넉히 넘는 역."""
    return station(no, now=slot(60.0, 1), on_arrival=slot(90.0, 2), **kwargs)


def flat(no: int, **kwargs) -> StationReading:
    """변화 없는 역."""
    return station(no, now=slot(60.0, 1), on_arrival=slot(61.0, 1), **kwargs)


# ── 기본 판정 ──


def test_연속_2역이_급등하면_트리거된다():
    decision = evaluate([rising(1), rising(2), flat(3)], thresholds=LIMITS)

    assert decision.fired
    assert [r.station_no for r in decision.segment] == [1, 2]
    assert decision.skip_reason is None


def test_한_역만_급등하면_노이즈로_보고_트리거하지_않는다():
    decision = evaluate([rising(1), flat(2), flat(3)], thresholds=LIMITS)

    assert not decision.fired
    # "임계를 넘은 역이 있었지만 연속이 짧았다"와 "아예 없었다"를 구분해 남긴다.
    assert decision.skip_reason == SKIP_RUN_TOO_SHORT


def test_아무_역도_임계를_못_넘으면_below_threshold다():
    decision = evaluate([flat(1), flat(2)], thresholds=LIMITS)

    assert not decision.fired
    assert decision.skip_reason == SKIP_BELOW_THRESHOLD


def test_읽을_역이_없으면_트리거하지_않는다():
    decision = evaluate([], thresholds=LIMITS)

    assert not decision.fired
    assert decision.skip_reason == SKIP_NO_READINGS


# ── 경계 ──


def test_등급과_퍼센트를_둘_다_넘어야_한다():
    # 등급만 오르고 %p가 모자란 경우
    grade_only = station(1, now=slot(60.0, 1), on_arrival=slot(70.0, 2))
    # %p만 오르고 등급이 그대로인 경우
    pct_only = station(2, now=slot(60.0, 1), on_arrival=slot(90.0, 1))

    decision = evaluate([grade_only, pct_only], thresholds=LIMITS)

    assert not decision.fired
    assert decision.skip_reason == SKIP_BELOW_THRESHOLD


def test_임계값_정확히_같으면_넘은_것으로_본다():
    # grade +1, pct +15.0 — 둘 다 임계와 정확히 일치
    exact = [
        station(1, now=slot(60.0, 1), on_arrival=slot(75.0, 2)),
        station(2, now=slot(60.0, 1), on_arrival=slot(75.0, 2)),
    ]

    assert evaluate(exact, thresholds=LIMITS).fired


def test_임계값_바로_아래는_넘지_않는다():
    below = [
        station(1, now=slot(60.0, 1), on_arrival=slot(74.9, 2)),
        station(2, now=slot(60.0, 1), on_arrival=slot(74.9, 2)),
    ]

    assert not evaluate(below, thresholds=LIMITS).fired


def test_혼잡도가_내려가면_트리거하지_않는다():
    falling = [
        station(1, now=slot(90.0, 2), on_arrival=slot(60.0, 1)),
        station(2, now=slot(90.0, 2), on_arrival=slot(60.0, 1)),
    ]

    assert not evaluate(falling, thresholds=LIMITS).fired


# ── 결측 처리 — 값을 지어내지 않는다 ──


@pytest.mark.parametrize("status", ["no_lookup", "segment_truncated", "no_calibration"])
def test_결측_역은_구간을_끊지_않고_연속_수에도_안_들어간다(status):
    # 급등 - 결측 - 급등. 결측이 끊으면 연속 1+1이라 트리거 안 되고,
    # 결측을 세면 연속 3이 된다. 건너뛰는 것이 맞으므로 연속 2로 트리거돼야 한다.
    missing = station(2, now=slot(None, None, status), on_arrival=slot(None, None, status))
    decision = evaluate([rising(1), missing, rising(3)], thresholds=LIMITS)

    assert decision.fired
    assert [r.station_no for r in decision.segment] == [1, 3]
    assert decision.facts["station_count"] == 2  # 결측 역은 세지 않는다


def test_배치_미실행이면_조건을_보지_않고_접는다():
    # no_data는 "혼잡하지 않다"가 아니라 "판단 근거가 없다"이다.
    no_data = station(2, now=slot(None, None, "no_data"), on_arrival=slot(None, None, "no_data"))
    decision = evaluate([rising(1), rising(3), no_data], thresholds=LIMITS)

    assert not decision.fired
    assert decision.skip_reason == SKIP_NO_DATA


def test_상태는_ok인데_등급만_null이면_비교에서_뺀다():
    # 배율표 결측으로 grade만 빠진 셀. 상태만 믿고 None을 빼면 그 자리에서 터진다.
    half = station(2, now=slot(60.0, None), on_arrival=slot(90.0, 2))
    decision = evaluate([rising(1), half, rising(3)], thresholds=LIMITS)

    assert decision.fired
    assert [r.station_no for r in decision.segment] == [1, 3]


def test_공휴일_보정_셀은_쓰되_사실로_표시한다():
    # calibration_fallback은 값이 있으므로 쓴다. 다만 일요일 배율을 빌려 쓴 값이라 안내 문장이
    # 그 사실을 밝혀야 하고, 그러려면 facts에 실려야 한다.
    borrowed = station(
        2,
        now=slot(60.0, 1, "calibration_fallback"),
        on_arrival=slot(90.0, 2, "calibration_fallback"),
    )
    decision = evaluate([rising(1), borrowed], thresholds=LIMITS)

    assert decision.fired
    assert decision.facts["calibration_fallback_used"] is True


def test_보정_셀이_없으면_표시도_없다():
    decision = evaluate([rising(1), rising(2)], thresholds=LIMITS)

    assert decision.facts["calibration_fallback_used"] is False


# ── 쿨다운 ──


def test_쿨다운_안이면_조건을_보지_않고_접는다():
    decision = evaluate([rising(1), rising(2)], thresholds=LIMITS, seconds_since_last_fire=59.0)

    assert not decision.fired
    assert decision.skip_reason == SKIP_COOLDOWN


def test_쿨다운이_지나면_다시_트리거된다():
    decision = evaluate([rising(1), rising(2)], thresholds=LIMITS, seconds_since_last_fire=601.0)

    assert decision.fired


def test_직전_발동_기록이_없으면_쿨다운을_보지_않는다():
    assert evaluate([rising(1), rising(2)], thresholds=LIMITS).fired


# ── 구간 선택·사실 ──


def test_구간이_여러_개면_가장_이른_것을_쓴다():
    # 사용자가 먼저 마주치는 구간이 의미 있다.
    readings = [rising(1), rising(2), flat(3), flat(4), rising(5), rising(6)]

    decision = evaluate(readings, thresholds=LIMITS)

    assert [r.station_no for r in decision.segment] == [1, 2]


def test_사실에_가장_심한_역이_담긴다():
    mild = station(1, now=slot(60.0, 1), on_arrival=slot(80.0, 2), name="약한역", eta=5)
    severe = station(2, now=slot(60.0, 1), on_arrival=slot(95.0, 2), name="심한역", eta=12)

    facts = evaluate([mild, severe], thresholds=LIMITS).facts

    assert facts["first_station_name"] == "약한역"
    assert facts["first_eta_minutes"] == 5
    assert facts["worst_station_name"] == "심한역"
    assert facts["worst_eta_minutes"] == 12
    assert facts["worst_pct_from"] == 60.0
    assert facts["worst_pct_to"] == 95.0


def test_사실이_예측임을_표시한다():
    # CROWD는 하루 1회 배치라 실측이 아니다. 문장 생성 쪽이 "지금 혼잡해졌다"고 쓰지 않도록
    # 사실로 박아둔다.
    facts = evaluate([rising(1), rising(2)], thresholds=LIMITS).facts

    assert facts["is_prediction"] is True
    assert facts["arrival_slot"] == "08:30"


def test_트리거되지_않으면_구간도_사실도_비어_있다():
    decision = evaluate([flat(1), flat(2)], thresholds=LIMITS)

    assert decision.segment == ()
    assert decision.facts == {}


# ── 임계값 주입 ──


def test_임계값을_낮추면_같은_입력이_트리거된다():
    readings = [
        station(1, now=slot(60.0, 1), on_arrival=slot(70.0, 2)),
        station(2, now=slot(60.0, 1), on_arrival=slot(70.0, 2)),
    ]

    assert not evaluate(readings, thresholds=LIMITS).fired
    assert evaluate(readings, thresholds=TriggerThresholds(grade_rise=1, pct_rise=10.0)).fired


def test_연속_요구를_1로_낮추면_단일_역도_트리거된다():
    readings = [rising(1), flat(2)]

    loosened = TriggerThresholds(grade_rise=1, pct_rise=15.0, min_run=1)
    assert evaluate(readings, thresholds=loosened).fired


def test_설정에서_임계값을_읽는다():
    class FakeSettings:
        time_trigger_grade_rise = 2
        time_trigger_pct_rise = 30.0
        time_trigger_min_run = 3
        time_trigger_cooldown_sec = 120.0

    limits = TriggerThresholds.from_settings(FakeSettings())

    assert limits.grade_rise == 2
    assert limits.pct_rise == 30.0
    assert limits.min_run == 3
    assert limits.cooldown_sec == 120.0
