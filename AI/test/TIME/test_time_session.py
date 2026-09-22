"""세션 쿨다운 보관소 검증(S15P21A104-302).

`InMemorySessionStore`가 지켜야 하는 것 셋 — ① TTL이 지나면 `last_fired_at`이 `None`이 된다
(파드 1개 전제·Redis로 바꿀 자리, `session.py` 모듈 docstring), ② 세션끼리 기록이 섞이지 않는다,
③ 동시 접근에서 죽거나 기록을 잃지 않는다(`guard.ToolGuard`와 같은 락 근거).
"""

from __future__ import annotations

import threading
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.TIME.session import InMemorySessionStore

KST = ZoneInfo("Asia/Seoul")
NOW = datetime(2026, 9, 22, 12, 0, tzinfo=KST)


class _MutableClock:
    """테스트가 시간을 앞으로 돌릴 수 있게 하는 가짜 시계(`guard.ToolGuard` 테스트와 같은 방식)."""

    def __init__(self, start: datetime) -> None:
        self.value = start

    def __call__(self) -> datetime:
        return self.value


# ── mark_fired / last_fired_at ──


def test_mark_fired_후_last_fired_at은_기록된_시각을_돌려준다():
    store = InMemorySessionStore(ttl_sec=600.0, clock=lambda: NOW)

    store.mark_fired("S-1", "REC-1", NOW + timedelta(minutes=10), now=NOW)

    assert store.last_fired_at("S-1") == NOW


def test_기록이_없는_세션은_None이다():
    store = InMemorySessionStore(ttl_sec=600.0)

    assert store.last_fired_at("NOPE") is None


def test_재발화는_기록을_덮어쓴다():
    clock = _MutableClock(NOW)
    store = InMemorySessionStore(ttl_sec=600.0, clock=clock)
    store.mark_fired("S-1", "REC-1", NOW + timedelta(minutes=10), now=NOW)

    later = NOW + timedelta(seconds=100)
    clock.value = later
    store.mark_fired("S-1", "REC-2", later + timedelta(minutes=10), now=later)

    assert store.last_fired_at("S-1") == later


# ── TTL 만료 ──


def test_ttl이_지나기_전에는_그대로_돌려준다():
    clock = _MutableClock(NOW)
    store = InMemorySessionStore(ttl_sec=600.0, clock=clock)
    store.mark_fired("S-1", "REC-1", NOW + timedelta(minutes=10), now=NOW)

    clock.value = NOW + timedelta(seconds=599)

    assert store.last_fired_at("S-1") == NOW


def test_ttl_경계값은_만료로_본다():
    clock = _MutableClock(NOW)
    store = InMemorySessionStore(ttl_sec=600.0, clock=clock)
    store.mark_fired("S-1", "REC-1", NOW + timedelta(minutes=10), now=NOW)

    clock.value = NOW + timedelta(seconds=600)

    assert store.last_fired_at("S-1") is None


def test_ttl이_지나면_기록_자체가_지워진다():
    clock = _MutableClock(NOW)
    store = InMemorySessionStore(ttl_sec=600.0, clock=clock)
    store.mark_fired("S-1", "REC-1", NOW + timedelta(minutes=10), now=NOW)

    clock.value = NOW + timedelta(seconds=1000)
    assert store.last_fired_at("S-1") is None

    # 지워진 뒤 시계를 되돌려도(현실에선 없는 상황이지만) 옛 기록이 되살아나지 않는다 —
    # purge가 조회를 "만료로 본 순간" 실제로 dict에서 지운다는 것을 확인한다.
    clock.value = NOW + timedelta(seconds=100)
    assert store.last_fired_at("S-1") is None


# ── 세션 격리 ──


def test_세션끼리_격리된다():
    store = InMemorySessionStore(ttl_sec=600.0, clock=lambda: NOW)
    store.mark_fired("S-1", "REC-1", NOW + timedelta(minutes=10), now=NOW)

    assert store.last_fired_at("S-2") is None


def test_다른_세션은_서로_다른_시각을_기억한다():
    clock = _MutableClock(NOW)
    store = InMemorySessionStore(ttl_sec=600.0, clock=clock)
    store.mark_fired("S-1", "REC-1", NOW + timedelta(minutes=10), now=NOW)

    later = NOW + timedelta(seconds=200)
    clock.value = later
    store.mark_fired("S-2", "REC-2", later + timedelta(minutes=10), now=later)

    assert store.last_fired_at("S-1") == NOW
    assert store.last_fired_at("S-2") == later


# ── 동시성 스모크 ──


def test_동시_접근에서_예외_없이_동작한다():
    store = InMemorySessionStore(ttl_sec=600.0, clock=lambda: NOW)
    errors: list[BaseException] = []

    def _worker(i: int) -> None:
        session_id = f"S-{i % 5}"
        try:
            for _ in range(50):
                store.mark_fired(session_id, "REC", NOW + timedelta(minutes=10), now=NOW)
                store.last_fired_at(session_id)
        except BaseException as exc:  # noqa: BLE001 - 스모크 테스트라 무엇이든 잡아서 보고한다
            errors.append(exc)

    threads = [threading.Thread(target=_worker, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
    for i in range(5):
        assert store.last_fired_at(f"S-{i}") == NOW
