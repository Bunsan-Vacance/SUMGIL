"""하차 후보역 생성 검증(S15P21A104-203).

`generate`가 순수 함수라 목이 거의 없다 — 정차역 목록·트리거 판정·`get_arrivals` 응답을 전부
인자로 만들어 넣는다. 실제 경로 데이터의 공급원은 아직 회신 대기라
(`TO_BE-time-station-sequence-01`), 여기서 고정하는 것은 **공급원이 무엇이든 지켜져야 하는
성질**이다 — 순서 필터, 구간 경계, 상한, 환승 우대가 후보를 빼지 않는다는 것, LIVE 아닌 도착
정보에서 후보를 내지 않는다는 것.
"""

from __future__ import annotations

import logging

import pytest

from app.TIME.candidates import (
    MAX_CANDIDATES,
    RANK_PLAIN,
    RANK_TRANSFER,
    generate,
)
from app.TIME.context import Stop
from app.TIME.trigger import SlotReading, StationReading, TriggerDecision

LIVE = {"status": "LIVE", "trains": [{"train_id": "2001", "direction": "성수행"}]}
"""정상적인 `get_arrivals` 응답. 대부분의 케이스가 이걸 쓴다."""


def stops(count: int = 10, *, transfers: tuple[int, ...] = ()) -> list[Stop]:
    """seq 1..count 정차역. `station_no`는 100+seq, `station_id`는 'MT-1xx'."""
    return [
        Stop(
            seq=i,
            station_id=f"MT-{100 + i}",
            station_no=100 + i,
            name=f"역{i}",
            is_transfer=i in transfers,
        )
        for i in range(1, count + 1)
    ]


def reading(station_no: int) -> StationReading:
    """혼잡 구간에 들어간 역 하나. 값 자체는 이 테스트의 관심사가 아니다(트리거 쪽에서 검증)."""
    return StationReading(
        station_no=station_no,
        station_name=f"역{station_no - 100}",
        eta_minutes=10,
        now=SlotReading(time_slot_30min="08:00", congestion_pct=60.0, grade=1, data_status="ok"),
        on_arrival=SlotReading(
            time_slot_30min="08:30", congestion_pct=90.0, grade=2, data_status="ok"
        ),
    )


def fired(*station_nos: int) -> TriggerDecision:
    return TriggerDecision(fired=True, segment=tuple(reading(no) for no in station_nos))


ETA = {i: i * 2 for i in range(1, 31)}
"""역별 소요시간. seq에 비례하게 둬서 '어느 역의 값인지'가 눈에 보이게 한다."""


def run(stop_list: list[Stop], decision: TriggerDecision, **kwargs) -> list:
    """자주 쓰는 인자를 채운 호출 헬퍼."""
    kwargs.setdefault("current_seq", 2)
    kwargs.setdefault("eta_minutes_by_seq", ETA)
    kwargs.setdefault("arrivals", LIVE)
    return generate(stop_list, decision, **kwargs)


def seqs(candidates) -> list[int]:
    return [c.stop.seq for c in candidates]


# ── 순서 필터 ──


def test_현재_위치_이전_역은_후보에서_빠진다():
    result = run(stops(10), fired(109, 110), current_seq=4)

    assert seqs(result) == [5, 6, 7, 8]


def test_현재_위치_역_자신도_후보가_아니다():
    """안내가 뜬 시점에 이미 정차 중이거나 막 떠난 역이라 행동할 수 없다."""
    result = run(stops(10), fired(109, 110), current_seq=4)

    assert 4 not in seqs(result)


def test_트리거_구간_안과_이후_역은_후보에서_빠진다():
    # 구간이 108·109이므로 경계는 seq 8. 8·9는 구간 안, 10은 구간 이후다.
    result = run(stops(10), fired(108, 109))

    assert seqs(result) == [3, 4, 5, 6, 7]


def test_구간_station_no가_정차역과_매칭되지_않으면_빈_목록():
    """경계를 못 짚으면 혼잡 구간 안쪽을 후보로 낼 수 있어 아무것도 내지 않는다."""
    result = run(stops(10), fired(9001, 9002))

    assert result == []


def test_트리거가_안_떴으면_빈_목록():
    result = run(stops(10), TriggerDecision(fired=False, skip_reason="below_threshold"))

    assert result == []


# ── 목적지 ──


def test_목적지_역은_후보가_아니다():
    # 구간은 109·110(경계 9)이라 seq 8이 살아남을 자리인데, 그 역이 목적지다.
    result = run(stops(10), fired(109, 110), dest_station_id="MT-108")

    assert 8 not in seqs(result)
    assert seqs(result) == [3, 4, 5, 6, 7]


def test_목적지를_seq로_줘도_빠진다():
    """`station_id`가 아직 안 채워진 정차역 목록도 있을 수 있어 두 경로를 다 연다."""
    result = run(stops(10), fired(109, 110), dest_seq=8)

    assert 8 not in seqs(result)


def test_목적지를_안_주면_마지막_정차역을_목적지로_본다():
    # 경로는 목적지에서 끝난다(replan 계약). 구간이 마지막 역 하나뿐이어도 후보에 목적지가
    # 섞이지 않아야 한다.
    result = run(stops(6), fired(106), current_seq=0)

    assert seqs(result) == [1, 2, 3, 4, 5]
    assert 6 not in seqs(result)


# ── 상한 ──


def test_후보가_많아도_상한_5개를_넘지_않는다():
    result = run(stops(20), fired(118, 119), current_seq=0, dest_seq=20)

    # 자격이 있는 역은 seq 1~17로 17개다.
    assert len(result) == MAX_CANDIDATES
    assert len(result) == 5


def test_상한은_가까운_역부터_채운다():
    """멀리 있는 역만 남으면 안내가 도착하기 전에 지나쳐버린다."""
    result = run(stops(20), fired(118, 119), current_seq=0, dest_seq=20)

    assert seqs(result) == [1, 2, 3, 4, 5]


def test_limit이_0이면_빈_목록():
    assert run(stops(10), fired(109, 110), limit=0) == []


# ── 환승 우대 ──


def test_환승역이_앞순위로_온다():
    result = run(stops(10, transfers=(5,)), fired(109, 110))

    assert seqs(result) == [5, 3, 4, 6, 7]
    assert result[0].rank_hint == RANK_TRANSFER
    assert all(c.rank_hint == RANK_PLAIN for c in result[1:])


def test_환승역이_여럿이면_그들끼리는_가까운_순서다():
    result = run(stops(10, transfers=(4, 6)), fired(109, 110))

    assert seqs(result) == [4, 6, 3, 5, 7]


def test_환승_여부를_모르는_역도_후보에_남는다():
    """`is_transfer`는 모르면 False다. 모른다고 빼면 실제 환승역을 통째로 놓친다 —
    우대는 정렬 힌트일 뿐 후보 집합을 바꾸지 않아야 한다."""
    result = run(stops(10), fired(109, 110))  # 전부 is_transfer=False

    assert seqs(result) == [3, 4, 5, 6, 7]
    assert all(c.rank_hint == RANK_PLAIN for c in result)


def test_환승역_우대가_가까운_역을_밀어내지_않는다():
    """상한을 환승 우대로 채우면 seq 1~5가 잘려나간다. 그렇게 되지 않는지 본다."""
    result = run(stops(20, transfers=(15, 16)), fired(118, 119), current_seq=0, dest_seq=20)

    assert seqs(result) == [1, 2, 3, 4, 5]


# ── get_arrivals 처리 ──


@pytest.mark.parametrize("status", ["NO_INFO", "OUTSIDE_WINDOW", "STALE"])
def test_도착정보가_LIVE가_아니면_빈_목록(status: str):
    """어느 열차에 타고 있는지 모르는 채로 '여기서 내리세요'를 말할 수 없다."""
    result = run(stops(10), fired(109, 110), arrivals={"status": status, "trains": []})

    assert result == []


def test_도착정보가_LIVE면_후보가_나온다():
    """위 세 가지와 짝. status 4종 중 LIVE만 통과한다는 것을 한 쌍으로 고정한다."""
    result = run(stops(10), fired(109, 110), arrivals={"status": "LIVE", "trains": []})

    assert seqs(result) == [3, 4, 5, 6, 7]


def test_도착정보가_None이면_빈_목록():
    """None은 '조회하지 않았다' 또는 '실패했다'이지 LIVE가 아니다 — LIVE 아닌 것과 같이 막는다.
    폴링마다 도는 기능이라 한 번 걸러도 다음 폴링에 다시 기회가 온다."""
    result = run(stops(10), fired(109, 110), arrivals=None)

    assert result == []


def test_ToolError_응답도_빈_목록():
    """도구가 실패하면 status가 없는 딕셔너리가 온다. 그대로 막혀야 한다."""
    error = {"error": "UPSTREAM_UNAVAILABLE", "detail": "BE 미기동", "retryable": True}
    result = run(stops(10), fired(109, 110), arrivals=error)

    assert result == []


# ── 소요시간 ──


def test_eta는_인자에서_그대로_온다():
    eta = {3: 4, 4: 9, 5: 11, 6: 14, 7: 21}
    result = run(stops(10), fired(109, 110), eta_minutes_by_seq=eta)

    assert {c.stop.seq: c.eta_minutes for c in result} == eta


def test_소요시간이_없는_역은_후보에서_빠진다():
    """값을 지어내느니 후보 하나를 잃는 쪽이 낫다."""
    eta = {3: 6, 5: 10, 7: 14}
    result = run(stops(10), fired(109, 110), eta_minutes_by_seq=eta)

    assert seqs(result) == [3, 5, 7]


# ── 빈 결과 ──


def test_후보가_될_역이_하나도_없으면_빈_목록():
    # 현재 위치(7) 바로 다음이 혼잡 구간(108)이라 사이에 낄 역이 없다.
    result = run(stops(10), fired(108, 109), current_seq=7)

    assert result == []


def test_정차역_목록이_비면_빈_목록():
    assert run([], fired(108, 109)) == []


def test_station_no가_하나도_없으면_배선_실수로_보고_경고한다(caplog):
    """조용한 실패를 막는다.

    `Stop.station_no`가 안 채워지면 혼잡 구간 경계를 영영 못 짚어 재안내가 발동하지 않는데,
    오류가 나지 않아 "혼잡이 없었다"와 구분되지 않는다. 배선 실수일 때만 로그로 드러낸다 —
    station_no가 채워져 있는데 구간과 안 겹치는 것은 정상적인 데이터 상황이라 조용히 둔다.
    """
    no_numbers = [Stop(seq=i, station_id=f"MT-{100 + i}", name=f"역{i}") for i in range(1, 4)]
    decision = fired(239)

    with caplog.at_level(logging.WARNING):
        result = generate(
            no_numbers, decision, current_seq=1, eta_minutes_by_seq=ETA, arrivals=LIVE
        )

    assert result == []
    assert any("station_no" in record.message for record in caplog.records)


def test_station_no가_있는데_구간과_안_겹치면_경고하지_않는다(caplog):
    numbered = stops(3)
    decision = fired(999)  # 어느 역과도 안 겹친다

    with caplog.at_level(logging.WARNING):
        result = generate(numbered, decision, current_seq=1, eta_minutes_by_seq=ETA, arrivals=LIVE)

    assert result == []
    assert not caplog.records
