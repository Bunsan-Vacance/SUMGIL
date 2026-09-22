"""따릉이 대여소 색인 검증(S15P21A104-203/302).

`haversine_m` 정확도, `nearby()`의 정렬·반경·상한, `InMemoryStationIndex`의 조회, 그리고
`ParquetStationIndex`가 `latest_stock.parquet`을 읽을 때 지켜야 하는 값 안 지어내기 원칙
(좌표 없는 행 제외, 오래된 값은 재고만 비움) · mtime 캐시를 고정한다.

실제 서빙 파일을 쓰지 않는다 — `tmp_path`에 직접 parquet을 써서 검증한다.
"""

from __future__ import annotations

import math
import os
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest

from app.TIME.station_index import (
    InMemoryStationIndex,
    ParquetStationIndex,
    RentalStation,
    haversine_m,
)

NOW = datetime(2026, 9, 22, 12, 0)


def _station(
    rental_id: str,
    lat: float,
    lng: float,
    *,
    name: str | None = None,
    current_stock: int | None = 5,
    rack_count: int | None = 10,
    updated_at: datetime | None = None,
) -> RentalStation:
    return RentalStation(
        rental_id=rental_id,
        name=name or rental_id,
        lat=lat,
        lng=lng,
        rack_count=rack_count,
        current_stock=current_stock,
        updated_at=updated_at,
    )


# ── haversine ──


def test_haversine_대략_1km_거리():
    # 위도 1도 ≈ 111.19km(구 근사, R=6371km) — 위도만 0.009도 차이나는 두 점은 약 1,000m다.
    distance = haversine_m(37.5665, 126.9780, 37.5755, 126.9780)

    assert 950.0 < distance < 1050.0


def test_haversine_같은_점은_0이다():
    assert haversine_m(37.5665, 126.9780, 37.5665, 126.9780) == pytest.approx(0.0)


def test_haversine_대칭이다():
    a = haversine_m(37.5665, 126.9780, 37.6000, 127.0000)
    b = haversine_m(37.6000, 127.0000, 37.5665, 126.9780)

    assert a == pytest.approx(b)


# ── InMemoryStationIndex.nearby ──


def test_nearby는_거리_오름차순으로_정렬된다():
    near = _station("A", 37.5670, 126.9780)
    mid = _station("B", 37.5700, 126.9780)
    far = _station("C", 37.6000, 126.9780)
    index = InMemoryStationIndex([far, near, mid])

    result = index.nearby(37.5665, 126.9780, radius_m=10_000, limit=10)

    assert [s.rental_id for s, _ in result] == ["A", "B", "C"]
    distances = [d for _, d in result]
    assert distances == sorted(distances)


def test_nearby는_반경_밖을_제외한다():
    near = _station("A", 37.5670, 126.9780)
    far = _station("B", 37.7000, 126.9780)
    index = InMemoryStationIndex([near, far])

    result = index.nearby(37.5665, 126.9780, radius_m=1_000, limit=10)

    assert [s.rental_id for s, _ in result] == ["A"]


def test_nearby는_상한을_지킨다():
    stations = [_station(f"S{i}", 37.5665 + i * 0.0002, 126.9780) for i in range(10)]
    index = InMemoryStationIndex(stations)

    result = index.nearby(37.5665, 126.9780, radius_m=10_000, limit=3)

    assert len(result) == 3


def test_nearby_limit이_0이면_빈_목록():
    index = InMemoryStationIndex([_station("A", 37.5665, 126.9780)])

    assert index.nearby(37.5665, 126.9780, radius_m=1000, limit=0) == []


# ── InMemoryStationIndex.get ──


def test_get은_rental_id로_찾는다():
    station = _station("A", 37.5665, 126.9780)
    index = InMemoryStationIndex([station])

    assert index.get("A") is station
    assert index.get("NOPE") is None


# ── ParquetStationIndex ──


def _write(tmp_path: Path, rows: list[dict]) -> Path:
    path = tmp_path / "latest_stock.parquet"
    pd.DataFrame(rows).to_parquet(path, index=False)
    return path


def _row(rental_id: str, **overrides) -> dict:
    row = {
        "rental_id": rental_id,
        "current_stock": 5,
        "updated_at": NOW,
        "station_name": f"{rental_id}역",
        "lat": 37.5665,
        "lng": 126.9780,
        "rack_count": 10,
    }
    row.update(overrides)
    return row


def test_파일이_없으면_빈_색인이다(tmp_path: Path):
    index = ParquetStationIndex(tmp_path / "missing.parquet")

    assert index.get("A", now=NOW) is None
    assert index.nearby(37.5665, 126.9780, radius_m=1000, limit=5, now=NOW) == []


def test_좌표가_없는_행은_제외된다(tmp_path: Path):
    path = _write(
        tmp_path,
        [
            _row("A", lat=37.5665, lng=126.9780),
            _row("B", lat=math.nan, lng=126.9790),
            _row("C", lat=37.5670, lng=math.nan),
        ],
    )
    index = ParquetStationIndex(path, max_staleness_seconds=300.0)

    assert index.get("A", now=NOW) is not None
    assert index.get("B", now=NOW) is None
    assert index.get("C", now=NOW) is None


def test_오래된_updated_at은_재고를_모른다로_비운다(tmp_path: Path):
    stale = NOW - timedelta(seconds=400)
    path = _write(tmp_path, [_row("A", current_stock=7, updated_at=stale)])
    index = ParquetStationIndex(path, max_staleness_seconds=300.0)

    station = index.get("A", now=NOW)

    assert station is not None
    assert station.current_stock is None  # 0이 아니라 "모른다"
    assert station.lat == pytest.approx(37.5665)  # 대여소 자체는 빠지지 않는다


def test_신선한_updated_at은_재고를_그대로_쓴다(tmp_path: Path):
    fresh = NOW - timedelta(seconds=100)
    path = _write(tmp_path, [_row("A", current_stock=7, updated_at=fresh)])
    index = ParquetStationIndex(path, max_staleness_seconds=300.0)

    station = index.get("A", now=NOW)

    assert station is not None
    assert station.current_stock == 7


def test_신선도_경계값은_아직_신선하다(tmp_path: Path):
    boundary = NOW - timedelta(seconds=300)
    path = _write(tmp_path, [_row("A", current_stock=7, updated_at=boundary)])
    index = ParquetStationIndex(path, max_staleness_seconds=300.0)

    station = index.get("A", now=NOW)

    assert station is not None
    assert station.current_stock == 7  # 경계값(같음)은 아직 넘지 않은 것으로 본다


def test_레거시_3컬럼_파일은_좌표_컬럼이_없어_빈_색인이다(tmp_path: Path):
    path = tmp_path / "latest_stock.parquet"
    pd.DataFrame([{"rental_id": "A", "current_stock": 5, "updated_at": NOW}]).to_parquet(
        path, index=False
    )
    index = ParquetStationIndex(path)

    assert index.get("A", now=NOW) is None
    assert index.nearby(37.5665, 126.9780, radius_m=10_000, limit=10, now=NOW) == []


def test_nearby가_거리순으로_반환한다(tmp_path: Path):
    path = _write(
        tmp_path,
        [
            _row("FAR", lat=37.6000, lng=126.9780),
            _row("NEAR", lat=37.5670, lng=126.9780),
        ],
    )
    index = ParquetStationIndex(path)

    result = index.nearby(37.5665, 126.9780, radius_m=10_000, limit=10, now=NOW)

    assert [s.rental_id for s, _ in result] == ["NEAR", "FAR"]


def test_파일이_바뀌면_다시_읽는다(tmp_path: Path):
    path = _write(tmp_path, [_row("A")])
    index = ParquetStationIndex(path, max_staleness_seconds=300.0)
    assert index.get("A", now=NOW) is not None
    assert index.get("B", now=NOW) is None

    # 같은 경로에 새 내용을 쓰고 mtime을 강제로 앞당긴다 — 파일시스템 타임스탬프 해상도가
    # 낮은 환경에서도 캐시 무효화가 확실히 일어나게 하려는 것이다.
    pd.DataFrame([_row("B")]).to_parquet(path, index=False)
    new_mtime = path.stat().st_mtime + 5.0
    os.utime(path, (new_mtime, new_mtime))

    assert index.get("A", now=NOW) is None
    assert index.get("B", now=NOW) is not None


def test_같은_mtime이면_다시_읽지_않는다(tmp_path: Path, monkeypatch):
    path = _write(tmp_path, [_row("A")])
    index = ParquetStationIndex(path, max_staleness_seconds=300.0)
    index.get("A", now=NOW)  # 최초 로딩으로 캐시를 채운다

    calls = []
    original_read_parquet = pd.read_parquet

    def _counting_read_parquet(*args, **kwargs):
        calls.append(1)
        return original_read_parquet(*args, **kwargs)

    monkeypatch.setattr(pd, "read_parquet", _counting_read_parquet)

    index.get("A", now=NOW)
    index.nearby(37.5665, 126.9780, radius_m=1000, limit=5, now=NOW)

    assert calls == []  # mtime이 안 바뀌었으니 다시 읽지 않는다
