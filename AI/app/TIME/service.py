"""재안내 판정 진입점(S15P21A104-203/302) — ①~⑥을 잇는 유일한 자리.

```
① 대상 조회     station_index.get     로컬 색인(latest_stock.parquet)
② 재고 조회     planner.read_stock    BE(get_eta_stock) 1회
③ 트리거 판정   trigger.evaluate      규칙
④ 후보 생성     candidates.generate   로컬 색인(haversine)
⑤ 프리페치·선택  planner.prefetch      BE 순차 호출
                strategy.decide       규칙 또는 LLM  ← 주입받는다
⑥ 경로 연결·도보 합성  guard.run(REPLAN_ROUTE) + build_walk_leg
```

**여기까지가 순수 라이브러리다.** FastAPI·세션 보관소·HTTP 모양은 `router.py`의 몫이고, 이
모듈은 그것을 모른다 — 호출 방향(FE→BE→AI / FE→AI)이 아직 결정 대기라
(`FROM_BE-time-reroute-contract-01` 6번) 그 결정이 바뀌어도 이 파일은 안 바뀌어야 한다.

**상태를 갖지 않는다.** 쿨다운(`seconds_since_last_fire`)·`ToolGuard`·전략은 전부 인자다.
세션 단위로 살아야 하는 것들이라 여기서 만들면 동시 사용자끼리 예산과 쿨다운을 공유한다
(`TOOL_CONTRACT.md` 5절).

**예외를 밖으로 내보내지 않는다.** 재안내는 "있으면 좋은 것"이라, 어디서 무엇이 실패하든
호출자는 기존 안내를 그대로 유지하면 된다. 실패는 `RerouteStatus.UNAVAILABLE`이라는 값으로 나온다.

## 단계별 실패 매핑 — 이 모듈의 핵심 판단

| 단계 | 조건 | 상태 | `reason` |
| --- | --- | --- | --- |
| ① 대상 조회 | `station_index.get(rental_id)`가 `None` | `UNAVAILABLE` | `target_unknown` |
| ③ 트리거 | `trig.reason == stock_unknown`(② 조회가 `ToolError`) | `UNAVAILABLE` | `stock_unknown` |
| ③ 트리거 | 그 밖의 미발화 사유(`below_threshold`·`cooldown`·`horizon_out_of_range`·`low_confidence`) | `NO_TRIGGER` | `trig.reason` 그대로 |
| ④ 후보 생성 | `candidates.generate()`가 빈 목록 | `NO_ALTERNATIVE` | `no_nearby_station` |
| ⑤ 프리페치 | 후보는 있는데 전부 조회 실패(`error is not None`) | `UNAVAILABLE` | `all_candidates_failed` |
| ⑤ 프리페치 | 전부 실패는 아닌데 `ctx.has_alternative`가 `False`(방어적 — 현재 `prefetch` 구현에서는 도달하지 않는다) | `NO_ALTERNATIVE` | `no_alternative` |
| ⑤ 선택 | `strategy`가 `None` | `UNAVAILABLE` | `no_strategy` |
| ⑤ 선택 | `strategy.decide(ctx)`가 `None`("대안은 있는데 점수를 못 냈다" — 대안 없음의 근거가 아니다) | `UNAVAILABLE` | `strategy_undecided` |
| ⑥ 경로 연결 | `boundary`가 `None` | `UNAVAILABLE` | `boundary_missing` |
| ⑥ 경로 연결 | `REPLAN_ROUTE`가 `ToolError` 또는 빈 배열(`route: null` 제안은 FE 결정상 금지) | `UNAVAILABLE` | `route_unavailable` |
| ⑥ 경로 연결 | 첫 원소에 안쪽 `route` dict가 없다 | `UNAVAILABLE` | `route_malformed` |
| ⑥ 성공 | 도보 합성까지 끝남 | `PROPOSAL` | `proposal.reason`(사용자 문장) |
| 그 외 | 어디서든 예상 못 한 예외 | `UNAVAILABLE` | `internal_error` |

①②④는 조회·판정 순서고, ⑤의 후보 선택 자체는 규칙 또는 LLM(`strategy`)에 위임한다. ⑥은
선택된 대안 이후에만 도는 단계라 앞 단계들과 실패 사유가 겹치지 않는다.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from app.TIME import candidates, planner, trigger
from app.TIME.adapters import ToolAdapter
from app.TIME.context import CandidateContext
from app.TIME.guard import ToolGuard
from app.TIME.registry import REPLAN_ROUTE
from app.TIME.schemas import is_error
from app.TIME.station_index import WALK_SPEED_M_PER_MIN, RentalStation, StationIndex, haversine_m
from app.TIME.strategy import RerouteProposal, RerouteStrategy
from app.TIME.trigger import StockReading, Thresholds, TriggerResult

_log = logging.getLogger(__name__)

WALK_DETOUR_FACTOR = 1.3
"""직선거리 → 실제 보행거리 보정 계수. **잠정값**(계획 2.5절) — `viaNodeId` 실경로 연동 전까지
직선 하버사인에 곱해 대략의 보행 거리·소요시간을 낸다."""

# 실패 사유(`RerouteOutcome.reason`). 트리거 미발화는 `trigger.REASON_*`를 그대로 쓰고, 여기는
# 이 모듈(①④⑤⑥)에서만 나는 사유만 둔다 — 모듈 docstring의 표와 문자열이 같아야 한다.
REASON_TARGET_UNKNOWN = "target_unknown"
REASON_NO_NEARBY_STATION = "no_nearby_station"
REASON_ALL_CANDIDATES_FAILED = "all_candidates_failed"
REASON_NO_ALTERNATIVE = "no_alternative"
REASON_NO_STRATEGY = "no_strategy"
REASON_STRATEGY_UNDECIDED = "strategy_undecided"
REASON_BOUNDARY_MISSING = "boundary_missing"
REASON_ROUTE_UNAVAILABLE = "route_unavailable"
REASON_ROUTE_MALFORMED = "route_malformed"
REASON_INTERNAL_ERROR = "internal_error"


class RerouteStatus(StrEnum):
    """호출자가 구분해야 하는 네 가지 결과.

    `NO_ALTERNATIVE`와 `UNAVAILABLE`을 굳이 나누는 이유는 `ToolErrorCode`의
    `NOT_FOUND`/`UPSTREAM_UNAVAILABLE` 구분과 같다(`TOOL_CONTRACT.md` 2.1절) — **"대안이 없다"와
    "대안이 있는지 물어보지 못했다"는 다르다.** 뭉개면 조회 장애를 "이 경로가 최선"이라고
    사용자에게 말하게 된다.
    """

    NO_TRIGGER = "no_trigger"
    """평소 상태. 대부분의 폴링이 여기서 끝난다."""

    NO_ALTERNATIVE = "no_alternative"
    """트리거는 섰는데 갈아탈 대여소가 실제로 없었다. 조회는 정상이었다."""

    UNAVAILABLE = "unavailable"
    """조회·판정을 끝내지 못했다. 호출자는 **조용히 무시**하고 기존 안내를 유지한다."""

    PROPOSAL = "proposal"
    """추천이 있다. `RerouteOutcome.proposal`·`route`·`walk_leg`가 채워진다."""


@dataclass(frozen=True)
class Boundary:
    """교체 경계 = 하차역. FE가 보내는 값이고 AI는 좌표를 추측하지 않고 그대로 에코한다.

    네 값 중 하나라도 없으면 FE가 애초에 호출하지 않는다(`TO_FE-bike-reroute-04.md` 1절) — 이
    타입이 전부 필수 필드인 이유다.
    """

    leg_index: int
    node_id: str
    lat: float
    lng: float


@dataclass(frozen=True)
class RerouteOutcome:
    """판정 결과 한 벌. `status` 외의 필드는 알아낸 만큼만 채워지는 부산물이다 — 어느 단계에서
    멈췄느냐에 따라 뒤 단계 필드는 비어 있다(값을 지어내지 않는다).
    """

    status: RerouteStatus

    reason: str | None = None
    """`PROPOSAL`이면 사용자에게 보여줄 문장(`proposal.reason`과 같다). 그 밖의 상태면 내부
    사유 코드(모듈 docstring의 표)다 — 이 경우 사용자에게 그대로 보여주는 문장이 아니다."""

    trigger: TriggerResult | None = None
    """트리거 판정. `facts`가 안내 문장이 인용한 사실 집합이다."""

    target: RentalStation | None = None
    """대상 대여소. ①에서 찾은 뒤로는 실패해도 계속 채워진다."""

    target_reading: StockReading | None = None
    """대상의 `get_eta_stock` 결과. ②가 `ToolError`를 냈으면 `None`이다."""

    proposal: RerouteProposal | None = None
    alternative: CandidateContext | None = None
    """선택된 후보. `strategy.decide`가 고른 것이라 ⑥ 실패(`boundary_missing` 등)에도 채워질 수
    있다 — "무엇을 고르려 했는지"는 알 수 있고 "경로를 못 이었다"만 실패했기 때문이다."""

    boundary: Boundary | None = None
    """요청받은 경계를 그대로 에코한다."""

    walk_leg: dict[str, Any] | None = None
    route: dict[str, Any] | None = None
    """BE `replan_route` 응답 원소의 **안쪽 `route`만**(순수 경로 DTO). 바깥 `reason`·`source`는
    버린다(`TO_FE-bike-reroute-04.md` 2.1절)."""


def propose_reroute(
    *,
    rental_id: str,
    eta_to_rental_minutes: int,
    step: int,
    dest_station_id: str,
    boundary: Boundary | None,
    adapter: ToolAdapter,
    guard: ToolGuard,
    strategy: RerouteStrategy | None,
    station_index: StationIndex,
    seconds_since_last_fire: float | None = None,
    thresholds: Thresholds | None = None,
    radius_m: int = 500,
    candidate_limit: int = candidates.MAX_CANDIDATES,
    force_trigger: bool = False,
) -> RerouteOutcome:
    """지금 재안내를 띄울지 판정하고, 띄운다면 대안 대여소·도보·잔여 경로까지 정한다.

    `rental_id`는 지금 안내 중인(고갈이 우려되는) 대여소, `eta_to_rental_minutes`는 그 대여소
    도착까지 남은 분이다. `boundary`는 FE가 보낸 하차역 경계(§`Boundary`) — 없으면 ⑥에서
    `unavailable`이 된다(추측하지 않는다).

    `seconds_since_last_fire`·`thresholds`·`strategy`·`guard`는 전부 세션(요청 하나) 단위
    인자다. 모듈 docstring 참고 — 이 함수가 상태를 들고 있지 않은 이유가 그것이다.
    """
    try:
        return _propose(
            rental_id=rental_id,
            eta_to_rental_minutes=eta_to_rental_minutes,
            step=step,
            dest_station_id=dest_station_id,
            boundary=boundary,
            adapter=adapter,
            guard=guard,
            strategy=strategy,
            station_index=station_index,
            seconds_since_last_fire=seconds_since_last_fire,
            thresholds=thresholds,
            radius_m=radius_m,
            candidate_limit=candidate_limit,
            force_trigger=force_trigger,
        )
    except Exception as exc:  # noqa: BLE001 - 불변식 유지가 목적이라 의도적으로 넓다
        # 어댑터·가드는 이미 실패를 값으로 내지만(`TOOL_CONTRACT.md` 2.2절), 전략 구현이나
        # 호출자가 넘긴 자료구조에서 새 예외가 날 수 있다. 재안내 하나 때문에 폴링 요청 전체가
        # 500이 되는 일은 없어야 한다. 예외 detail은 로그에 남기지 않는다 — rental_id·좌표 같은
        # 사용자 이동 정보가 메시지에 섞여 있을 수 있어서다(타입 이름만 남긴다).
        _log.exception("재안내 판정 중 예상 못 한 오류(%s)", type(exc).__name__)
        return RerouteOutcome(status=RerouteStatus.UNAVAILABLE, reason=REASON_INTERNAL_ERROR)


def _propose(
    *,
    rental_id: str,
    eta_to_rental_minutes: int,
    step: int,
    dest_station_id: str,
    boundary: Boundary | None,
    adapter: ToolAdapter,
    guard: ToolGuard,
    strategy: RerouteStrategy | None,
    station_index: StationIndex,
    seconds_since_last_fire: float | None,
    thresholds: Thresholds | None,
    radius_m: int,
    candidate_limit: int,
    force_trigger: bool,
) -> RerouteOutcome:
    # ── ① 대상 조회 ──
    target = station_index.get(rental_id)
    if target is None:
        # 좌표를 모르면 주변 탐색(④) 자체가 불가능하다 — 추측하지 않는다.
        return RerouteOutcome(status=RerouteStatus.UNAVAILABLE, reason=REASON_TARGET_UNKNOWN)

    # ── ② 재고 조회 ──
    reading = planner.read_stock(rental_id, eta_to_rental_minutes, adapter=adapter, guard=guard)
    target_reading = reading if isinstance(reading, StockReading) else None

    # ── ③ 트리거 ──
    trig = trigger.evaluate(
        reading,
        eta_minutes=eta_to_rental_minutes,
        seconds_since_last_fire=seconds_since_last_fire,
        thresholds=thresholds,
        force=force_trigger,
    )
    if not trig.fired:
        # `stock_unknown`은 "물어보지 못했다"이지 "평소 상태"가 아니다 — 나머지 미발화 사유
        # (임계 미달·쿨다운·horizon 밖·저신뢰)와 같은 칸에 두지 않는다.
        status = (
            RerouteStatus.UNAVAILABLE
            if trig.reason == trigger.REASON_STOCK_UNKNOWN
            else RerouteStatus.NO_TRIGGER
        )
        return RerouteOutcome(
            status=status,
            reason=trig.reason,
            trigger=trig,
            target=target,
            target_reading=target_reading,
        )

    # 트리거가 섰다는 것은 규칙 1번(오류→stock_unknown)을 통과했다는 뜻이라 reading은
    # ToolError일 수 없다(`trigger.evaluate` 순서 참고) — 여기서 타입을 좁힌다.
    assert isinstance(reading, StockReading)
    target_reading = reading

    # ── ④ 후보 생성 ──
    cands = candidates.generate(target, station_index, radius_m=radius_m, limit=candidate_limit)
    if not cands:
        return RerouteOutcome(
            status=RerouteStatus.NO_ALTERNATIVE,
            reason=REASON_NO_NEARBY_STATION,
            trigger=trig,
            target=target,
            target_reading=target_reading,
        )

    # ── ⑤ 프리페치·선택 ──
    ctx = planner.prefetch(
        decision=trig,
        target=target,
        target_reading=target_reading,
        eta_minutes=eta_to_rental_minutes,
        candidates=cands,
        adapter=adapter,
        guard=guard,
        dest_station_id=dest_station_id,
    )
    all_failed = bool(ctx.candidates) and all(c.error is not None for c in ctx.candidates)
    if all_failed:
        return RerouteOutcome(
            status=RerouteStatus.UNAVAILABLE,
            reason=REASON_ALL_CANDIDATES_FAILED,
            trigger=trig,
            target=target,
            target_reading=target_reading,
        )
    if not ctx.has_alternative:
        # 방어적 분기다 — 지금의 `prefetch` 구현에서 후보가 있고 전부 실패도 아니면 하나는
        # `usable`이라 이론상 도달하지 않는다. 그래도 "전부 실패"와 "대안 없음"을 같은 값으로
        # 뭉개지 않기 위해 자리를 남겨둔다.
        return RerouteOutcome(
            status=RerouteStatus.NO_ALTERNATIVE,
            reason=REASON_NO_ALTERNATIVE,
            trigger=trig,
            target=target,
            target_reading=target_reading,
        )

    if strategy is None:
        return RerouteOutcome(
            status=RerouteStatus.UNAVAILABLE,
            reason=REASON_NO_STRATEGY,
            trigger=trig,
            target=target,
            target_reading=target_reading,
        )

    proposal = strategy.decide(ctx)
    if proposal is None:
        # 대안은 받았는데 점수를 하나도 못 냈다 — 응답 모양이 예상과 다르다는 뜻이지
        # "대안이 없다"는 근거가 아니다(`AGENT_DESIGN.md` 계획 2.4절/§3.1).
        return RerouteOutcome(
            status=RerouteStatus.UNAVAILABLE,
            reason=REASON_STRATEGY_UNDECIDED,
            trigger=trig,
            target=target,
            target_reading=target_reading,
        )

    alt = ctx.usable_candidates[proposal.candidate_index]

    # ── ⑥ 경로 연결·도보 합성 ──
    if boundary is None:
        return RerouteOutcome(
            status=RerouteStatus.UNAVAILABLE,
            reason=REASON_BOUNDARY_MISSING,
            trigger=trig,
            target=target,
            target_reading=target_reading,
            proposal=proposal,
            alternative=alt,
        )

    route_args = {
        "step": step,
        "boundary_id": alt.candidate.station.rental_id,
        "dest_station_id": dest_station_id,
    }
    replan_result = guard.run(
        REPLAN_ROUTE, lambda: adapter.call(REPLAN_ROUTE, route_args), route_args
    )
    if is_error(replan_result) or not isinstance(replan_result, list) or not replan_result:
        # `ToolError`든 빈 배열이든 "이 경로가 최선"이라고 말할 근거가 없다 — FE 결정상
        # `route: null` 제안은 금지라 여기서 제안 자체를 내지 않는다(unavailable).
        return RerouteOutcome(
            status=RerouteStatus.UNAVAILABLE,
            reason=REASON_ROUTE_UNAVAILABLE,
            trigger=trig,
            target=target,
            target_reading=target_reading,
            proposal=proposal,
            alternative=alt,
            boundary=boundary,
        )

    first = replan_result[0]  # BE가 소요시간순으로 정렬해 준다 — 첫 원소를 그대로 쓴다.
    route = first.get("route") if isinstance(first, Mapping) else None
    if not isinstance(route, Mapping):
        return RerouteOutcome(
            status=RerouteStatus.UNAVAILABLE,
            reason=REASON_ROUTE_MALFORMED,
            trigger=trig,
            target=target,
            target_reading=target_reading,
            proposal=proposal,
            alternative=alt,
            boundary=boundary,
        )

    walk_leg = build_walk_leg(boundary, alt.candidate.station)

    return RerouteOutcome(
        status=RerouteStatus.PROPOSAL,
        reason=proposal.reason,
        trigger=trig,
        target=target,
        target_reading=target_reading,
        proposal=proposal,
        alternative=alt,
        boundary=boundary,
        walk_leg=walk_leg,
        route=dict(route),
    )


def build_walk_leg(boundary: Boundary, station: RentalStation) -> dict[str, Any]:
    """하차역(`boundary`)→대안 대여소(`station`) 도보 leg를 합성한다.

    실제 보행 라우팅이 없어(`viaNodeId` 경유 강제 연동 전) 직선거리를 `WALK_DETOUR_FACTOR`로
    보정해 근사한다 — `estimated: true`·`geometryStatus: "estimated"`로 그 사실을 밝힌다.
    필드 이름은 BE `RouteLegResponse`와 같다(`TO_FE-bike-reroute-04.md` 2.2절) — FE가 같은
    변환기를 그대로 타게 하려는 것이다. 좌표 순서는 BE와 같은 GeoJSON `[lng, lat]`다.

    `minutes`·`distanceMeters`는 **같은 보정 거리**(직선×1.3)에서 나온다 — 편지의 예시(234m·
    3.5분)가 `234 / 67 ≈ 3.5`로 맞아떨어지는 것과 같은 값이다. `alternative.distanceMeters`
    (직선)와 다른 것은 의도다 — 앞은 "얼마나 가까운가", 여기는 "얼마나 걷나"(편지 2.3절).
    """
    straight_m = haversine_m(boundary.lat, boundary.lng, station.lat, station.lng)
    walk_m = straight_m * WALK_DETOUR_FACTOR
    return {
        "mode": "WALK",
        "fromNodeId": boundary.node_id,
        "fromNodeName": None,
        "fromLat": boundary.lat,
        "fromLng": boundary.lng,
        "toNodeId": station.rental_id,
        "toNodeName": station.name,
        "toLat": station.lat,
        "toLng": station.lng,
        "routeId": None,
        "routeName": None,
        "minutes": round(walk_m / WALK_SPEED_M_PER_MIN, 1),
        "distanceMeters": round(walk_m),
        "geometry": {
            "type": "MultiLineString",
            "coordinates": [[[boundary.lng, boundary.lat], [station.lng, station.lat]]],
        },
        "geometryStatus": "estimated",
        "estimated": True,
    }


__all__ = [
    "REASON_ALL_CANDIDATES_FAILED",
    "REASON_BOUNDARY_MISSING",
    "REASON_INTERNAL_ERROR",
    "REASON_NO_ALTERNATIVE",
    "REASON_NO_NEARBY_STATION",
    "REASON_NO_STRATEGY",
    "REASON_ROUTE_MALFORMED",
    "REASON_ROUTE_UNAVAILABLE",
    "REASON_STRATEGY_UNDECIDED",
    "REASON_TARGET_UNKNOWN",
    "WALK_DETOUR_FACTOR",
    "Boundary",
    "RerouteOutcome",
    "RerouteStatus",
    "build_walk_leg",
    "propose_reroute",
]
