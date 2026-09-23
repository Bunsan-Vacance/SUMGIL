"""재안내 라우터(S15P21A104-302) — `POST /time/reroute/check`.

`service.propose_reroute()`가 상태·사유를 전부 정한다(`AGENT_DESIGN.md` §3). 이 모듈은 그
결과를 세션 보관소·추천 ID·HTTP 응답 모양으로 감싸는 **껍데기**일 뿐이다 — FE→AI 직접 호출인지
FE→BE→AI인지가 아직 결정 대기라(`FROM_BE-time-reroute-contract-01` 6번) 그 결정이 바뀌어도
`service.py`가 안 바뀌게 하려는 구조가 여기서도 지켜진다.

**여기서도 예외를 밖으로 내보내지 않는다.** `propose_reroute` 자체는 이미 내부에서 예외를
잡지만, 이 라우터의 조립(세션 보관소 조회·전략 생성 등)에서 새 예외가 날 수 있다 — 재안내 폴링
하나 때문에 요청이 500이 되는 일은 없어야 한다는 원칙(`service.py` 모듈 docstring)을 여기서
한 번 더 지킨다. **항상 HTTP 200이다.**

팩토리 함수(`_station_index`·`_session_store`·`_adapter`·`_strategy`·`_now`)는 테스트가
`app.BIKE.router` 테스트의 `service._store` monkeypatch와 같은 패턴으로 갈아끼운다.
`_station_index`·`_session_store`만 **프로세스 싱글턴**이고(파일 조회·세션 상태는 요청 사이에
남아야 한다), `_adapter`·`_strategy`는 매 요청 새로 만든다. **`_strategy`만 인자
(`session_id`)를 받는다** — 324-3부터 LLM 세션 예산(`llm_budget.LlmBudget`)을 세션 보관소에
붙였고, `_strategy`가 그 세션의 예산을 꺼내 `AgentStrategy`에 물려야 해서다.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

from fastapi import APIRouter

from app.core.config import get_settings
from app.TIME.adapters import CompositeAdapter, HttpAdapter, LocalAdapter, ToolAdapter
from app.TIME.api_schemas import (
    RerouteCheckRequest,
    RerouteCheckResponse,
    from_outcome,
)
from app.TIME.guard import ToolGuard
from app.TIME.llm import settings_client
from app.TIME.llm_budget import LlmBudget
from app.TIME.service import RerouteStatus, propose_reroute
from app.TIME.session import InMemorySessionStore, SessionStore
from app.TIME.station_index import ParquetStationIndex, StationIndex
from app.TIME.strategy import AgentStrategy, RerouteStrategy, RuleStrategy, ScoreWeights
from app.TIME.trigger import Thresholds

_log = logging.getLogger(__name__)

# `app.TIME.adapters.KST`와 같은 값 — 상수 하나 때문에 다른 모듈을 끌어오지 않는다.
KST = ZoneInfo("Asia/Seoul")

router = APIRouter(prefix="/time", tags=["time"])

_station_index_singleton: StationIndex | None = None
_session_store_singleton: SessionStore | None = None


def _now() -> datetime:
    """KST 기준 현재 시각. 테스트가 monkeypatch로 고정한다(`recommendationId`·`validUntil`
    검증에 고정 시각이 필요하다)."""
    return datetime.now(KST)


def _station_index() -> StationIndex:
    """`latest_stock.parquet` 색인 — 프로세스 싱글턴. `ParquetStationIndex` 자체가 mtime
    캐시를 갖고 있어(파일이 안 바뀌면 다시 안 읽는다), 매 요청 새로 만들어도 비용은 크지 않지만
    그래도 인스턴스는 하나로 둔다(`app.BIKE.service.get_live_stock_store`와 같은 패턴)."""
    global _station_index_singleton
    if _station_index_singleton is None:
        settings = get_settings()
        _station_index_singleton = ParquetStationIndex(
            settings.bike_live_stock_path, settings.bike_live_stock_max_staleness_seconds
        )
    return _station_index_singleton


def _session_store() -> SessionStore:
    """세션 쿨다운 보관소 — 프로세스 싱글턴(`session.py` 모듈 docstring 참고. 여러 세션이
    한 인스턴스를 공유해야 쿨다운이 폴링 사이에 유지된다). TTL은 쿨다운 노브를 그대로 쓴다 —
    쿨다운이 끝난 세션의 발화 기록은 더 볼 일이 없다. 324-3부터 같은 TTL로 세션별 LLM 예산도
    같이 보관한다(`session.py` 모듈 docstring 324-3 문단).

    `clock=_now`를 넘긴다 — 안 넘기면 `InMemorySessionStore`가 자기 시계(`session.py`의
    `_now_kst`, 실제 벽시계)를 쓰게 되는데, 그러면 `_now()`를 고정해 테스트하는 라우터의
    다른 계산(`seconds_since_last_fire`·`validUntil`)과 저장소의 만료 판정이 서로 다른
    시각을 기준으로 움직인다 — 실제 운영에서는 둘 다 실시각이라 안 드러나지만, `_now`를
    고정하는 테스트에서는 만료 판정만 실시각을 써서 쿨다운이 조용히 안 걸리는 어긋남이 난다.

    `budget_factory`는 `Settings`의 세션 예산 노브를 닫아넣은 클로저다 — 싱글턴 생성 시점의
    설정값을 그대로 굳힌다(다른 노브들도 이미 이 함수에서 그렇게 굳는다).
    """
    global _session_store_singleton
    if _session_store_singleton is None:
        settings = get_settings()
        _session_store_singleton = InMemorySessionStore(
            ttl_sec=settings.time_trigger_cooldown_sec,
            clock=_now,
            budget_factory=lambda: LlmBudget(
                max_calls=settings.time_llm_max_calls_per_session,
                max_total_tokens=settings.time_llm_max_tokens_per_session,
            ),
        )
    return _session_store_singleton


def _adapter() -> ToolAdapter:
    """요청마다 새로 만든다 — `CompositeAdapter`·`LocalAdapter`·`HttpAdapter`는 상태를 갖지
    않는 얇은 래퍼라 재사용할 이유가 없다(`guard.py`의 세션 단위 인스턴스 원칙과 달리, 이쪽은
    애초에 세션 상태가 없다)."""
    settings = get_settings()
    return CompositeAdapter(
        local=LocalAdapter(),
        http=HttpAdapter(settings.time_be_base_url, settings.time_be_timeout_sec),
    )


def _strategy(session_id: str) -> RerouteStrategy:
    """규칙 폴백을 기본으로 두고, LLM 게이트웨이 설정(주소·모델명·키) 셋이 전부 있을 때만
    `AgentStrategy`로 갈아 끼운다 — 하나라도 없으면 규칙 전략이 그대로 나간다(운영 폴백,
    `strategy.py` 모듈 docstring).

    **324-3: 세션 단위 예산.** `_session_store().budget_for(session_id)`로 이 세션의
    `LlmBudget`을 꺼내 물린다 — 요청마다 새로 만들지 않으므로 세션당 3회/8000토큰 한도가
    폴링 여러 번에 걸쳐 실제로 누적된다(`session.py` 모듈 docstring 324-3 문단, 이전에는
    요청 단위로 매번 새로 만들었다).
    """
    settings = get_settings()
    rule = RuleStrategy(ScoreWeights.from_settings(settings))
    if settings.time_llm_base_url and settings.time_llm_model and settings.time_llm_api_key:
        return AgentStrategy(
            settings_client(settings),
            fallback=rule,
            budget=_session_store().budget_for(session_id),
            max_sentences=settings.time_agent_reason_max_sentences,
            max_chars=settings.time_agent_reason_max_chars,
        )
    return rule


@router.post("/reroute/check", response_model=RerouteCheckResponse)
def check_reroute(req: RerouteCheckRequest) -> RerouteCheckResponse:
    """폴링 하나를 판정한다. **절대 예외를 던지지 않는다** — 무엇이 터지든 200을 낸다
    (모듈 docstring)."""
    try:
        return _check_reroute(req)
    except Exception as exc:  # noqa: BLE001 - service.propose_reroute와 같은 이유의 마지막 그물
        _log.exception("재안내 라우터 처리 중 예상 못 한 오류(%s)", type(exc).__name__)
        return RerouteCheckResponse(status="unavailable", reason="internal_error")


def _check_reroute(req: RerouteCheckRequest) -> RerouteCheckResponse:
    settings = get_settings()
    now = _now()
    store = _session_store()

    last_fired = store.last_fired_at(req.session_id)
    seconds_since_last_fire = (now - last_fired).total_seconds() if last_fired is not None else None

    # 운영 환경에서는 플래그가 꺼져 있어 디버그 강제 트리거가 조용히 무시된다
    # (`config.py` time_debug_force_trigger_enabled 주석).
    force_trigger = req.debug_force_trigger and settings.time_debug_force_trigger_enabled
    boundary = req.boundary.to_domain() if req.boundary is not None else None

    outcome = propose_reroute(
        rental_id=req.rental_id,
        eta_to_rental_minutes=req.eta_to_rental_minutes,
        step=req.step,
        dest_station_id=req.dest_station_id,
        boundary=boundary,
        adapter=_adapter(),
        guard=ToolGuard(),  # 세션(요청 하나) 단위 — guard.py 첫 문단
        strategy=_strategy(req.session_id),
        station_index=_station_index(),
        seconds_since_last_fire=seconds_since_last_fire,
        thresholds=Thresholds.from_settings(settings),
        radius_m=settings.time_nearby_radius_m,
        candidate_limit=settings.time_nearby_limit,
        force_trigger=force_trigger,
    )

    recommendation_id: str | None = None
    valid_until: datetime | None = None
    if outcome.status is RerouteStatus.PROPOSAL:
        recommendation_id = str(uuid4())
        valid_until = now + timedelta(seconds=settings.time_recommendation_ttl_sec)
        store.mark_fired(req.session_id, recommendation_id, valid_until, now=now)

    # 좌표를 남기지 않는다 — status·reason·session_id만으로도 폴링 흐름을 추적하기엔 충분하고,
    # 좌표를 남기기 시작하면 로그가 사실상 위치 추적 기록이 된다(guard.py arg_keys_of와 같은 원칙).
    _log.info(
        "reroute check session=%s status=%s reason=%s",
        req.session_id,
        outcome.status.value,
        outcome.reason,
    )

    return from_outcome(outcome, recommendation_id=recommendation_id, valid_until=valid_until)
