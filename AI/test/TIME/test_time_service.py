"""재안내 판정 진입점 검증(S15P21A104-302).

여기서 고정하려는 것은 넷이다.

1. **단계별 실패 매핑이 안 섞인다** — `service.py` 모듈 docstring의 표(target_unknown·
   stock_unknown·no_nearby_station·all_candidates_failed·no_strategy·strategy_undecided·
   boundary_missing·route_unavailable·route_malformed) 하나하나가 제 상태·사유로 나온다.
2. **안 부르는 것** — 트리거가 안 서면 후보·경로를 조회하지 않는다. 대안 선택이 끝나기 전에는
   `replan_route`(BE 비용)를 부르지 않는다.
3. **⑥ 경로 연결·도보 합성** — `replan_route`가 준 원소의 안쪽 `route`만 싣고, 실패(빈 배열·
   `ToolError`·`route` 없음)는 전부 `unavailable`이다(`route: null` 제안 금지). `walkLeg`는
   GeoJSON `[lng, lat]` 순서와 `estimated` 표시를 지킨다.
4. **예외가 새지 않는다. `force_trigger`도 `stock_unknown`은 못 건너뛴다** — 어느 단계가
   터져도 `unavailable`(`internal_error`)이지 500이 아니고, 강제 트리거는 임계값만 건너뛸 뿐
   조회 실패까지 덮어쓰지 않는다.

실제 네트워크·parquet·LLM을 쓰지 않는다(`test_time_planner.py`와 같은 방침). `RuleStrategy`
(`app.TIME.strategy`)를 기본 전략으로 쓴다 — 점수식 자체는 `test_time_strategy.py`가 이미
고정했으므로 여기서는 "어떤 후보가 골렸는지"만 확인하면 되게, 성공 경로의 고정 픽스처는 항상
후보 하나만 조회 가능하게(usable) 만든다.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest

from app.TIME.guard import ToolGuard
from app.TIME.registry import GET_ETA_STOCK, REPLAN_ROUTE
from app.TIME.schemas import ToolError
from app.TIME.service import (
    REASON_ALL_CANDIDATES_FAILED,
    REASON_BOUNDARY_MISSING,
    REASON_INTERNAL_ERROR,
    REASON_NO_NEARBY_STATION,
    REASON_NO_STRATEGY,
    REASON_ROUTE_MALFORMED,
    REASON_ROUTE_UNAVAILABLE,
    REASON_STRATEGY_UNDECIDED,
    REASON_TARGET_UNKNOWN,
    WALK_DETOUR_FACTOR,
    Boundary,
    RerouteStatus,
    build_walk_leg,
    propose_reroute,
)
from app.TIME.station_index import (
    WALK_SPEED_M_PER_MIN,
    InMemoryStationIndex,
    RentalStation,
    haversine_m,
)
from app.TIME.strategy import RuleStrategy
from app.TIME.trigger import (
    REASON_BELOW_THRESHOLD,
    REASON_COOLDOWN,
    REASON_FORCED,
    REASON_HORIZON_OUT_OF_RANGE,
    REASON_STOCK_UNKNOWN,
)

TARGET_ID = "TARGET"
ALT_A_ID = "ALT-A"
ALT_B_ID = "ALT-B"
DEST_ID = "DEST-1"

BOUNDARY = Boundary(leg_index=1, node_id="ND-221", lat=37.5665, lng=126.9780)


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


TARGET_STATION = _station(TARGET_ID, name="역삼")
ALT_A_STATION = _station(ALT_A_ID, lat=37.5666, lng=126.9780, name="교대")  # 대상에서 ~11m
ALT_B_STATION = _station(ALT_B_ID, lat=37.5700, lng=126.9780, name="강남")  # 대상에서 ~390m


def _index(*extra: RentalStation) -> InMemoryStationIndex:
    return InMemoryStationIndex([TARGET_STATION, *extra])


DEFAULT_INDEX = _index(ALT_A_STATION, ALT_B_STATION)


def _eta(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "rental_id": "X",
        "eta_minutes": 10,
        "current_stock": 3,
        "predicted_stock": 5.0,
        "p_empty": 0.1,
        "p_full": 0.0,
        "source": "lightgbm",
        "model_horizon_min": 10,
    }
    body.update(overrides)
    return body


FIRED_TARGET = _eta(current_stock=0, predicted_stock=0.3, p_empty=0.9)
"""p_empty 0.9 ≥ 기본 임계(0.7) — 트리거가 선다."""

BELOW_THRESHOLD_TARGET = _eta(current_stock=3, predicted_stock=5.0, p_empty=0.3)
"""p_empty·predicted_stock 둘 다 여유 — 트리거가 안 선다."""

GOOD_ALT = _eta(current_stock=4, predicted_stock=4.0, p_empty=0.1)
"""대안 후보의 조회 결과 — 재고 여유, 비어 있을 확률 낮음."""


def _route_element(**route_overrides: Any) -> dict[str, Any]:
    """BE `replan_route` 응답 원소 하나. 기본 `route`는 데모 예시(FE-04 편지 2.3절)를 옮겼다."""
    route: dict[str, Any] = {
        "routeType": "BIKE_SUBWAY",
        "totalMinutes": 20.0,
        "source": "ALGORITHM",
        "totalDistanceMeters": 6000.0,
        "transferCount": 0,
        "legs": [{"mode": "BIKE", "minutes": 20.0, "routeId": None}],
    }
    route.update(route_overrides)
    return {"reason": "BE 고정 문구", "source": "ALGORITHM", "route": route}


# ── 가짜 어댑터 ──


class FakeAdapter:
    """`get_eta_stock`은 `rental_id`별 미리 정한 응답을, `replan_route`는 고정된 응답을 낸다.

    `replan=None`(기본)이면 성공 원소 하나를 돌려준다 — 대부분의 테스트가 ⑥까지 통과하는 것을
    전제로 하고, ⑥ 자체를 검증하는 테스트만 `replan`을 명시로 덮어쓴다.
    """

    def __init__(self, *, eta_stock: Mapping[str, Any] | None = None, replan: Any = None) -> None:
        self.eta_stock = dict(eta_stock or {})
        self.replan = [_route_element()] if replan is None else replan
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def call(self, name: str, args: Mapping[str, Any]) -> Any:
        self.calls.append((name, dict(args)))
        if name == GET_ETA_STOCK:
            rental_id = str(args["rental_id"])
            if rental_id not in self.eta_stock:
                return ToolError.not_found(f"{rental_id} 실시간 재고를 확인할 수 없다")
            return self.eta_stock[rental_id]
        if name == REPLAN_ROUTE:
            return self.replan
        return ToolError.invalid_input(f"가짜 어댑터가 모르는 도구 '{name}'")

    def count(self, name: str) -> int:
        return sum(1 for called, _ in self.calls if called == name)

    def replan_calls(self) -> list[dict[str, Any]]:
        return [args for name, args in self.calls if name == REPLAN_ROUTE]


def run(adapter: FakeAdapter, **kwargs: Any):
    """`propose_reroute` 호출 도우미. 자주 바뀌지 않는 인자는 기본값을 깔아준다."""
    return propose_reroute(
        rental_id=kwargs.pop("rental_id", TARGET_ID),
        eta_to_rental_minutes=kwargs.pop("eta", 10),
        step=kwargs.pop("step", 0),
        dest_station_id=DEST_ID,
        boundary=kwargs.pop("boundary") if "boundary" in kwargs else BOUNDARY,
        adapter=adapter,
        guard=kwargs.pop("guard", None) or ToolGuard(),
        strategy=kwargs.pop("strategy") if "strategy" in kwargs else RuleStrategy(),
        station_index=kwargs.pop("index", None) or DEFAULT_INDEX,
        **kwargs,
    )


# ── ① 대상 조회 ──


def test_대상_대여소가_색인에_없으면_target_unknown이다():
    adapter = FakeAdapter()

    outcome = run(adapter, rental_id="NOPE")

    assert outcome.status is RerouteStatus.UNAVAILABLE
    assert outcome.reason == REASON_TARGET_UNKNOWN
    assert outcome.target is None
    assert adapter.calls == []  # 좌표를 모르면 재고 조회조차 하지 않는다


# ── ③ 트리거 ──


def test_재고_조회가_실패하면_stock_unknown_unavailable이다():
    adapter = FakeAdapter(eta_stock={})  # TARGET 응답 없음 → ToolError

    outcome = run(adapter)

    assert outcome.status is RerouteStatus.UNAVAILABLE
    assert outcome.reason == REASON_STOCK_UNKNOWN
    assert outcome.target is not None
    assert outcome.target_reading is None
    assert adapter.count(REPLAN_ROUTE) == 0


def test_임계_미달이면_no_trigger다():
    adapter = FakeAdapter(eta_stock={TARGET_ID: BELOW_THRESHOLD_TARGET})

    outcome = run(adapter)

    assert outcome.status is RerouteStatus.NO_TRIGGER
    assert outcome.reason == REASON_BELOW_THRESHOLD
    assert outcome.target_reading is not None
    assert adapter.count(GET_ETA_STOCK) == 1  # 후보 조회로 번지지 않는다
    assert adapter.count(REPLAN_ROUTE) == 0


def test_쿨다운_중이면_no_trigger다():
    # 고갈 조건(p_empty 0.9)은 충족해도 쿨다운이 먼저 막는다.
    adapter = FakeAdapter(eta_stock={TARGET_ID: FIRED_TARGET})

    outcome = run(adapter, seconds_since_last_fire=10.0)

    assert outcome.status is RerouteStatus.NO_TRIGGER
    assert outcome.reason == REASON_COOLDOWN


def test_ETA가_horizon_밖이면_no_trigger다():
    adapter = FakeAdapter(eta_stock={TARGET_ID: FIRED_TARGET})

    outcome = run(adapter, eta=40)

    assert outcome.status is RerouteStatus.NO_TRIGGER
    assert outcome.reason == REASON_HORIZON_OUT_OF_RANGE


# ── ④ 후보 생성 ──


def test_주변에_대여소가_없으면_no_alternative다():
    adapter = FakeAdapter(eta_stock={TARGET_ID: FIRED_TARGET})

    outcome = run(adapter, index=_index())  # 대상 혼자뿐인 색인

    assert outcome.status is RerouteStatus.NO_ALTERNATIVE
    assert outcome.reason == REASON_NO_NEARBY_STATION
    assert adapter.count(REPLAN_ROUTE) == 0


# ── ⑤ 프리페치·선택 ──


def test_후보_조회가_전부_실패하면_unavailable이다():
    adapter = FakeAdapter(eta_stock={TARGET_ID: FIRED_TARGET})  # ALT 응답이 전혀 없다

    outcome = run(adapter)

    assert outcome.status is RerouteStatus.UNAVAILABLE
    assert outcome.reason == REASON_ALL_CANDIDATES_FAILED
    assert adapter.count(REPLAN_ROUTE) == 0


def test_일부_후보만_실패해도_추천은_나온다():
    # ALT_B는 조회에 없어 실패로 남지만, ALT_A가 살아있어 추천이 나온다.
    adapter = FakeAdapter(eta_stock={TARGET_ID: FIRED_TARGET, ALT_A_ID: GOOD_ALT})

    outcome = run(adapter)

    assert outcome.status is RerouteStatus.PROPOSAL
    assert outcome.alternative is not None
    assert outcome.alternative.candidate.station.rental_id == ALT_A_ID


def test_전략이_없으면_no_strategy_unavailable이다():
    adapter = FakeAdapter(eta_stock={TARGET_ID: FIRED_TARGET, ALT_A_ID: GOOD_ALT})

    outcome = run(adapter, strategy=None)

    assert outcome.status is RerouteStatus.UNAVAILABLE
    assert outcome.reason == REASON_NO_STRATEGY
    assert adapter.count(REPLAN_ROUTE) == 0


class _NoneStrategy:
    """대안이 있어도 하나도 못 고르는 전략 — "대안 없음"과 뭉개지지 않는지 확인한다."""

    def decide(self, ctx: Any) -> None:
        return None


def test_전략이_고르지_못하면_strategy_undecided_unavailable이다():
    adapter = FakeAdapter(eta_stock={TARGET_ID: FIRED_TARGET, ALT_A_ID: GOOD_ALT})

    outcome = run(adapter, strategy=_NoneStrategy())

    assert outcome.status is RerouteStatus.UNAVAILABLE
    assert outcome.reason == REASON_STRATEGY_UNDECIDED
    assert adapter.count(REPLAN_ROUTE) == 0


# ── ⑥ 경로 연결·도보 합성 ──


def test_경계가_없으면_boundary_missing_unavailable이다():
    adapter = FakeAdapter(eta_stock={TARGET_ID: FIRED_TARGET, ALT_A_ID: GOOD_ALT})

    outcome = run(adapter, boundary=None)

    assert outcome.status is RerouteStatus.UNAVAILABLE
    assert outcome.reason == REASON_BOUNDARY_MISSING
    assert outcome.proposal is not None  # 대안까지는 골랐다 — 경로만 못 이었다
    assert outcome.alternative is not None
    assert adapter.count(REPLAN_ROUTE) == 0


def test_경로_재탐색이_실패하면_route_unavailable이다():
    adapter = FakeAdapter(
        eta_stock={TARGET_ID: FIRED_TARGET, ALT_A_ID: GOOD_ALT},
        replan=ToolError.upstream_unavailable("BE 미기동"),
    )

    outcome = run(adapter)

    assert outcome.status is RerouteStatus.UNAVAILABLE
    assert outcome.reason == REASON_ROUTE_UNAVAILABLE
    assert outcome.boundary == BOUNDARY


def test_경로_재탐색이_빈_배열이면_route_unavailable이다():
    # BE 계약상 빈 배열은 오류가 아니다 — 그래도 route:null 제안은 금지라 unavailable로 묶는다.
    adapter = FakeAdapter(eta_stock={TARGET_ID: FIRED_TARGET, ALT_A_ID: GOOD_ALT}, replan=[])

    outcome = run(adapter)

    assert outcome.status is RerouteStatus.UNAVAILABLE
    assert outcome.reason == REASON_ROUTE_UNAVAILABLE


def test_원소에_route가_없으면_route_malformed이다():
    adapter = FakeAdapter(
        eta_stock={TARGET_ID: FIRED_TARGET, ALT_A_ID: GOOD_ALT},
        replan=[{"reason": "BE 고정 문구", "source": "ALGORITHM"}],  # route 키 없음
    )

    outcome = run(adapter)

    assert outcome.status is RerouteStatus.UNAVAILABLE
    assert outcome.reason == REASON_ROUTE_MALFORMED


def test_성공하면_proposal이고_필요한_필드가_다_채워진다():
    inner_route = {
        "routeType": "BIKE_SUBWAY",
        "totalMinutes": 21.5,
        "source": "ALGORITHM",
        "totalDistanceMeters": 6120.0,
        "transferCount": 1,
        "legs": [{"mode": "BIKE", "minutes": 8.0, "routeId": None}],
    }
    adapter = FakeAdapter(
        eta_stock={TARGET_ID: FIRED_TARGET, ALT_A_ID: GOOD_ALT},
        replan=[_route_element(**inner_route)],
    )

    outcome = run(adapter)

    assert outcome.status is RerouteStatus.PROPOSAL
    assert outcome.reason == outcome.proposal.reason  # 사용자 문장 = proposal.reason
    assert outcome.target is TARGET_STATION
    assert outcome.alternative is not None
    assert outcome.alternative.candidate.station.rental_id == ALT_A_ID
    assert outcome.boundary == BOUNDARY  # 요청받은 경계를 그대로 에코
    assert outcome.route == inner_route  # 바깥 reason·source는 버리고 안쪽 route만

    walk_leg = outcome.walk_leg
    assert walk_leg is not None
    assert walk_leg["mode"] == "WALK"
    assert walk_leg["fromNodeId"] == BOUNDARY.node_id
    assert walk_leg["fromNodeName"] is None
    assert walk_leg["toNodeId"] == ALT_A_ID
    assert walk_leg["toNodeName"] == ALT_A_STATION.name
    assert walk_leg["routeId"] is None
    assert walk_leg["routeName"] is None
    assert walk_leg["geometryStatus"] == "estimated"
    assert walk_leg["estimated"] is True
    coords = walk_leg["geometry"]["coordinates"][0]
    assert coords[0] == [BOUNDARY.lng, BOUNDARY.lat]  # GeoJSON [lng, lat] 순서
    assert coords[1] == [ALT_A_STATION.lng, ALT_A_STATION.lat]


def test_build_walk_leg_거리와_소요시간은_보정된_같은_값에서_나온다():
    boundary = Boundary(leg_index=1, node_id="221", lat=37.500658, lng=127.03643)
    station = _station("ST-1290", lat=37.49, lng=127.03, name="역삼로")

    leg = build_walk_leg(boundary, station)

    straight_m = haversine_m(boundary.lat, boundary.lng, station.lat, station.lng)
    walk_m = straight_m * WALK_DETOUR_FACTOR
    assert leg["distanceMeters"] == round(walk_m)
    assert leg["minutes"] == pytest.approx(round(walk_m / WALK_SPEED_M_PER_MIN, 1))
    assert leg["geometry"] == {
        "type": "MultiLineString",
        "coordinates": [[[boundary.lng, boundary.lat], [station.lng, station.lat]]],
    }


# ── force_trigger — 임계값은 건너뛰어도 조회 실패는 못 건너뛴다 ──


def test_force_trigger는_임계_미달을_건너뛴다():
    adapter = FakeAdapter(eta_stock={TARGET_ID: BELOW_THRESHOLD_TARGET, ALT_A_ID: GOOD_ALT})

    outcome = run(adapter, force_trigger=True)

    assert outcome.status is RerouteStatus.PROPOSAL
    assert outcome.trigger is not None
    assert outcome.trigger.reason == REASON_FORCED


def test_force_trigger여도_재고를_모르면_stock_unknown이다():
    adapter = FakeAdapter(eta_stock={})  # TARGET 조회 자체가 실패

    outcome = run(adapter, force_trigger=True)

    assert outcome.status is RerouteStatus.UNAVAILABLE
    assert outcome.reason == REASON_STOCK_UNKNOWN


# ── replan 호출 모양 ──


def test_replan은_선택된_대안의_rental_id로_한_번만_불린다():
    adapter = FakeAdapter(eta_stock={TARGET_ID: FIRED_TARGET, ALT_A_ID: GOOD_ALT})

    outcome = run(adapter, step=3)

    assert outcome.status is RerouteStatus.PROPOSAL
    assert adapter.count(REPLAN_ROUTE) == 1
    assert adapter.replan_calls() == [
        {"step": 3, "boundary_id": ALT_A_ID, "dest_station_id": DEST_ID}
    ]


# ── 예외가 새지 않는다 ──


class _ExplodingStrategy:
    def decide(self, ctx: Any) -> None:
        raise RuntimeError("전략 내부 버그")


def test_전략이_터져도_예외가_새지_않는다():
    adapter = FakeAdapter(eta_stock={TARGET_ID: FIRED_TARGET, ALT_A_ID: GOOD_ALT})

    outcome = run(adapter, strategy=_ExplodingStrategy())

    assert outcome.status is RerouteStatus.UNAVAILABLE
    assert outcome.reason == REASON_INTERNAL_ERROR


class _ExplodingAdapter(FakeAdapter):
    def call(self, name: str, args: Mapping[str, Any]) -> Any:
        raise ValueError("어댑터 내부 버그")


def test_어댑터가_터져도_예외가_새지_않는다():
    outcome = run(_ExplodingAdapter())

    assert outcome.status is RerouteStatus.UNAVAILABLE
    assert outcome.reason == REASON_INTERNAL_ERROR
    assert outcome.proposal is None
