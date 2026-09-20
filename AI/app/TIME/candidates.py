"""하차 후보역 생성(S15P21A104-203).

**LLM을 쓰지 않는다.** 계획 1절의 ② 노드다 — "어느 역에서 내릴 수 있나"는 순서·구간 비교라
규칙으로 전부 결정된다. 여기서 LLM을 쓰면 후보 집합 자체가 매번 달라져 7절 비교의 동등 조건
(`AI/CLAUDE.md` 모델 비교 하드 룰 2번 "표본")이 깨진다. 선택은 ④(전략)의 몫이고, 이 모듈은
**선택지를 좁히기만** 한다.

**순수 함수다.** 정차역 목록·트리거 판정·`get_arrivals` 응답·역별 소요시간을 전부 인자로 받는다.

- 정차역 목록을 인자로 받는 이유는 `context.py` 모듈 docstring에 적힌 그대로다 — BE
  `RouteLegResponse`가 같은 노선 연속 구간을 leg 하나로 합쳐 중간 정차역이 응답에 없고, 그
  공급원은 아직 회신 대기(`TO_BE-time-station-sequence-01`)다. 공급원이 정해지면 호출자만
  바뀐다.
- `get_arrivals` 응답도 받기만 한다. 도구 호출은 `ToolGuard`를 거쳐야 하는데(202의 예산·로그),
  후보 생성이 직접 부르면 같은 폴링에서 예산을 두 군데가 나눠 쓰게 된다. 호출은 `planner.py`가
  모아서 한다.
- 소요시간도 받기만 한다. 여기서 추정하면 트리거가 쓴 `eta_minutes`와 다른 값이 나와, 같은
  역에 대해 "10분 뒤 혼잡"과 "12분 뒤 도착"이 한 문장에 섞인다.
"""

from __future__ import annotations

import logging
from typing import Any, Mapping, Sequence

from app.TIME.context import DropCandidate, Stop
from app.TIME.trigger import TriggerDecision

_log = logging.getLogger(__name__)

MAX_CANDIDATES = 5
"""후보 상한. 협의 문서 6절에서 BE에 통지한 값이라 임의로 올리지 않는다.

근거가 강한 숫자는 아니다(계획 11절 "다른 판단이 가능한 곳") — 실제 노선의 환승 가능 역 수를
보고 조정하되, 바꿀 때는 BE와 같이 바꾼다.
"""

ARRIVAL_STATUS_LIVE = "LIVE"
"""`get_arrivals`의 4종 status 중 후보를 만들어도 되는 유일한 값(`registry.py` 참고)."""

RANK_TRANSFER = 0
"""환승 가능 역. 갈아탈 수 있는 역이 먼저 보이는 편이 낫다."""

RANK_PLAIN = 1
"""그 밖의 역. **`is_transfer`를 모르는 역도 여기 들어온다** — 아래 `_rank_hint` 주석 참고."""


def generate(
    stops: Sequence[Stop],
    decision: TriggerDecision,
    *,
    current_seq: int,
    eta_minutes_by_seq: Mapping[int, int],
    arrivals: Mapping[str, Any] | None,
    dest_station_id: str | None = None,
    dest_seq: int | None = None,
    limit: int = MAX_CANDIDATES,
) -> list[DropCandidate]:
    """트리거 구간 진입 전에 내릴 수 있는 역들을 뽑는다.

    `stops`는 경로상 정차역 전부다. 순서는 `Stop.seq`로만 판단하므로 인자의 나열 순서는 보지
    않는다 — 공급원이 정해지지 않은 목록이라(위 docstring) 정렬을 호출자에게 기대하지 않는다.

    `current_seq`는 현재 위치 역의 `seq`다. **그 역 자신은 후보가 아니다** — 안내가 뜬 시점에
    이미 정차 중이거나 막 떠난 역이라 행동할 수 없다.

    `eta_minutes_by_seq`는 현재 위치에서 각 역까지 걸리는 분. 여기 없는 역은 후보에서 뺀다.
    소요시간을 지어내느니 후보 하나를 잃는 쪽이 낫다(값 안 지어내기 원칙).

    `arrivals`는 `get_arrivals` 응답 그대로이거나 None이다. 호출하지 않았거나 실패했으면 None을
    넘긴다.

    목적지는 `dest_station_id`(BE `replan`의 키)로 찾고, 못 찾으면 `dest_seq`로 찾는다. 둘 다
    없으면 **`stops`의 마지막 역을 목적지로 본다** — `replan` 계약상 경로는 목적지에서 끝난다
    (`registry.py` REPLAN_ROUTE 설명). 목적지를 모른 채 두면 "목적지에서 내려 갈아타세요"라는
    무의미한 안내가 나올 수 있어, 모를 때 후보를 넓히는 쪽으로 기울이지 않았다.

    반환 순서는 `rank_hint` → `seq`다. **최종 선택은 하지 않는다**(`DropCandidate.rank_hint` 참고).
    """
    if limit <= 0:
        return []

    # ── get_arrivals가 LIVE가 아니면 후보를 만들지 않는다 ──
    # 지금 어느 열차에 타고 있는지 모르는 채로 "여기서 내리세요"를 말할 수 없기 때문이다.
    # NO_INFO·OUTSIDE_WINDOW는 애초에 탑승 중이라고 볼 근거가 없고, STALE은 값이 오래돼
    # 지금쯤 어느 역을 지났는지 어긋날 수 있다 — 어긋난 채로 안내하면 이미 지나친 역에서
    # 내리라고 하게 된다. 셋을 구분해 다르게 대우할 실익이 없어 한 갈래로 묶었다.
    # arrivals가 None인 경우(호출 안 함 / ToolError)도 같은 자리에 둔다. "조회하지 못했다"는
    # LIVE가 아니며, 모르는 것을 아는 것처럼 쓰지 않는다. 폴링마다 도는 기능이라 한 번 걸러도
    # 다음 폴링에서 다시 기회가 온다 — 막히는 쪽으로 기울여도 잃는 것이 적다.
    if not _is_live(arrivals):
        return []

    # 트리거가 안 떴으면 재안내 자체가 없다. 구간이 비어 있어 아래 경계 계산도 성립하지 않는다.
    if not decision.fired:
        return []

    boundary_seq = _segment_entry_seq(stops, decision)
    if boundary_seq is None:
        # 혼잡 구간이 정차역 목록의 어디인지 못 짚은 상태다(station_no 미매칭 —
        # `TO_BE-time-station-sequence-01`). 경계를 모르면 혼잡 구간 안쪽 역을 후보로 낼 수
        # 있으므로 아무것도 내지 않는다.
        return []

    dest_seq_resolved = _dest_seq(stops, dest_station_id, dest_seq)

    picked: list[DropCandidate] = []
    for stop in sorted(stops, key=lambda s: s.seq):
        if stop.seq <= current_seq:
            continue  # 이미 지난 역
        if stop.seq >= boundary_seq:
            continue  # 혼잡 구간 진입 이후 — 여기서 내려도 의미가 없다
        if dest_seq_resolved is not None and stop.seq >= dest_seq_resolved:
            continue  # 목적지(와 그 너머). 거기까지 가면 재안내가 필요 없다
        eta = eta_minutes_by_seq.get(stop.seq)
        if eta is None:
            continue
        picked.append(DropCandidate(stop=stop, eta_minutes=int(eta), rank_hint=_rank_hint(stop)))
        if len(picked) >= limit:
            break

    # 상한은 **가까운 역부터** 채우고(위 루프가 seq 순), 정렬은 그 뒤에 한다.
    # 환승 우대로 상한을 채우면 멀리 있는 환승역만 남아 정작 지금 내릴 수 있는 역이 잘려나간다 —
    # 우대는 "같은 선택지 안에서 뭘 먼저 보여줄까"이지 선택지를 바꾸는 힘이 아니다.
    picked.sort(key=lambda c: (c.rank_hint, c.stop.seq))
    return picked


def _is_live(arrivals: Mapping[str, Any] | None) -> bool:
    """`get_arrivals` 응답이 실시간인지.

    `trains`는 보지 않는다. 비어 있어도 오류가 아니고(`registry.py`), 어느 열차를 쓸지 고르는
    것은 이 모듈의 일이 아니다. ToolError 딕셔너리에는 `status`가 없어 자연히 False가 된다.
    """
    if arrivals is None:
        return False
    return arrivals.get("status") == ARRIVAL_STATUS_LIVE


def _segment_entry_seq(stops: Sequence[Stop], decision: TriggerDecision) -> int | None:
    """혼잡 구간에 처음 들어가는 역의 `seq`. 짚지 못하면 None.

    구간의 **모든** 역을 찾아 그중 가장 이른 `seq`를 쓴다. `TriggerDecision.segment`는 진행
    순서대로지만 그 순서가 `Stop.seq`와 같은지는 보장되지 않는다 — 두 목록의 공급원이 다르다.
    일부만 매칭돼도 가장 이른 것을 경계로 삼으면 안전한 쪽(후보가 줄어드는 쪽)으로 틀린다.
    """
    segment_nos = {r.station_no for r in decision.segment}
    if not segment_nos:
        return None
    seqs = [s.seq for s in stops if s.station_no is not None and s.station_no in segment_nos]
    if seqs:
        return min(seqs)

    # 여기부터는 경계를 못 짚은 경우다. 두 가지가 섞여 있는데 성격이 전혀 다르다.
    #
    #  ⑴ station_no가 채워진 역은 있는데 구간과 안 겹친다 → 정상적인 데이터 상황.
    #     (트리거가 본 노선과 이 경로의 구간이 다를 수 있다.) 조용히 후보 없음으로 둔다.
    #  ⑵ 어느 역에도 station_no가 없다 → **배선 실수**다. 호출자가 Stop.station_no를 안 채웠다.
    #     이 경우 기능은 영원히 발동하지 않으면서 오류도 안 난다 — 정상 동작과 구분되지 않는
    #     조용한 실패라 로그로 드러낸다(`TO_BE-time-station-sequence-01` 3번, ID 체계 미확정).
    if stops and all(stop.station_no is None for stop in stops):
        _log.warning(
            "정차역 %d개 중 station_no가 채워진 것이 하나도 없어 혼잡 구간 경계를 짚지 못했다 — "
            "호출자가 Stop.station_no를 채우지 않았을 가능성이 높다(재안내가 영영 발동하지 않는다).",
            len(stops),
        )
    return None


def _dest_seq(
    stops: Sequence[Stop], dest_station_id: str | None, dest_seq: int | None
) -> int | None:
    """목적지 역의 `seq`. 정차역이 없으면 None."""
    if dest_station_id is not None:
        for stop in stops:
            if stop.station_id == dest_station_id:
                return stop.seq
    if dest_seq is not None:
        return dest_seq
    if not stops:
        return None
    return max(s.seq for s in stops)


def _rank_hint(stop: Stop) -> int:
    """환승역에 주는 약한 우대.

    **환승역이 아니라고 후보에서 빼지 않는다.** `Stop.is_transfer`는 모르면 False라(기본값),
    빼는 쪽으로 만들면 환승 정보가 아직 안 붙은 지금 후보가 전부 사라지고, 정보가 붙은 뒤에도
    누락된 역 하나가 통째로 안 보이게 된다. False는 "환승역이 아니다"가 아니라 "환승역인지
    모른다"에 가깝다 — 모른다고 배제하지 않는 것이 이 프로젝트의 결측 처리 방식이다.
    """
    return RANK_TRANSFER if stop.is_transfer else RANK_PLAIN
