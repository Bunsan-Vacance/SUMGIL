"""주변 따릉이 대여소 후보 생성 검증(S15P21A104-203/302).

`generate`가 순수 함수라 목이 거의 없다 — `StationIndex`(가짜 `InMemoryStationIndex`)와 대상
대여소만 있으면 된다. 여기서 고정하려는 것은 넷이다 — 대상 자신 제외, 재고 0 제외(`None`은
통과), 제외 후에도 상한을 넘지 않는 것, 빈 색인이면 빈 목록.
"""

from __future__ import annotations

from app.TIME.candidates import MAX_CANDIDATES, generate
from app.TIME.station_index import InMemoryStationIndex, RentalStation


def _station(
    rental_id: str,
    *,
    lat: float = 37.5665,
    lng: float = 126.9780,
    current_stock: int | None = 5,
    name: str | None = None,
) -> RentalStation:
    return RentalStation(
        rental_id=rental_id,
        name=name or rental_id,
        lat=lat,
        lng=lng,
        rack_count=10,
        current_stock=current_stock,
        updated_at=None,
    )


TARGET = _station("TARGET")


def test_대상_자신은_후보에서_빠진다():
    other = _station("OTHER", lat=37.5670, lng=126.9780)
    index = InMemoryStationIndex([TARGET, other])

    result = generate(TARGET, index, radius_m=1000, limit=5)

    assert [c.station.rental_id for c in result] == ["OTHER"]


def test_재고가_0인_대여소는_제외된다():
    empty = _station("EMPTY", lat=37.5670, lng=126.9780, current_stock=0)
    has_stock = _station("HAS", lat=37.5675, lng=126.9780, current_stock=3)
    index = InMemoryStationIndex([TARGET, empty, has_stock])

    result = generate(TARGET, index, radius_m=1000, limit=5)

    assert [c.station.rental_id for c in result] == ["HAS"]


def test_재고를_모르는_대여소는_통과한다():
    # None은 "모른다"이지 "비었다"가 아니다 — 값 안 지어내기 원칙.
    unknown = _station("UNKNOWN", lat=37.5670, lng=126.9780, current_stock=None)
    index = InMemoryStationIndex([TARGET, unknown])

    result = generate(TARGET, index, radius_m=1000, limit=5)

    assert [c.station.rental_id for c in result] == ["UNKNOWN"]


def test_거리가_함께_담긴다():
    other = _station("OTHER", lat=37.5670, lng=126.9780)
    index = InMemoryStationIndex([TARGET, other])

    result = generate(TARGET, index, radius_m=1000, limit=5)

    assert result[0].distance_m > 0.0


def test_기본_상한은_MAX_CANDIDATES다():
    stations = [TARGET] + [
        _station(f"S{i}", lat=37.5665 + i * 0.0002, lng=126.9780, current_stock=3)
        for i in range(1, 10)
    ]
    index = InMemoryStationIndex(stations)

    result = generate(TARGET, index, radius_m=10_000)

    assert len(result) == MAX_CANDIDATES


def test_제외해도_상한을_넘지_않는다():
    # 대상 바로 다음으로 가까운 대여소가 재고 0이면, 탐색 창(limit+1)에서 대상과 함께 둘 다
    # 빠져 정확히 limit개를 못 채울 수 있다 — 그래도 넘치지는 않는다는 것이 이 테스트의 요점이다.
    zero_close = _station("EMPTY", lat=37.5666, lng=126.9780, current_stock=0)
    far_extras = [
        _station(f"S{i}", lat=37.5665 + i * 0.0010, lng=126.9780, current_stock=3)
        for i in range(1, 8)
    ]
    index = InMemoryStationIndex([TARGET, zero_close, *far_extras])

    result = generate(TARGET, index, radius_m=10_000, limit=3)

    assert len(result) <= 3
    assert "EMPTY" not in [c.station.rental_id for c in result]


def test_가까운_재고_0인_대여소가_둘이어도_상한을_채운다():
    # 재고 0인 대여소 둘이 채택될 후보들보다 대상에 더 가깝다 — limit+1(=4)짜리 탐색창이면
    # 대상·EMPTY1·EMPTY2·S1만 걸려 제외 후 1개(S1)만 남는다. limit*3+1(=10)로 넓혀야 나머지
    # S2·S3까지 걸려 상한(3)을 채운다.
    zero_close_1 = _station("EMPTY1", lat=37.5666, lng=126.9780, current_stock=0)
    zero_close_2 = _station("EMPTY2", lat=37.5667, lng=126.9780, current_stock=0)
    far_extras = [
        _station(f"S{i}", lat=37.5665 + i * 0.0005, lng=126.9780, current_stock=3)
        for i in range(1, 4)
    ]
    index = InMemoryStationIndex([TARGET, zero_close_1, zero_close_2, *far_extras])

    result = generate(TARGET, index, radius_m=10_000, limit=3)

    assert len(result) == 3
    picked_ids = [c.station.rental_id for c in result]
    assert "EMPTY1" not in picked_ids
    assert "EMPTY2" not in picked_ids


def test_대상만_있고_제외되지_않으면_상한을_그대로_채운다():
    # 대상 자신 하나만 제외되는 경우(재고 0인 대여소가 없을 때)는 상한을 정확히 채워야 한다.
    stations = [TARGET] + [
        _station(f"S{i}", lat=37.5665 + i * 0.0002, lng=126.9780, current_stock=3)
        for i in range(1, 6)
    ]
    index = InMemoryStationIndex(stations)

    result = generate(TARGET, index, radius_m=10_000, limit=3)

    assert len(result) == 3


def test_색인이_비어_있으면_빈_목록():
    index = InMemoryStationIndex([])

    assert generate(TARGET, index, radius_m=1000, limit=5) == []


def test_limit이_0이면_빈_목록():
    other = _station("OTHER", lat=37.5670, lng=126.9780)
    index = InMemoryStationIndex([TARGET, other])

    assert generate(TARGET, index, radius_m=1000, limit=0) == []


def test_반경_밖_대여소는_애초에_대상이_아니다():
    far = _station("FAR", lat=37.7000, lng=126.9780)
    index = InMemoryStationIndex([TARGET, far])

    result = generate(TARGET, index, radius_m=1000, limit=5)

    assert result == []
