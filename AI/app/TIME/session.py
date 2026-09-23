"""재안내 세션 쿨다운 보관소(S15P21A104-302/324).

**파드 1개를 전제한다.** 세션 상태를 프로세스 메모리 dict에 둔다 — 여러 파드로 수평 확장하면
사용자 요청이 매번 다른 파드에 붙을 수 있어 쿨다운이 파드마다 따로 논다. 지금은 그 상황이 아니라
(`AI/CLAUDE.md` 현재 상태), 미룰 수 있는 선택이다. Redis 등 공유 저장소로 바꿀 자리는 이미 표시돼
있다 — `SessionStore` Protocol만 지키면 `router.py`는 구현이 바뀐 줄도 모른다
(`AI/app/TIME/AGENT_DESIGN.md` §3.2 "TTL 보관소는 router.py의 몫"과 같은 결의 결정).

`guard.ToolGuard`와 같은 이유로 **세션 단위가 아니라 전역 인스턴스 하나를 여러 세션이 공유한다** —
이건 `ToolGuard`(세션마다 새로 만든다)와 반대다. 쿨다운은 "이 세션이 최근에 언제 팝업을 띄웠나"를
여러 요청(폴링)에 걸쳐 기억해야 하는 값이라, 요청마다 버리면 쿨다운 자체가 의미가 없다.

**324-3: LLM 세션 예산(`llm_budget.LlmBudget`)도 같은 이유로 여기 산다.** `AgentStrategy`가
매 요청 새 예산으로 시작하면 세션당 3회/8000토큰 한도가 폴링 여러 번에 걸쳐 누적되지 않는다
(`router.py`의 옛 주석 — 요청 단위로 남겨뒀던 자리). 쿨다운 항목(`_Entry`)은 `mark_fired`가
불릴 때만(=제안이 실제로 나갔을 때만) 생기는데, LLM 호출은 제안이 안 나가도(후보는 있었지만
경로 연결 실패 등) 일어날 수 있어 예산은 별도 dict(`_budgets`)로 관리한다 — 발화 여부와
무관하게 `budget_for()`를 부를 때마다 살아 있어야 한다. TTL은 쿨다운과 같은 값(`ttl_sec`)을
재사용하되, 마지막 접근 시각 기준 슬라이딩 만료다(고정 발화 시각 기준인 `_Entry`와 다르다) —
폴링이 이어지는 동안은 살아 있고, 한동안(`ttl_sec`) 접근이 없으면 다음 접근에서 새 예산으로
초기화된다.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from zoneinfo import ZoneInfo

from app.TIME.llm_budget import LlmBudget

# `app.TIME.adapters.KST`·`app.TIME.station_index.KST`와 같은 값이다. 상수 하나 때문에
# 다른 모듈을 끌어오지 않고 직접 정의한다(같은 이유는 두 모듈의 KST 주석 참고).
KST = ZoneInfo("Asia/Seoul")


class SessionStore(Protocol):
    """세션 하나의 "마지막으로 언제 재안내를 띄웠나"를 기억한다.

    구현체는 스레드 안전해야 한다 — 같은 세션의 동시 폴링(드문 경우지만 재시도 등으로 생길 수
    있다)에서도 카운트가 새지 않아야 한다.
    """

    def last_fired_at(self, session_id: str) -> datetime | None:
        """마지막으로 발화(`RerouteStatus.PROPOSAL`)한 시각. 기록이 없거나 TTL이 지났으면
        `None`이다 — "쿨다운 정보가 없다"를 그대로 알린다(`trigger.evaluate`는 이 `None`을
        "쿨다운 미적용"으로 읽는다)."""
        ...

    def mark_fired(
        self, session_id: str, recommendation_id: str, valid_until: datetime, now: datetime
    ) -> None:
        """발화 하나를 기록한다. `recommendation_id`·`valid_until`은 지금 당장 이 모듈이 쓰지는
        않지만, Redis로 옮길 때 "이 추천이 아직 유효한가"를 같은 조회로 답하려면 필요한 값이라
        인터페이스에 미리 둔다."""
        ...

    def budget_for(self, session_id: str) -> LlmBudget:
        """이 세션의 `LlmBudget`을 가져온다(없거나 만료됐으면 새로 만들어 저장한 뒤 돌려준다).

        같은 `LlmBudget` **인스턴스**를 돌려줘야 한다 — 매번 새 인스턴스를 만들면 `.check()`/
        `.record()`가 쌓은 호출·토큰 수가 폴링 사이에 사라져 세션 단위 예산이 되지 않는다
        (모듈 docstring 324-3 문단).
        """
        ...


@dataclass(frozen=True, slots=True)
class _Entry:
    fired_at: datetime
    recommendation_id: str
    valid_until: datetime


@dataclass(slots=True)
class _BudgetEntry:
    """세션 하나의 LLM 예산 항목. `_Entry`와 분리한 이유는 모듈 docstring 324-3 문단 참고."""

    budget: LlmBudget
    last_touched_at: datetime


class InMemorySessionStore:
    """프로세스 메모리 dict 기반 `SessionStore`. TTL이 지난 항목은 조회 시점에 지운다(lazy purge).

    **TTL은 쿨다운 기간과 같은 값을 쓴다** — `router.py`가
    `InMemorySessionStore(ttl_sec=settings.time_trigger_cooldown_sec)`로 만든다. 쿨다운이
    끝난 세션의 발화 기록은 더 볼 일이 없으므로, 별도 만료 정책 없이 같은 숫자를 재사용한다.

    시계는 생성자로 주입받는다(`clock`, 기본은 KST 현재 시각) — `guard.ToolGuard`와 같은 이유로
    테스트가 시간을 앞으로 돌릴 수 있게 열어둔다.
    """

    def __init__(
        self,
        ttl_sec: float,
        clock: Callable[[], datetime] | None = None,
        budget_factory: Callable[[], LlmBudget] | None = None,
    ) -> None:
        self.ttl_sec = ttl_sec
        self._clock = clock if clock is not None else _now_kst
        self._budget_factory = budget_factory if budget_factory is not None else LlmBudget
        """세션에 예산이 없을 때 새로 만드는 팩토리. 인자 없이 부른다 — 호출자(`router.py`)가
        `Settings`의 `time_llm_max_calls_per_session`·`time_llm_max_tokens_per_session`을 이미
        닫아넣은 클로저를 넘긴다. 기본값(`LlmBudget` 생성자)은 테스트·미지정 시의 폴백이다."""
        # `ToolGuard`와 같은 이유의 락 — read-modify-write(purge 후 재삽입)가 섞여 있어
        # 락이 없으면 동시 요청에서 기록이 유실될 수 있다.
        self._lock = threading.RLock()
        self._entries: dict[str, _Entry] = {}
        self._budgets: dict[str, _BudgetEntry] = {}

    def last_fired_at(self, session_id: str) -> datetime | None:
        with self._lock:
            entry = self._purge_if_expired(session_id)
            return entry.fired_at if entry is not None else None

    def mark_fired(
        self, session_id: str, recommendation_id: str, valid_until: datetime, now: datetime
    ) -> None:
        with self._lock:
            self._entries[session_id] = _Entry(
                fired_at=now, recommendation_id=recommendation_id, valid_until=valid_until
            )

    def budget_for(self, session_id: str) -> LlmBudget:
        with self._lock:
            now = self._clock()
            entry = self._budgets.get(session_id)
            if entry is not None and (now - entry.last_touched_at).total_seconds() >= self.ttl_sec:
                entry = None  # 한동안(ttl_sec) 접근이 없었다 — 세션이 끝난 것으로 보고 새로 만든다
            if entry is None:
                entry = _BudgetEntry(budget=self._budget_factory(), last_touched_at=now)
            else:
                entry.last_touched_at = now  # 슬라이딩 TTL — 접근할 때마다 만료 시각을 미룬다
            self._budgets[session_id] = entry
            return entry.budget

    def _purge_if_expired(self, session_id: str) -> _Entry | None:
        """호출 시점(락 안)에서만 만료를 판정한다 — 백그라운드 청소 스레드를 두지 않는다.
        조회가 뜸한 세션의 항목은 다음 조회 전까지 메모리에 남아 있을 수 있지만, 세션 수
        규모에서 문제가 될 크기가 아니다."""
        entry = self._entries.get(session_id)
        if entry is None:
            return None
        age_seconds = (self._clock() - entry.fired_at).total_seconds()
        if age_seconds >= self.ttl_sec:
            del self._entries[session_id]
            return None
        return entry


def _now_kst() -> datetime:
    return datetime.now(KST)


__all__ = ["InMemorySessionStore", "SessionStore"]
