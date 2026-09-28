"""세션 쿨다운 보관소 검증(S15P21A104-302/324).

`InMemorySessionStore`가 지켜야 하는 것 셋 — ① TTL이 지나면 `last_fired_at`이 `None`이 된다
(파드 1개 전제·Redis로 바꿀 자리, `session.py` 모듈 docstring), ② 세션끼리 기록이 섞이지 않는다,
③ 동시 접근에서 죽거나 기록을 잃지 않는다(`guard.ToolGuard`와 같은 락 근거).

324-3: `budget_for()`가 지켜야 하는 것 셋 — ① 같은 세션이면 같은 `LlmBudget` **인스턴스**를
돌려준다(그래야 `.check()`/`.record()`가 쌓인다), ② 세션끼리 예산이 섞이지 않는다, ③ 한동안
(`ttl_sec`) 접근이 없으면 다음 접근에서 새 예산으로 초기화된다(슬라이딩 TTL — 접근할 때마다
만료 시각이 밀린다).
"""

from __future__ import annotations

import threading
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.TIME.llm import LlmResult
from app.TIME.llm_budget import LlmBudget
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


# ── 324-3: budget_for ──


def test_같은_세션은_같은_budget_인스턴스를_돌려받는다():
    store = InMemorySessionStore(ttl_sec=600.0, clock=lambda: NOW)

    first = store.budget_for("S-1")
    first.calls = 2  # 상태를 표식 삼아 남긴다 — 같은 인스턴스인지는 이 상태가 보이는지로 안다

    second = store.budget_for("S-1")

    assert second is first
    assert second.calls == 2


def test_budget는_check_record로_누적된다():
    store = InMemorySessionStore(ttl_sec=600.0, clock=lambda: NOW)

    budget = store.budget_for("S-1")
    assert budget.check() is None
    budget.record(LlmResult(text="x", input_tokens=10, output_tokens=5, latency_ms=1.0, model="m"))

    # 두 번째 조회도 같은 인스턴스라 누적된 상태를 그대로 본다.
    assert store.budget_for("S-1").calls == 1
    assert store.budget_for("S-1").total_tokens == 15


def test_세션끼리_budget이_섞이지_않는다():
    store = InMemorySessionStore(ttl_sec=600.0, clock=lambda: NOW)

    budget_1 = store.budget_for("S-1")
    budget_2 = store.budget_for("S-2")

    assert budget_1 is not budget_2


def test_budget_factory로_한도를_지정할_수_있다():
    store = InMemorySessionStore(
        ttl_sec=600.0, clock=lambda: NOW, budget_factory=lambda: LlmBudget(max_calls=1)
    )

    budget = store.budget_for("S-1")

    assert budget.max_calls == 1


def test_ttl_동안_접근이_없으면_다음_접근에서_새_budget으로_초기화된다():
    clock = _MutableClock(NOW)
    store = InMemorySessionStore(ttl_sec=600.0, clock=clock)
    first = store.budget_for("S-1")
    first.calls = 3  # 예산을 다 쓴 상태를 흉내낸다

    clock.value = NOW + timedelta(seconds=600)  # 마지막 접근(생성) 이후 ttl_sec 이상 지났다

    second = store.budget_for("S-1")

    assert second is not first
    assert second.calls == 0


def test_ttl_안에서_폴링이_이어지면_budget이_살아있다():
    """접근할 때마다 만료 시각이 밀리는 슬라이딩 TTL — ttl_sec을 훌쩍 넘는 총 경과 시간이어도
    접근 간격이 매번 ttl_sec보다 짧으면 예산이 리셋되지 않는다."""
    clock = _MutableClock(NOW)
    store = InMemorySessionStore(ttl_sec=600.0, clock=clock)
    first = store.budget_for("S-1")
    first.calls = 2

    for _ in range(5):
        clock.value = clock.value + timedelta(seconds=120)  # ttl_sec(600)보다 짧은 간격
        touched = store.budget_for("S-1")
        assert touched is first
        assert touched.calls == 2
