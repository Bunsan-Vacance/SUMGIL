"""재안내 라우터 요청/응답 pydantic 모델(S15P21A104-302).

**이름이 `schemas.py`가 아니라 `api_schemas.py`인 이유.** 도메인 모듈 규약(`AI/CLAUDE.md`)상
요청/응답 pydantic 모델은 `schemas.py` 자리인데, `TIME/schemas.py`는 이미 도구 계층 공통 타입
(`ToolError`·`ToolErrorCode`)이 쓰고 있다(`AGENT_DESIGN.md` §3.4 "이름 충돌" 메모). 도구 계층
스키마를 옮기면 202/203 코드 전체의 import 경로가 바뀌므로, 대신 이 파일에 API 전용 이름을
새로 둔다.

**FE 계약은 camelCase, 내부는 snake_case다.** 모든 모델이 `populate_by_name=True` +
`Field(alias=...)`를 쓴다 — 요청은 camelCase JSON을 그대로 받고(별칭 검증), 응답은
`by_alias=True`로 camelCase JSON을 낸다(FastAPI `response_model`의 기본 동작이 이미
`by_alias=True`라 라우터에서 따로 지정할 필요가 없다). 필드 이름·의미는
`.claude/handoff/TO_FE-bike-reroute-04.md`(확정 계약)를 그대로 따른다.

`from_outcome()`이 `service.RerouteOutcome`을 이 응답 모양으로 옮기는 유일한 자리다 — **`status`가
`PROPOSAL`이 아니면 `status`(+`reason`) 외의 필드는 전부 비운다.** `RerouteOutcome`은 실패
단계에 따라 `boundary`·`alternative` 등이 부분적으로 채워져 있을 수 있지만(예: `route_unavailable`도
`boundary`는 echo한다 — `service.py` 참고), 그 부산물을 FE에 그대로 흘리지 않는다
(`TO_FE-bike-reroute-04.md` 2.3절 "proposal 외 상태는 status(+reason 있으면)만").
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.TIME.service import Boundary, RerouteOutcome, RerouteStatus


class BoundaryIn(BaseModel):
    """FE가 보내는 교체 경계(하차역). 네 값 모두 필수다 — 하나라도 없으면 FE가 애초에 호출하지
    않는다(`TO_FE-bike-reroute-04.md` 1절)."""

    model_config = ConfigDict(populate_by_name=True)

    leg_index: int = Field(alias="legIndex")
    node_id: str = Field(alias="nodeId")
    lat: float
    lng: float

    def to_domain(self) -> Boundary:
        return Boundary(leg_index=self.leg_index, node_id=self.node_id, lat=self.lat, lng=self.lng)


class BoundaryOut(BaseModel):
    """요청받은 경계를 그대로 에코한다(추측하지 않는다 — `service.Boundary` docstring)."""

    model_config = ConfigDict(populate_by_name=True)

    leg_index: int = Field(alias="legIndex")
    node_id: str = Field(alias="nodeId")
    lat: float
    lng: float

    @classmethod
    def from_domain(cls, boundary: Boundary) -> BoundaryOut:
        return cls(
            leg_index=boundary.leg_index,
            node_id=boundary.node_id,
            lat=boundary.lat,
            lng=boundary.lng,
        )


class RerouteCheckRequest(BaseModel):
    """`POST /time/reroute/check` 요청 본문."""

    model_config = ConfigDict(populate_by_name=True)

    session_id: str = Field(alias="sessionId")
    step: int
    rental_id: str = Field(alias="rentalId")
    eta_to_rental_minutes: int = Field(alias="etaToRentalMinutes")
    dest_station_id: str = Field(alias="destStationId")
    boundary: BoundaryIn | None = None
    debug_force_trigger: bool = Field(default=False, alias="debugForceTrigger")


class TargetOut(BaseModel):
    """지금 안내 중인(고갈이 우려되는) 대여소."""

    model_config = ConfigDict(populate_by_name=True)

    rental_id: str = Field(alias="rentalId")
    name: str | None = None
    current_bikes: int | None = Field(default=None, alias="currentBikes")
    predicted_stock: float | None = Field(default=None, alias="predictedStock")
    p_empty: float | None = Field(default=None, alias="pEmpty")
    horizon_min: int | None = Field(default=None, alias="horizonMin")


class AlternativeOut(BaseModel):
    """선택된 대안 대여소."""

    model_config = ConfigDict(populate_by_name=True)

    rental_id: str = Field(alias="rentalId")
    name: str | None = None
    lat: float
    lng: float
    distance_meters: int = Field(alias="distanceMeters")
    current_bikes: int | None = Field(default=None, alias="currentBikes")
    predicted_stock: float | None = Field(default=None, alias="predictedStock")
    p_empty: float | None = Field(default=None, alias="pEmpty")


class RerouteCheckResponse(BaseModel):
    """`POST /time/reroute/check` 응답. `status`가 `proposal`이 아니면 `reason` 외의 필드는
    전부 `None`이다(모듈 docstring)."""

    model_config = ConfigDict(populate_by_name=True)

    status: Literal["no_trigger", "no_alternative", "unavailable", "proposal"]
    recommendation_id: str | None = Field(default=None, alias="recommendationId")
    valid_until: datetime | None = Field(default=None, alias="validUntil")
    recommended_by: str | None = Field(default=None, alias="recommendedBy")
    reason: str | None = None
    """`status`가 `proposal`이 아니면 `service.py` 모듈 docstring 표의 사유 코드 문자열
    (`target_unknown`·`stock_unknown`·`route_malformed`·`route_not_from_alternative` 등) —
    `route_not_from_alternative`는 BE가 첫 leg BIKE를 보장하지 않아(`FROM_BE-bike-reroute-route-02.md`
    1번) 대안 대여소에서 출발하는 경로를 하나도 못 찾았을 때 나온다(324). `proposal`이면 사용자에게
    보여줄 문장이다."""
    target: TargetOut | None = None
    alternative: AlternativeOut | None = None
    boundary: BoundaryOut | None = None
    walk_leg: dict[str, Any] | None = Field(default=None, alias="walkLeg")
    route: dict[str, Any] | None = None


class SessionBudgetOut(BaseModel):
    """세션당 LLM 예산 노브(324-3, `llm_budget.LlmBudget`의 상한값)."""

    model_config = ConfigDict(populate_by_name=True)

    max_calls: int = Field(alias="maxCalls")
    max_total_tokens: int = Field(alias="maxTotalTokens")


class TimeMetaResponse(BaseModel):
    """`GET /time/meta`(324-2) 응답 — FE 디버그·시연용. **키는 절대 담지 않는다**
    (`llmModel`만 있고 `llmApiKey`는 없다)."""

    model_config = ConfigDict(populate_by_name=True)

    trigger_p_empty: float = Field(alias="triggerPEmpty")
    trigger_min_stock: float = Field(alias="triggerMinStock")
    trigger_max_eta_min: int = Field(alias="triggerMaxEtaMin")
    trigger_cooldown_sec: float = Field(alias="triggerCooldownSec")
    debug_force_trigger_enabled: bool = Field(alias="debugForceTriggerEnabled")
    nearby_radius_m: int = Field(alias="nearbyRadiusM")
    nearby_limit: int = Field(alias="nearbyLimit")
    score_empty_penalty_min: float = Field(alias="scoreEmptyPenaltyMin")
    strategy_kind: Literal["AGENT", "ALGORITHM"] = Field(alias="strategyKind")
    llm_model: str | None = Field(default=None, alias="llmModel")
    llm_configured: bool = Field(alias="llmConfigured")
    station_index_size: int | None = Field(default=None, alias="stationIndexSize")
    snapshot_age_sec: float | None = Field(default=None, alias="snapshotAgeSec")
    session_budget: SessionBudgetOut = Field(alias="sessionBudget")


def from_outcome(
    outcome: RerouteOutcome,
    *,
    recommendation_id: str | None,
    valid_until: datetime | None,
) -> RerouteCheckResponse:
    """`RerouteOutcome` → `RerouteCheckResponse`. `recommendation_id`·`valid_until`은 세션
    보관소·ID 발급(라우터의 몫)이 끝난 뒤 값이라 인자로 받는다 — 이 함수는 그 발급 자체를
    하지 않는다.
    """
    if outcome.status is not RerouteStatus.PROPOSAL:
        # 실패 단계에 따라 boundary·alternative 등이 부분적으로 채워져 있을 수 있지만
        # (`service.py`의 단계별 실패 매핑 표 참고), FE에는 넘기지 않는다.
        return RerouteCheckResponse(status=outcome.status.value, reason=outcome.reason)

    assert outcome.proposal is not None
    assert outcome.target is not None
    assert outcome.target_reading is not None
    assert outcome.alternative is not None
    assert outcome.boundary is not None

    alt_station = outcome.alternative.candidate.station
    alt_reading = outcome.alternative.reading

    return RerouteCheckResponse(
        status=outcome.status.value,
        recommendation_id=recommendation_id,
        valid_until=valid_until,
        recommended_by=outcome.proposal.recommended_by,
        reason=outcome.reason,
        target=TargetOut(
            rental_id=outcome.target.rental_id,
            name=outcome.target.name,
            current_bikes=outcome.target_reading.current_stock,
            predicted_stock=outcome.target_reading.predicted_stock,
            p_empty=outcome.target_reading.p_empty,
            horizon_min=outcome.target_reading.model_horizon_min,
        ),
        alternative=AlternativeOut(
            rental_id=alt_station.rental_id,
            name=alt_station.name,
            lat=alt_station.lat,
            lng=alt_station.lng,
            distance_meters=round(outcome.alternative.candidate.distance_m),
            current_bikes=alt_reading.current_stock if alt_reading is not None else None,
            predicted_stock=alt_reading.predicted_stock if alt_reading is not None else None,
            p_empty=alt_reading.p_empty if alt_reading is not None else None,
        ),
        boundary=BoundaryOut.from_domain(outcome.boundary),
        walk_leg=outcome.walk_leg,
        route=outcome.route,
    )


__all__ = [
    "AlternativeOut",
    "BoundaryIn",
    "BoundaryOut",
    "RerouteCheckRequest",
    "RerouteCheckResponse",
    "SessionBudgetOut",
    "TargetOut",
    "TimeMetaResponse",
    "from_outcome",
]
