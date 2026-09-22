"""따릉이 대여소 색인 — 주변 대여소 탐색(S15P21A104-203/302).

**왜 BE `bike_stations_nearby` 대신 로컬 색인인가.** 재고 고갈 판정(`trigger.py`)과 대안 탐색이
같은 원천을 봐야 한다 — 판정에 쓰는 `get_eta_stock`은 `latest_stock.parquet`(Kafka `bike.stock`
컨슈머가 station별 upsert로 유지하는 최신 스냅샷)을 근거로 하는데, BE `bike_stations_nearby`
DTO에는 판정에 쓸 필드가 없다(`availableBikes`는 **지금** 재고일 뿐 도착 시점 예측·`p_empty`가
없다 — 계획 v2 1절). 이름·좌표·거치대 수가 이미 같은 Kafka 페이로드에 실려 있어
(`DATA_ENGINE/stream/kafka_sink.py`의 `BIKE_LATEST_STOCK_COLUMNS`), 같은 표에서 거리까지 재면
판정과 후보 생성이 한 원천으로 통일된다 — 두 원천을 쓰면 "이 대여소가 후보로는 보이는데 재고
조회는 안 된다" 같은 어긋남이 생긴다.

**mtime 캐시는 `app.BIKE.service.LiveStockStore`와 동일한 방식**이다. 컨슈머와 서빙 앱이
파일시스템을 공유한다는 같은 전제 위에서 동작한다.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol
from zoneinfo import ZoneInfo

import pandas as pd

# `app.TIME.adapters.KST`와 같은 값이지만, 그쪽과 같은 이유로 상수 하나 때문에
# `app.BIKE.pipeline.calendar`(무거운 의존성 물릴 위험)를 끌어오지 않고 직접 정의한다.
KST = ZoneInfo("Asia/Seoul")

_EARTH_RADIUS_M = 6_371_000.0

DEFAULT_MAX_STALENESS_SECONDS = 300.0
"""`app.core.config.Settings.bike_live_stock_max_staleness_seconds`와 같은 기본값 — 같은 원천
(`latest_stock.parquet`)의 신선도 기준이라 서로 다를 이유가 없다."""

WALK_SPEED_M_PER_MIN = 67.0
"""도보 속도(분당 미터). **잠정값**(계획 2.5절) — 실측 없이 우선 박아둔 값이다. 이 모듈에
정의하는 이유는 두 자리가 같은 값을 써야 하기 때문이다 — `strategy.ScoreWeights`(후보 사이
상대 순위 근사)와 `service.build_walk_leg`(하차역→대안 실제 도보 소요 합성). 순위 계산에 쓴
속도와 사용자에게 보여줄 분 단위가 어긋나면 안 되므로, 상수를 여기 하나만 두고 양쪽에서
import한다(순환 import를 피하는 가장 단순한 자리 — `station_index`는 `strategy`·`service`
어느 쪽도 참조하지 않는다)."""


def haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """두 좌표 사이의 대권 거리(미터).

    지구를 구로 근사한다 — 보행 반경(수백 m) 수준에서 타원체 보정 오차는 무시할 만하다.
    """
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lng2 - lng1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return _EARTH_RADIUS_M * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


@dataclass(frozen=True)
class RentalStation:
    """대여소 하나의 정적·준정적 속성.

    `current_stock`·`updated_at`은 이 색인이 **로딩 시점**에 읽은 값이라 호출 사이에 갱신되지
    않는다 — 트리거·프리페치가 쓰는 최신 재고는 `get_eta_stock`을 따로 불러 얻는다. 이 값은
    "이 대여소가 후보로 쓸 만한지"를 거르는 용도(`candidates.generate`의 0대 제외)다.
    """

    rental_id: str
    name: str | None
    lat: float
    lng: float
    rack_count: int | None
    current_stock: int | None
    updated_at: datetime | None


class StationIndex(Protocol):
    """대여소 하나를 찾거나(`get`) 주변을 훑는다(`nearby`).

    `InMemoryStationIndex`(테스트·조립 단위)와 `ParquetStationIndex`(운영)가 같은 인터페이스를
    구현한다 — `candidates.generate`는 어느 구현인지 모른 채 이 프로토콜만 본다.
    """

    def get(self, rental_id: str) -> RentalStation | None: ...

    def nearby(
        self, lat: float, lng: float, radius_m: float, limit: int
    ) -> list[tuple[RentalStation, float]]:
        """반경 안 대여소를 거리(m) 오름차순으로.

        거리·상한 말고는 아무것도 거르지 않는다 — 자기 자신 제외·재고 0 제외는 호출자
        (`candidates.generate`)의 몫이다. 값을 지어내지 않는 것도 구현의 몫이라, 좌표를 모르는
        대여소는 애초에 색인에 들어오지 않는다.
        """
        ...


class InMemoryStationIndex:
    """고정된 대여소 목록으로 만든 색인.

    테스트가 직접 주입하는 용도이자, `ParquetStationIndex`가 매 조회마다 조립하는 내부 단위다.
    """

    def __init__(self, stations: Iterable[RentalStation]) -> None:
        self._by_id: dict[str, RentalStation] = {s.rental_id: s for s in stations}

    def get(self, rental_id: str) -> RentalStation | None:
        return self._by_id.get(rental_id)

    def nearby(
        self, lat: float, lng: float, radius_m: float, limit: int
    ) -> list[tuple[RentalStation, float]]:
        if limit <= 0:
            return []
        pairs = [
            (station, haversine_m(lat, lng, station.lat, station.lng))
            for station in self._by_id.values()
        ]
        pairs = [pair for pair in pairs if pair[1] <= radius_m]
        pairs.sort(key=lambda pair: pair[1])
        return pairs[:limit]


class ParquetStationIndex:
    """`latest_stock.parquet`(Kafka `bike.stock` 최신 스냅샷)을 읽어 주변 대여소를 찾는다.

    `app.BIKE.service.LiveStockStore`와 동일한 mtime 캐시 방식이다 — 파일이 안 바뀌었으면
    다시 읽지 않는다. 컬럼은 `DATA_ENGINE/stream/kafka_sink.py`의 `BIKE_LATEST_STOCK_COLUMNS`
    (rental_id·current_stock·updated_at·station_name·lat·lng·rack_count)와 같다.

    **좌표가 없는 행은 색인에서 아예 뺀다** — 위치를 추측해 넣지 않는다(값 안 지어내기 원칙).
    `lat`/`lng` 컬럼 자체가 없는 옛 스냅샷(레거시 3컬럼 파일)도 같은 규칙으로 빈 색인이 된다.

    **오래된 값은 대여소를 빼지 않고 `current_stock`만 `None`으로 비운다** — 대여소째 빼면
    실제로 존재하는 대여소가 "없다"고 오인된다. `None`은 "모른다"이지 "0대(비었다)"가 아니라서
    `candidates.generate`의 0대 제외 필터를 통과한다(그 자리에서 다시 값을 지어내지 않는다).

    신선도 판정 시각(`now`)은 `load()` 시점이 아니라 `get`/`nearby` 호출마다 받는다 — mtime
    캐시는 **원본 parquet 프레임만** 캐시하고 신선도는 매번 다시 계산한다. 파일이 그대로인 채
    시간만 흘러도(실제 서빙 상황이 그렇다) 오래된 값이 갱신되게 하려는 것이다. 테스트는 `now`를
    고정 시각으로 주입해 경계값을 검증한다.
    """

    def __init__(
        self, path: Path, max_staleness_seconds: float = DEFAULT_MAX_STALENESS_SECONDS
    ) -> None:
        self.path = Path(path)
        self.max_staleness_seconds = max_staleness_seconds
        self._cache: tuple[float, pd.DataFrame] | None = None

    def _frame(self) -> pd.DataFrame | None:
        if not self.path.exists():
            return None
        mtime = self.path.stat().st_mtime
        if self._cache is not None and self._cache[0] == mtime:
            return self._cache[1]
        frame = pd.read_parquet(self.path)
        self._cache = (mtime, frame)
        return frame

    def _index(self, *, now: datetime | None) -> InMemoryStationIndex:
        frame = self._frame()
        if frame is None:
            return InMemoryStationIndex([])
        moment = now if now is not None else _now_kst()
        stations = _stations_from_frame(
            frame, now=moment, max_staleness_seconds=self.max_staleness_seconds
        )
        return InMemoryStationIndex(stations)

    def get(self, rental_id: str, *, now: datetime | None = None) -> RentalStation | None:
        return self._index(now=now).get(rental_id)

    def nearby(
        self,
        lat: float,
        lng: float,
        radius_m: float,
        limit: int,
        *,
        now: datetime | None = None,
    ) -> list[tuple[RentalStation, float]]:
        return self._index(now=now).nearby(lat, lng, radius_m, limit)


def _now_kst() -> datetime:
    """`app.BIKE.pipeline.calendar.now_kst()`와 같은 값을 낸다(서버 OS 시간대가 UTC라도 KST
    기준 naive datetime). 그 함수를 직접 부르지 않는 이유는 모듈 docstring의 `KST` 주석과 같다."""
    return datetime.now(KST).replace(tzinfo=None)


def _stations_from_frame(
    frame: pd.DataFrame, *, now: datetime, max_staleness_seconds: float
) -> list[RentalStation]:
    if "lat" not in frame.columns or "lng" not in frame.columns:
        return []  # 좌표 컬럼 자체가 없는 레거시 스냅샷 — 전부 제외한다

    stations: list[RentalStation] = []
    for row in frame.to_dict("records"):
        lat = _optional_float(row.get("lat"))
        lng = _optional_float(row.get("lng"))
        if lat is None or lng is None:
            continue  # 좌표 없는 대여소는 추측해 넣지 않고 제외한다

        rental_id = _optional_str(row.get("rental_id"))
        if rental_id is None:
            continue

        updated_at = _optional_datetime(row.get("updated_at"))
        current_stock = _optional_int(row.get("current_stock"))
        if updated_at is not None:
            age_seconds = (now - updated_at).total_seconds()
            if age_seconds > max_staleness_seconds:
                current_stock = None  # 오래된 값은 "모른다" — 0대가 아니다

        stations.append(
            RentalStation(
                rental_id=rental_id,
                name=_optional_str(row.get("station_name")),
                lat=lat,
                lng=lng,
                rack_count=_optional_int(row.get("rack_count")),
                current_stock=current_stock,
                updated_at=updated_at,
            )
        )
    return stations


def _optional_float(value: Any) -> float | None:
    """숫자로 못 읽거나 결측(None/NaN)이면 0이 아니라 `None`이다."""
    if value is None or pd.isna(value):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _optional_int(value: Any) -> int | None:
    if value is None or pd.isna(value):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _optional_str(value: Any) -> str | None:
    if value is None or pd.isna(value):
        return None
    text = str(value).strip()
    return text or None


def _optional_datetime(value: Any) -> datetime | None:
    if value is None or pd.isna(value):
        return None
    py_dt = pd.Timestamp(value).to_pydatetime()
    if py_dt.tzinfo is not None:
        # 컨슈머(`kafka_sink._naive_kst`)는 naive KST로 저장하지만, 다른 경로로 만들어진
        # parquet이 tz-aware일 수 있어 방어적으로 KST naive로 맞춘다.
        py_dt = py_dt.astimezone(KST).replace(tzinfo=None)
    return py_dt


__all__ = [
    "DEFAULT_MAX_STALENESS_SECONDS",
    "WALK_SPEED_M_PER_MIN",
    "InMemoryStationIndex",
    "ParquetStationIndex",
    "RentalStation",
    "StationIndex",
    "haversine_m",
]
