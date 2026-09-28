"""주변 따릉이 대여소 후보 생성(S15P21A104-203/302).

**LLM을 쓰지 않는다.** 계획 1절의 ② 노드다 — "어느 대여소로 바꿀 수 있나"는 거리·재고 비교라
규칙으로 전부 결정된다. 여기서 LLM을 쓰면 후보 집합 자체가 매번 달라져 7절 비교의 동등 조건
(`AI/CLAUDE.md` 모델 비교 하드 룰 2번 "표본")이 깨진다. 선택은 ④(전략)의 몫이고, 이 모듈은
**선택지를 좁히기만** 한다.

**순수 함수다.** `StationIndex.nearby()`가 이미 거리순으로 거른 결과를 받아, 대상 대여소
자신과 재고가 확실히 0인 대여소만 더 뺀다. 색인 자체(파일 읽기·mtime 캐시)는 `station_index.py`가
맡고, 이 모듈은 그 결과를 순수하게 가공한다.
"""

from __future__ import annotations

from app.TIME.context import RentalCandidate
from app.TIME.station_index import RentalStation, StationIndex

MAX_CANDIDATES = 5
"""후보 상한. **BE 예산이 아니라 LLM 프롬프트 길이를 지키기 위한 값이다**
(`AGENT_DESIGN.md` 1.3절 — 후보 상한 5가 넘으면 프롬프트가 캐시 프리픽스 밖으로 밀린다).

근거가 강한 숫자는 아니다 — 실제 후보 분포를 보고 조정한다."""


def generate(
    target: RentalStation,
    index: StationIndex,
    *,
    radius_m: int,
    limit: int = MAX_CANDIDATES,
) -> list[RentalCandidate]:
    """대상 대여소 주변의 대체 후보를 뽑는다.

    `index.nearby(target.lat, target.lng, radius_m, limit * 3 + 1)`로 상한보다 넉넉히 더 받는다 —
    대상 자신이 그 안에 낄 것은 확실하지만(거리 0으로 가장 먼저 나온다), 그것만 보고 `limit + 1`만
    받으면 반경 안에 재고 0인 대여소가 여럿일 때 제외 후 `limit`에 못 미칠 수 있다. `*3`은
    메모리 안에서 도는 haversine 정렬이라 비용이 싸서 넉넉히 잡은 값이다 — 근거가 강한 숫자는
    아니고, 실제 대여소 밀도 분포를 보면 다시 조정한다. 대상 자신을 뺀 뒤, 재고가 확실히 0인
    대여소도 뺀다. **`current_stock`이 `None`(모른다)인 대여소는 통과시킨다** — 값 안 지어내기
    원칙: "모른다"를 "비었다"로 읽지 않는다.
    """
    if limit <= 0:
        return []

    pairs = index.nearby(target.lat, target.lng, radius_m, limit * 3 + 1)

    picked: list[RentalCandidate] = []
    for station, distance_m in pairs:
        if station.rental_id == target.rental_id:
            continue  # 대상 자신은 후보가 아니다
        if station.current_stock == 0:
            continue  # 확실히 비어 있다고 알려진 대여소는 대안이 될 수 없다
        picked.append(RentalCandidate(station=station, distance_m=distance_m))
        if len(picked) >= limit:
            break

    return picked


__all__ = ["MAX_CANDIDATES", "generate"]
