"""재안내 API 요청/응답 모델 검증(S15P21A104-302).

여기서 고정하려는 것은 셋이다.

1. `from_outcome`이 `PROPOSAL`을 camelCase 필드로 옮기고, `walkLeg`·`route`는 손대지 않고
   그대로 통과시킨다(`api_schemas.py` 모듈 docstring — "BE DTO 원문").
2. `PROPOSAL`이 아닌 상태는 `status`(+`reason`) 외의 필드가 전부 `None`이다 — `RerouteOutcome`에
   부산물(`boundary`·`alternative` 등)이 남아 있어도 FE에 흘리지 않는다.
3. `RerouteCheckRequest`는 camelCase JSON을 그대로 파싱하고, `boundary`는 생략 가능하다.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from app.TIME.api_schemas import BoundaryIn, RerouteCheckRequest, from_outcome
from app.TIME.context import CandidateContext, RentalCandidate
from app.TIME.service import Boundary, RerouteOutcome, RerouteStatus
from app.TIME.station_index import RentalStation
from app.TIME.strategy import RECOMMENDED_BY_ALGORITHM, RerouteProposal
from app.TIME.trigger import StockReading

KST = ZoneInfo("Asia/Seoul")


def _station(rental_id: str, *, name: str | None = None) -> RentalStation:
    return RentalStation(
        rental_id=rental_id,
        name=name or rental_id,
        lat=37.5665,
        lng=126.9780,
        rack_count=10,
        current_stock=4,
        updated_at=None,
    )


def _reading(**overrides: object) -> StockReading:
    body: dict[str, object] = {
        "current_stock": 3,
        "predicted_stock": 0.3,
        "p_empty": 0.83,
        "p_full": 0.0,
        "source": "lightgbm",
        "model_horizon_min": 15,
    }
    body.update(overrides)
    return StockReading(**body)  # type: ignore[arg-type]


def _proposal_outcome() -> RerouteOutcome:
    target = _station("ST-1234", name="강남역 2번 출구")
    alt_station = _station("ST-1290", name="역삼로")
    boundary = Boundary(leg_index=1, node_id="221", lat=37.500658, lng=127.03643)
    alt_candidate = CandidateContext(
        candidate=RentalCandidate(station=alt_station, distance_m=180.4),
        reading=_reading(current_stock=6, predicted_stock=4.2, p_empty=0.08),
    )
    proposal = RerouteProposal(
        candidate_index=0,
        reason="강남역 2번 출구 대여소는 도착 시점에 자전거가 없을 가능성이 높습니다.",
        recommended_by=RECOMMENDED_BY_ALGORITHM,
        score=1.5,
    )
    route = {
        "routeType": "BIKE_SUBWAY",
        "totalMinutes": 21.5,
        "source": "ALGORITHM",
        "totalDistanceMeters": 6120.0,
        "transferCount": 1,
        "legs": [{"mode": "BIKE", "minutes": 8.0, "routeId": None}],
    }
    walk_leg = {
        "mode": "WALK",
        "fromNodeId": "221",
        "fromNodeName": None,
        "fromLat": 37.500658,
        "fromLng": 127.03643,
        "toNodeId": "ST-1290",
        "toNodeName": "역삼로",
        "toLat": 37.49,
        "toLng": 127.03,
        "routeId": None,
        "routeName": None,
        "minutes": 3.5,
        "distanceMeters": 234,
        "geometry": {
            "type": "MultiLineString",
            "coordinates": [[[127.03643, 37.500658], [127.03, 37.49]]],
        },
        "geometryStatus": "estimated",
        "estimated": True,
    }
    return RerouteOutcome(
        status=RerouteStatus.PROPOSAL,
        reason=proposal.reason,
        target=target,
        target_reading=_reading(current_stock=2, predicted_stock=0.4, p_empty=0.83),
        proposal=proposal,
        alternative=alt_candidate,
        boundary=boundary,
        walk_leg=walk_leg,
        route=route,
    )


# ── from_outcome — PROPOSAL ──


def test_proposal은_camelCase_필드로_직렬화된다():
    outcome = _proposal_outcome()
    now = datetime(2026, 9, 22, 9, 10, tzinfo=KST)

    response = from_outcome(outcome, recommendation_id="REC-1", valid_until=now)
    body = response.model_dump(by_alias=True, mode="json")

    assert body["status"] == "proposal"
    assert body["recommendationId"] == "REC-1"
    assert body["validUntil"] is not None
    assert body["recommendedBy"] == RECOMMENDED_BY_ALGORITHM
    assert body["target"]["rentalId"] == "ST-1234"
    assert body["target"]["currentBikes"] == 2
    assert body["target"]["predictedStock"] == 0.4
    assert body["target"]["pEmpty"] == 0.83
    assert body["target"]["horizonMin"] == 15
    assert body["alternative"]["rentalId"] == "ST-1290"
    assert body["alternative"]["distanceMeters"] == 180  # round(180.4)
    assert body["alternative"]["currentBikes"] == 6
    assert body["boundary"] == {
        "legIndex": 1,
        "nodeId": "221",
        "lat": 37.500658,
        "lng": 127.03643,
    }


def test_walkLeg와_route는_그대로_통과한다():
    outcome = _proposal_outcome()

    response = from_outcome(outcome, recommendation_id="REC-1", valid_until=None)

    assert response.walk_leg == outcome.walk_leg
    assert response.route == outcome.route
    # BE DTO 원문이라 재가공하지 않는다 — identity까지는 요구하지 않지만 내용이 정확히 같아야 한다.
    assert response.walk_leg["geometryStatus"] == "estimated"
    assert response.walk_leg["distanceMeters"] == 234


# ── from_outcome — 비-proposal ──


def test_비_proposal은_status와_reason만_남는다():
    outcome = RerouteOutcome(
        status=RerouteStatus.UNAVAILABLE,
        reason="route_unavailable",
        target=_station("ST-1234"),
        target_reading=_reading(),
        proposal=RerouteProposal(
            candidate_index=0, reason="문장", recommended_by=RECOMMENDED_BY_ALGORITHM
        ),
        alternative=CandidateContext(
            candidate=RentalCandidate(station=_station("ST-1290"), distance_m=100.0),
            reading=_reading(),
        ),
        boundary=Boundary(leg_index=1, node_id="221", lat=37.5, lng=127.0),
    )

    response = from_outcome(outcome, recommendation_id="REC-1", valid_until=datetime.now(KST))

    assert response.status == "unavailable"
    assert response.reason == "route_unavailable"
    assert response.recommendation_id is None
    assert response.valid_until is None
    assert response.recommended_by is None
    assert response.target is None
    assert response.alternative is None
    assert response.boundary is None
    assert response.walk_leg is None
    assert response.route is None


def test_no_trigger는_reason만_있고_나머지는_없다():
    outcome = RerouteOutcome(status=RerouteStatus.NO_TRIGGER, reason="below_threshold")

    response = from_outcome(outcome, recommendation_id=None, valid_until=None)

    assert response.status == "no_trigger"
    assert response.reason == "below_threshold"
    assert response.target is None


# ── RerouteCheckRequest ──


def test_request는_camelCase_JSON을_그대로_파싱한다():
    payload = {
        "sessionId": "SESS-1",
        "step": 2,
        "rentalId": "ST-1234",
        "etaToRentalMinutes": 12,
        "destStationId": "DEST-1",
        "boundary": {"legIndex": 1, "nodeId": "221", "lat": 37.5, "lng": 127.0},
        "debugForceTrigger": True,
    }

    req = RerouteCheckRequest.model_validate(payload)

    assert req.session_id == "SESS-1"
    assert req.rental_id == "ST-1234"
    assert req.eta_to_rental_minutes == 12
    assert req.dest_station_id == "DEST-1"
    assert req.debug_force_trigger is True
    assert isinstance(req.boundary, BoundaryIn)
    assert req.boundary.to_domain() == Boundary(leg_index=1, node_id="221", lat=37.5, lng=127.0)


def test_request는_boundary_없이도_파싱된다():
    payload = {
        "sessionId": "SESS-1",
        "step": 0,
        "rentalId": "ST-1234",
        "etaToRentalMinutes": 12,
        "destStationId": "DEST-1",
    }

    req = RerouteCheckRequest.model_validate(payload)

    assert req.boundary is None
    assert req.debug_force_trigger is False  # 기본값
