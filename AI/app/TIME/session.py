"""재안내 세션 쿨다운 보관소(S15P21A104-302).

**파드 1개를 전제한다.** 세션 상태를 프로세스 메모리 dict에 둔다 — 여러 파드로 수평 확장하면
사용자 요청이 매번 다른 파드에 붙을 수 있어 쿨다운이 파드마다 따로 논다. 지금은 그 상황이 아니라
(`AI/CLAUDE.md` 현재 상태), 미룰 수 있는 선택이다. Redis 등 공유 저장소로 바꿀 자리는 이미 표시돼
있다 — `SessionStore` Protocol만 지키면 `router.py`는 구현이 바뀐 줄도 모른다
(`AI/app/TIME/AGENT_DESIGN.md` §3.2 "TTL 보관소는 router.py의 몫"과 같은 결의 결정).

`guard.ToolGuard`와 같은 이유로 **세션 단위가 아니라 전역 인스턴스 하나를 여러 세션이 공유한다** —
이건 `ToolGuard`(세션마다 새로 만든다)와 반대다. 쿨다운은 "이 세션이 최근에 언제 팝업을 띄웠나"를
여러 요청(폴링)에 걸쳐 기억해야 하는 값이라, 요청마다 버리면 쿨다운 자체가 의미가 없다.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from zoneinfo import ZoneInfo

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


@dataclass(frozen=True, slots=True)
class _Entry:
    fired_at: datetime
    recommendation_id: str
    valid_until: datetime


class InMemorySessionStore:
    """프로세스 메모리 dict 기반 `SessionStore`. TTL이 지난 항목은 조회 시점에 지운다(lazy purge).

    **TTL은 쿨다운 기간과 같은 값을 쓴다** — `router.py`가
    `InMemorySessionStore(ttl_sec=settings.time_trigger_cooldown_sec)`로 만든다. 쿨다운이
    끝난 세션의 발화 기록은 더 볼 일이 없으므로, 별도 만료 정책 없이 같은 숫자를 재사용한다.

    시계는 생성자로 주입받는다(`clock`, 기본은 KST 현재 시각) — `guard.ToolGuard`와 같은 이유로
    테스트가 시간을 앞으로 돌릴 수 있게 열어둔다.
    """

    def __init__(self, ttl_sec: float, clock: Callable[[], datetime] | None = None) -> None:
        self.ttl_sec = ttl_sec
        self._clock = clock if clock is not None else _now_kst
        # `ToolGuard`와 같은 이유의 락 — read-modify-write(purge 후 재삽입)가 섞여 있어
        # 락이 없으면 동시 요청에서 기록이 유실될 수 있다.
        self._lock = threading.RLock()
        self._entries: dict[str, _Entry] = {}

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
