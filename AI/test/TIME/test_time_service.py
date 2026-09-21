"""재안내 판정 진입점 검증(S15P21A104-302).

여기서 고정하려는 것은 넷이다.

1. **안 부르는 것** — 트리거가 안 서면 `get_arrivals`·`replan_route`를 부르지 않는다. 폴링이
   30~60초마다 도는데 여기가 새면 BE·LLM 비용이 그대로 곱해진다.
2. **네 상태가 섞이지 않는다** — 특히 `no_alternative`(대안이 없다)와 `unavailable`(물어보지
   못했다). 뭉개면 조회 장애를 "이 경로가 최선"이라고 말하게 된다.
3. **주입** — 전략·가드를 호출자가 넣는다. 전략이 하드코딩되면 204 비교에서 두 전략을 같은
   파이프라인에 태울 수 없고, 가드가 전역이면 동시 사용자끼리 예산을 나눠 쓴다.
4. **예외가 새지 않는다** — 어느 단계에서 터져도 `unavailable`이지 500이 아니다.

실제 네트워크·parquet·LLM을 쓰지 않는다(`test_time_planner.py`와 같은 방침).
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from app.TIME.context import AgentContext, Stop
from app.TIME.guard import ToolGuard
from app.TIME.registry import GET_ARRIVALS, GET_LINE_CONGESTION, REPLAN_ROUTE
from app.TIME.schemas import ToolError
from app.TIME.service import RerouteStatus, propose_reroute
from app.TIME.strategy import SOURCE_ALGORITHM, RerouteProposal, RuleStrategy

NOW = datetime(2026, 9, 20, 8, 20)
"""08:20 — 현재 슬롯 08:00, 15분 뒤 도착이면 08:30 슬롯이다."""

LINE = "2호선"

STOPS = [
    Stop(seq=1, station_id="ST-1", station_no=201, name="역삼"),
    Stop(seq=2, station_id="ST-2", station_no=202, name="강남"),
    Stop(seq=3, station_id="ST-3", station_no=203, name="교대", is_transfer=True),
    Stop(seq=4, station_id="ST-4", station_no=204, name="서초"),
    Stop(seq=5, station_id="ST-5", station_no=205, name="방배"),
]

ETA = {2: 3, 3: 6, 4: 10, 5: 14}
"""현재 위치(seq=1)에서 각 역까지 남은 분."""

LIVE_ARRIVALS = {"status": "LIVE", "trains": [{"train_id": "T-1", "direction": "내선"}]}


# ── 가짜 어댑터 ──


class FakeAdapter:
    """도구 호출을 기록하고 미리 정한 응답을 돌려준다.

    `spike`가 True면 08:30 슬롯의 서초·방배가 지금보다 2등급·30%p 올라 트리거가 선다.
    """

    def __init__(
        self,
        *,
        spike: bool = True,
        arrivals: Any = None,
        replan: Mapping[str, Any] | None = None,
        no_data: bool = False,
    ) -> None:
        self.spike = spike
        self.arrivals = LIVE_ARRIVALS if arrivals is None else arrivals
        self.replan = dict(replan) if replan is not None else None
        self.no_data = no_data
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def call(self, name: str, args: Mapping[str, Any]) -> Any:
        self.calls.append((name, dict(args)))
        if name == GET_LINE_CONGESTION:
            return self._congestion(str(args["time_slot_30min"]))
        if name == GET_ARRIVALS:
            return self.arrivals
        if name == REPLAN_ROUTE:
            if self.replan is None:
                return [_route(minutes=20.0)]
            return self.replan.get(str(args["boundary_id"]), [])
        return ToolError.invalid_input(f"가짜 어댑터가 모르는 도구 '{name}'")

    def count(self, name: str) -> int:
        return sum(1 for called, _ in self.calls if called == name)

    def _congestion(self, slot: str) -> Any:
        if self.no_data:
            # 배치가 안 돈 날. 행은 오지만 값이 null이고 상태가 `no_data`다.
            return {
                "date": "2026-09-20",
                "line": LINE,
                "time_slot_30min": slot,
                "stations": [
                    {
                        "station_no": stop.station_no,
                        "station_name": stop.name,
                        "congestion_pct": None,
                        "grade": None,
                        "data_status": "no_data",
                    }
                    for stop in STOPS
                ],
            }
        rising = self.spike and slot == "08:30"
        stations = [
            {
                "station_no": stop.station_no,
                "station_name": stop.name,
                "congestion_pct": 80.0 if rising and stop.seq >= 4 else 50.0,
                "grade": 3 if rising and stop.seq >= 4 else 1,
                "data_status": "ok",
            }
            for stop in STOPS
        ]
        return {
            "date": "2026-09-20",
            "line": LINE,
            "time_slot_30min": slot,
            "stations": stations,
        }


def _route(*, minutes: float) -> dict[str, Any]:
    return {
        "reason": "BE 고정 문구",
        "source": SOURCE_ALGORITHM,
        "route": {
            "totalMinutes": minutes,
            "transferCount": 0,
            "legs": [{"minutes": minutes, "routeId": "L3"}],
        },
    }


class RecordingStrategy:
    """호출 여부만 보는 전략. `proposal`이 None이면 "고를 게 없다"를 흉내 낸다."""

    def __init__(self, proposal: RerouteProposal | None = None) -> None:
        self.proposal = proposal
        self.seen: list[AgentContext] = []

    def decide(self, ctx: AgentContext) -> RerouteProposal | None:
        self.seen.append(ctx)
        return self.proposal


def run(adapter: FakeAdapter, *, strategy: Any = None, guard: ToolGuard | None = None, **kwargs):
    return propose_reroute(
        stops=STOPS,
        current_seq=1,
        current_station_id="ST-1",
        eta_minutes_by_seq=ETA,
        line=LINE,
        now=NOW,
        dest_station_id="ST-9",
        adapter=adapter,
        guard=guard or ToolGuard(),
        strategy=strategy if strategy is not None else RuleStrategy(),
        **kwargs,
    )


# ── 트리거가 안 서면 아무것도 안 부른다 ──


def test_트리거가_안_서면_도착정보도_경로도_부르지_않는다():
    adapter = FakeAdapter(spike=False)

    outcome = run(adapter)

    assert outcome.status is RerouteStatus.NO_TRIGGER
    assert outcome.proposal is None
    assert adapter.count(GET_ARRIVALS) == 0
    assert adapter.count(REPLAN_ROUTE) == 0


def test_트리거가_안_서면_전략도_부르지_않는다():
    strategy = RecordingStrategy()

    run(FakeAdapter(spike=False), strategy=strategy)

    assert strategy.seen == []


def test_쿨다운_중이면_트리거가_서지_않는다():
    # 같은 이동에서 팝업이 반복해 뜨는 것을 막는다. 혼잡 급등 자체는 그대로다.
    adapter = FakeAdapter(spike=True)

    outcome = run(adapter, seconds_since_last_fire=10.0)

    assert outcome.status is RerouteStatus.NO_TRIGGER
    assert outcome.detail == "cooldown"
    assert adapter.count(REPLAN_ROUTE) == 0


def test_앞쪽_정차역이_없으면_혼잡도도_안_읽는다():
    adapter = FakeAdapter()

    outcome = propose_reroute(
        stops=STOPS,
        current_seq=99,  # 이미 목적지 근처
        current_station_id="ST-5",
        eta_minutes_by_seq=ETA,
        line=LINE,
        now=NOW,
        dest_station_id="ST-9",
        adapter=adapter,
        guard=ToolGuard(),
        strategy=RuleStrategy(),
    )

    assert outcome.status is RerouteStatus.NO_TRIGGER
    assert adapter.calls == []


# ── 네 상태 ──


def test_추천이_나오면_proposal이다():
    outcome = run(FakeAdapter())

    assert outcome.status is RerouteStatus.PROPOSAL
    assert outcome.proposal is not None
    assert outcome.fired
    assert outcome.context is not None


def test_배치_표가_없으면_no_trigger가_아니라_unavailable이다():
    # "혼잡하지 않다"가 아니라 "판단할 근거가 없다"이다. 이 둘을 뭉개면 배치가 멈춘 날
    # 재안내가 조용히 죽은 것을 아무도 모른다.
    outcome = run(FakeAdapter(no_data=True))

    assert outcome.status is RerouteStatus.UNAVAILABLE
    assert outcome.detail == "no_data"


def test_대안이_비면_no_alternative다():
    # BE가 빈 배열을 준 것은 오류가 아니라 "갈아탈 경로가 없다"이다.
    adapter = FakeAdapter(replan={})

    outcome = run(adapter)

    assert outcome.status is RerouteStatus.NO_ALTERNATIVE
    assert adapter.count(REPLAN_ROUTE) > 0


def test_경로_조회가_전부_실패하면_unavailable이다():
    class Failing(FakeAdapter):
        def call(self, name: str, args: Mapping[str, Any]) -> Any:
            result = super().call(name, args)
            if name == REPLAN_ROUTE:
                return ToolError.upstream_unavailable("BE 미기동")
            return result

    outcome = run(Failing())

    assert outcome.status is RerouteStatus.UNAVAILABLE
    assert outcome.detail == "후보 경로 조회 실패"


def test_도착정보를_못_읽으면_no_alternative가_아니라_unavailable이다():
    # `candidates.generate`는 LIVE가 아니면 후보를 만들지 않는다. 그 0개를 "내릴 역이 없다"로
    # 읽으면 조회 장애가 사용자에게 판단으로 전달된다.
    adapter = FakeAdapter(arrivals=ToolError.upstream_unavailable("BE 미기동"))

    outcome = run(adapter)

    assert outcome.status is RerouteStatus.UNAVAILABLE
    assert outcome.detail == "도착 정보를 읽지 못했다"
    assert adapter.count(REPLAN_ROUTE) == 0


def test_운행시간_밖이면_도착정보는_읽혔어도_후보가_없다():
    # status가 LIVE가 아니면 탈 열차를 모른다 — 실패와 같은 칸에 둔다.
    outcome = run(FakeAdapter(arrivals={"status": "OUTSIDE_WINDOW", "trains": []}))

    assert outcome.status is RerouteStatus.UNAVAILABLE


def test_전략이_경로를_하나도_못_읽으면_unavailable이다():
    # 대안은 받았는데 점수를 하나도 못 냈다 = 응답 모양이 예상과 다르다. "대안 없음"이 아니다.
    outcome = run(FakeAdapter(), strategy=RecordingStrategy(proposal=None))

    assert outcome.status is RerouteStatus.UNAVAILABLE
    assert outcome.detail == "전략이 경로를 하나도 읽지 못했다"


# ── 주입 ──


def test_전략을_주입받는다():
    # 204 비교가 같은 파이프라인에 두 전략을 태울 수 있어야 한다.
    picked = RerouteProposal(
        candidate_index=0, route={}, reason="가짜 전략 문장", source="AGENT", score=None
    )
    strategy = RecordingStrategy(proposal=picked)

    outcome = run(FakeAdapter(), strategy=strategy)

    assert outcome.proposal is picked
    assert outcome.proposal.reason == "가짜 전략 문장"
    assert len(strategy.seen) == 1


def test_두_전략이_같은_입력을_본다():
    # 모델 비교 하드 룰 2·3번 — 표현만 다르고 근거는 같아야 한다.
    left, right = RecordingStrategy(), RecordingStrategy()

    run(FakeAdapter(), strategy=left)
    run(FakeAdapter(), strategy=right)

    assert left.seen[0].decision.facts == right.seen[0].decision.facts
    assert len(left.seen[0].usable_candidates) == len(right.seen[0].usable_candidates)


def test_가드를_하나로_공유한다():
    # 파이프라인 전체가 한 인스턴스를 쓴다. 단계마다 새로 만들면 예산이 아무것도 못 막는다.
    guard = ToolGuard()

    run(FakeAdapter(), guard=guard)

    assert guard.total_calls > 0
    assert set(guard.stats()) >= {GET_LINE_CONGESTION, GET_ARRIVALS, REPLAN_ROUTE}


def test_가드_예산이_떨어지면_그_이상_부르지_않는다():
    adapter = FakeAdapter()
    guard = ToolGuard(tool_budgets={REPLAN_ROUTE: 1})

    outcome = run(adapter, guard=guard)

    assert adapter.count(REPLAN_ROUTE) == 1
    # 예산에 막힌 후보는 실패로 남고, 살아남은 후보가 있으면 추천은 그대로 나온다.
    assert outcome.status in {RerouteStatus.PROPOSAL, RerouteStatus.NO_ALTERNATIVE}


# ── 예외가 새지 않는다 ──


def test_전략이_터져도_예외가_새지_않는다():
    class Exploding:
        def decide(self, ctx: AgentContext) -> RerouteProposal | None:
            raise RuntimeError("전략 내부 버그")

    outcome = run(FakeAdapter(), strategy=Exploding())

    assert outcome.status is RerouteStatus.UNAVAILABLE
    assert "RuntimeError" in (outcome.detail or "")


def test_어댑터가_터져도_예외가_새지_않는다():
    class Exploding(FakeAdapter):
        def call(self, name: str, args: Mapping[str, Any]) -> Any:
            raise ValueError("어댑터 내부 버그")

    outcome = run(Exploding())

    assert outcome.status is RerouteStatus.UNAVAILABLE
    assert outcome.proposal is None


def test_정차역_목록이_비어도_죽지_않는다():
    outcome = propose_reroute(
        stops=[],
        current_seq=1,
        current_station_id="ST-1",
        eta_minutes_by_seq={},
        line=LINE,
        now=NOW,
        dest_station_id="ST-9",
        adapter=FakeAdapter(),
        guard=ToolGuard(),
        strategy=RuleStrategy(),
    )

    assert outcome.status is RerouteStatus.NO_TRIGGER
