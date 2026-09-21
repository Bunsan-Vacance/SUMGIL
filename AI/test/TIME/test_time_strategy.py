"""규칙 기준선 전략 검증(S15P21A104-203).

가중치(환승 4분·혼잡 3분)는 **잠정값**이라 "4분이 옳은가"를 검증하지 않는다. 대신 가중치가
무엇으로 바뀌든 지켜져야 하는 성질을 고정한다 — 점수 단조성, 읽지 못한 값의 처리, 문장이
없는 숫자를 만들지 않는 것.

특히 마지막이 중요하다. 이 전략이 LLM보다 정직한 이유가 "자리에 넣을 값이 없으면 문장을 통째로
뺀다"인데, 그게 깨지면 기준선으로서의 의미가 없다.
"""

from __future__ import annotations

from app.TIME.context import AgentContext, CandidateContext, DropCandidate, Stop
from app.TIME.strategy import (
    SOURCE_ALGORITHM,
    RuleStrategy,
    ScoreWeights,
    build_reason,
)
from app.TIME.trigger import SlotReading, StationReading, TriggerDecision

WEIGHTS = ScoreWeights(transfer_penalty_min=4.0, congestion_penalty_min=3.0)


def route(minutes: float | None = 20.0, transfers: int = 0, grades: tuple[int, ...] = ()) -> dict:
    """BE `RerouteResponse` 한 건. 래퍼(`{reason, source, route}`) 모양 그대로."""
    legs: list[dict] = [{"minutes": minutes, "routeId": "L2"}] if minutes is not None else []
    for grade in grades:
        legs.append({"minutes": 0.0, "routeId": "L3", "congestionGrade": grade})
    body: dict = {"legs": legs, "transferCount": transfers}
    if minutes is not None:
        body["totalMinutes"] = minutes
    return {"reason": "BE 고정 문구", "source": "ALGORITHM", "route": body}


def candidate(name: str = "교대", *, seq: int = 3, eta: int = 6, routes=None) -> CandidateContext:
    return CandidateContext(
        candidate=DropCandidate(
            stop=Stop(seq=seq, station_id=f"MT-{seq}", station_no=100 + seq, name=name),
            eta_minutes=eta,
        ),
        routes=list(routes) if routes is not None else [route()],
    )


def reading(no: int, *, name: str, eta: int, g_from: int, g_to: int, status: str = "ok"):
    return StationReading(
        station_no=no,
        station_name=name,
        eta_minutes=eta,
        now=SlotReading("08:00", 60.0, g_from, status),
        on_arrival=SlotReading("08:30", 92.0, g_to, status),
    )


def fired_ctx(*candidates: CandidateContext, facts: dict | None = None) -> AgentContext:
    segment = (reading(239, name="강남", eta=11, g_from=1, g_to=2),)
    default_facts = {
        "station_count": 1,
        "first_station_name": "강남",
        "first_eta_minutes": 11,
        "worst_station_name": "강남",
        "worst_eta_minutes": 11,
        "worst_grade_from": 1,
        "worst_grade_to": 2,
        "arrival_slot": "08:30",
        "calibration_fallback_used": False,
        "is_prediction": True,
    }
    decision = TriggerDecision(
        fired=True, segment=segment, facts=facts if facts is not None else default_facts
    )
    return AgentContext(decision=decision, candidates=list(candidates), current_route_id="L2")


# ── 선택 ──


def test_점수가_가장_낮은_경로를_고른다():
    fast = candidate("교대", seq=3, routes=[route(minutes=18.0)])
    slow = candidate("강남", seq=4, routes=[route(minutes=30.0)])

    proposal = RuleStrategy(WEIGHTS).decide(fired_ctx(fast, slow))

    assert proposal is not None
    assert proposal.candidate_index == 0
    assert proposal.score == 18.0
    assert proposal.source == SOURCE_ALGORITHM


def test_환승이_많으면_소요시간이_짧아도_밀린다():
    # 18분 + 환승 2회×4분 = 26  vs  22분 + 환승 0회 = 22
    many_transfers = candidate("교대", seq=3, routes=[route(minutes=18.0, transfers=2)])
    direct = candidate("강남", seq=4, routes=[route(minutes=22.0, transfers=0)])

    proposal = RuleStrategy(WEIGHTS).decide(fired_ctx(many_transfers, direct))

    assert proposal is not None
    assert proposal.candidate_index == 1


def test_혼잡_등급이_높으면_밀린다():
    # 20분 + 등급2×3분 = 26  vs  24분 + 등급0 = 24
    crowded = candidate("교대", seq=3, routes=[route(minutes=20.0, grades=(2,))])
    calm = candidate("강남", seq=4, routes=[route(minutes=24.0)])

    proposal = RuleStrategy(WEIGHTS).decide(fired_ctx(crowded, calm))

    assert proposal is not None
    assert proposal.candidate_index == 1


def test_한_후보_안의_여러_경로_중에서도_고른다():
    multi = candidate("교대", seq=3, routes=[route(minutes=30.0), route(minutes=16.0)])

    proposal = RuleStrategy(WEIGHTS).decide(fired_ctx(multi))

    assert proposal is not None
    assert proposal.score == 16.0


def test_경로를_가공하지_않고_그대로_들고_나간다():
    original = route(minutes=19.0, transfers=1)
    proposal = RuleStrategy(WEIGHTS).decide(fired_ctx(candidate(routes=[original])))

    assert proposal is not None
    assert proposal.route is original  # 사본도 아니고 그 객체 그대로


def test_가중치를_바꾸면_선택이_바뀐다():
    many_transfers = candidate("교대", seq=3, routes=[route(minutes=18.0, transfers=2)])
    direct = candidate("강남", seq=4, routes=[route(minutes=22.0)])
    ctx = fired_ctx(many_transfers, direct)

    assert RuleStrategy(WEIGHTS).decide(ctx).candidate_index == 1
    lenient = ScoreWeights(transfer_penalty_min=0.5, congestion_penalty_min=3.0)
    assert RuleStrategy(lenient).decide(ctx).candidate_index == 0


# ── 고를 게 없을 때 ──


def test_대안이_없으면_None이다():
    empty = AgentContext(decision=TriggerDecision(fired=True), candidates=[])

    assert RuleStrategy(WEIGHTS).decide(empty) is None


def test_조회_실패만_있으면_None이다():
    failed = CandidateContext(
        candidate=DropCandidate(stop=Stop(seq=3, name="교대"), eta_minutes=6),
        routes=[],
        error={"error": "UPSTREAM_UNAVAILABLE", "detail": "BE 미기동", "retryable": True},
    )

    assert RuleStrategy(WEIGHTS).decide(fired_ctx(failed)) is None


def test_소요시간을_못_읽으면_그_경로를_건너뛴다():
    unreadable = {"route": {"legs": [{"routeId": "L2"}]}}
    readable = route(minutes=25.0)
    both = candidate("교대", routes=[unreadable, readable])

    proposal = RuleStrategy(WEIGHTS).decide(fired_ctx(both))

    assert proposal is not None
    assert proposal.score == 25.0


def test_전부_못_읽으면_임의로_고르지_않고_None이다():
    # 응답 모양이 예상과 다르다는 뜻이다. 모르는 채로 안내하느니 안 하는 쪽이 낫다.
    unreadable = candidate("교대", routes=[{"route": {"legs": [{"routeId": "L2"}]}}])

    assert RuleStrategy(WEIGHTS).decide(fired_ctx(unreadable)) is None


def test_래퍼가_없는_경로_모양도_읽는다():
    # BE 응답 모양이 회신 대기 중이라 한쪽만 보면 조용히 0점이 된다.
    bare = {"totalMinutes": 21.0, "legs": [{"minutes": 21.0}], "transferCount": 0}

    proposal = RuleStrategy(WEIGHTS).decide(fired_ctx(candidate(routes=[bare])))

    assert proposal is not None
    assert proposal.score == 21.0


def test_totalMinutes가_없으면_legs_합으로_낸다():
    split = {"route": {"legs": [{"minutes": 8.0}, {"minutes": 7.0}], "transferCount": 0}}

    proposal = RuleStrategy(WEIGHTS).decide(fired_ctx(candidate(routes=[split])))

    assert proposal is not None
    assert proposal.score == 15.0


def test_혼잡_등급이_없는_경로를_쾌적으로_치지_않는다():
    # 없는 것을 0(쾌적)으로 치면 혼잡 정보가 없는 경로가 늘 이긴다. 같은 소요시간이면
    # 등급 정보가 있는 쪽과 점수가 같아야 한다(중립).
    no_grade = candidate("교대", seq=3, routes=[route(minutes=20.0)])
    zero_grade = candidate("강남", seq=4, routes=[route(minutes=20.0, grades=(0,))])

    strategy = RuleStrategy(WEIGHTS)
    assert strategy.score(no_grade.routes[0]) == strategy.score(zero_grade.routes[0])


# ── 안내 문장 — 없는 숫자를 만들지 않는다 ──


def test_문장에_하차역과_혼잡_변화가_담긴다():
    ctx = fired_ctx(candidate("교대", eta=6))
    proposal = RuleStrategy(WEIGHTS).decide(ctx)

    assert proposal is not None
    reason = proposal.reason
    assert "교대" in reason
    assert "강남" in reason  # 혼잡해지는 역
    assert "1등급에서 2등급" in reason
    assert "6분" in reason  # 하차역까지 남은 시간


def test_문장이_예측임을_드러낸다():
    # "지금 혼잡하다"가 아니라 "도착 시점에 혼잡해진다"여야 한다 — CROWD는 하루 1회 배치다.
    proposal = RuleStrategy(WEIGHTS).decide(fired_ctx(candidate()))

    assert proposal is not None
    assert "도착 시점" in proposal.reason
    assert "보입니다" in proposal.reason


def test_공휴일_보정값이면_문장이_그_사실을_밝힌다():
    facts = {
        "worst_station_name": "강남",
        "worst_eta_minutes": 11,
        "worst_grade_from": 1,
        "worst_grade_to": 2,
        "calibration_fallback_used": True,
        "is_prediction": True,
    }
    ctx = fired_ctx(candidate(), facts=facts)

    proposal = RuleStrategy(WEIGHTS).decide(ctx)

    assert proposal is not None
    assert "공휴일" in proposal.reason


def test_사실이_비면_그_문장을_통째로_뺀다():
    # 템플릿이 LLM보다 정직한 지점. 등급 정보가 없으면 등급 문장을 만들지 않는다.
    facts = {"worst_station_name": "강남", "calibration_fallback_used": False}
    ctx = fired_ctx(candidate(), facts=facts)

    reason = RuleStrategy(WEIGHTS).decide(ctx).reason

    assert "등급" not in reason
    assert "강남" in reason  # 아는 것은 여전히 말한다


def test_사실이_아예_없어도_문장이_만들어진다():
    ctx = fired_ctx(candidate("교대"), facts={})

    reason = RuleStrategy(WEIGHTS).decide(ctx).reason

    assert "교대" in reason
    assert reason.strip()


def test_하차역_이름을_모르면_지어내지_않는다():
    nameless = CandidateContext(
        candidate=DropCandidate(stop=Stop(seq=3, station_id="MT-3", station_no=103), eta_minutes=6),
        routes=[route(minutes=20.0)],
    )

    reason = RuleStrategy(WEIGHTS).decide(fired_ctx(nameless)).reason

    assert "None" not in reason
    assert "다음 역" in reason


def test_build_reason을_직접_불러도_같은_문장이다():
    # 204 평가가 전략을 거치지 않고 문장만 다시 만들 수 있어야 한다.
    cand = candidate("교대", eta=6)
    ctx = fired_ctx(cand)

    assert build_reason(ctx, cand, cand.routes[0]) == RuleStrategy(WEIGHTS).decide(ctx).reason


# ── 설정 ──


def test_설정에서_가중치를_읽는다():
    class FakeSettings:
        time_score_transfer_penalty_min = 9.0
        time_score_congestion_penalty_min = 1.0

    weights = ScoreWeights.from_settings(FakeSettings())

    assert weights.transfer_penalty_min == 9.0
    assert weights.congestion_penalty_min == 1.0
