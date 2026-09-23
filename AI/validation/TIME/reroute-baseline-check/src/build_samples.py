"""331 — 재안내 규칙·에이전트 비교용 합성 표본 생성.

`AgentContext`를 만드는 방식은 `AI/test/TIME/test_time_strategy.py`의 `station`·`reading`·
`candidate`·`fired_ctx` 헬퍼 **패턴을 그대로 따른다**(같은 필드 구성, 값만 다르게 채운다) —
두 전략이 같은 입력을 보게 하는 203/302 설계 전제를 표본 생성에서도 지키기 위해서다.
`AI/test/TIME`을 직접 import하지는 않는다 — `test/`는 basename으로 모듈을 식별하는 pytest
전용 구조라(`AI/CLAUDE.md` `test/` 규약) 외부 스크립트가 끌어다 쓰는 자리가 아니다. 그래서
로직만 재현했다.

## 표본 구성(기본 8건, `--n`으로 조절)

`AI/CLAUDE.md`의 "동등 조건" 원칙(하드 룰)에 따라 8건 전부 같은 `Thresholds`·같은 도보 속도
가정으로 트리거가 이미 선 상태(`fired=True`)에서 시작한다 — 두 전략이 후보를 고르는 지점만
비교하려는 것이지 트리거 판정 자체를 비교하는 것이 아니다. 각 표본은 `trigger.evaluate()`를
실제로 통과시켜 `TriggerResult`를 만든다(손으로 값을 지어 넣지 않는다) — 설계값이 실제로
트리거를 세우는지 스스로 검증하는 효과가 있다.

8개 시나리오가 요구된 다양성 축을 각각 대표한다:

1. `large_score_gap`      — 후보 2개, 점수 차 큼(가깝고 안전 vs 멀고 위험)
2. `small_score_gap`      — 후보 2개, 점수 차 작음(거의 동점)
3. `single_candidate`     — 후보 1개(LLM을 아예 안 부르는 지름길 경로)
4. `near_risky_far_safe`  — 가깝지만 재고 불안한 후보 vs 멀지만 안정적인 후보
5. `many_candidates`      — 후보 4개, 점수 분포가 넓다
6. `proxy_predicted_stock`— 후보의 `p_empty`가 없어 `predicted_stock` 근사(proxy)로만 판단
7. `low_confidence_facts` — `facts`가 다른 값(호라이즌 상한 근처 ETA·p_full 존재 등)을 쓴다
8. `three_candidates_close` — 후보 3개, 인접 점수가 촘촘해 순위가 민감하다

`--n`이 8과 다르면 이 시나리오를 순서대로 순환하며 채운다(표본 인덱스가 대여소 ID에 그대로
들어가 순환해도 ID가 겹치지 않는다).

## `--from-parquet`

실제 `latest_stock.parquet`이 있으면 그 스냅샷에서 **현재 재고가 1대 이하인(고갈 임박)** 대여소
상위 N곳을 대상으로 표본을 만든다. 대상·후보의 위치·이름·현재 재고는 스냅샷 실측값 그대로다.
다만 이 폴더에는 학습된 예측 모델 아티팩트가 없어 `predicted_stock`·`p_empty`·
`model_horizon_min`은 **모델 출력이 아니라 문서화된 근사치**다 — 없는 값을 지어내는 것과
구분하려고 근사 규칙을 명시한다: `predicted_stock`은 "현재 재고가 그대로 유지된다"는 보수적
가정(persistence)으로 `current_stock`을 그대로 쓰고, `p_empty`는 `strategy._p_empty_or_proxy`와
같은 형식의 이진 근사(`predicted_stock <= 1` → 0.9, 아니면 0.1)를 쓰며, `model_horizon_min`은
`eta_minutes`와 같은 고정값(10분, 근거 없음)을 쓴다. `source`는 `"parquet_naive_proxy"`로 못박아
실제 LightGBM 산출(`lightgbm`)과 절대 섞이지 않게 한다. 파일이 없으면 값을 지어내는 대신
**명확한 오류 메시지만 내고 종료한다**(0이 아닌 종료 코드).
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
AI_ROOT = _HERE.parents[3]
if str(AI_ROOT) not in sys.path:
    sys.path.insert(0, str(AI_ROOT))
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from samples_io import to_json, write_samples  # noqa: E402

from app.TIME import candidates as candidates_mod  # noqa: E402
from app.TIME import trigger  # noqa: E402
from app.TIME.context import AgentContext, CandidateContext, RentalCandidate  # noqa: E402
from app.TIME.station_index import ParquetStationIndex, RentalStation  # noqa: E402
from app.TIME.trigger import StockReading  # noqa: E402

DEFAULT_OUT = _HERE.parent / "samples" / "samples.json"

# 스냅샷 실측 모드에서 모델이 없을 때 쓰는 근사 표시값. 실제 예측(`lightgbm`)과 절대 안 섞이게
# 이름을 다르게 둔다.
PARQUET_PROXY_SOURCE = "parquet_naive_proxy"
PARQUET_ASSUMED_ETA_MIN = 10
PARQUET_NEARBY_RADIUS_M = 500  # Settings.time_nearby_radius_m 기본값과 같다
PARQUET_NEARBY_LIMIT = 5  # Settings.time_nearby_limit 기본값과 같다


# ── 공통 팩토리(테스트 픽스처 패턴 재현) ──


def _station(
    rental_id: str,
    *,
    name: str | None,
    lat: float = 37.5,
    lng: float = 127.0,
    rack_count: int | None = 10,
    current_stock: int | None = 5,
) -> RentalStation:
    return RentalStation(
        rental_id=rental_id,
        name=name,
        lat=lat,
        lng=lng,
        rack_count=rack_count,
        current_stock=current_stock,
        updated_at=None,
    )


def _reading(
    *,
    current_stock: int | None,
    predicted_stock: float | None,
    p_empty: float | None,
    p_full: float | None = 0.0,
    source: str | None = "lightgbm",
    model_horizon_min: int | None = 10,
) -> StockReading:
    return StockReading(
        current_stock=current_stock,
        predicted_stock=predicted_stock,
        p_empty=p_empty,
        p_full=p_full,
        source=source,
        model_horizon_min=model_horizon_min,
    )


def _candidate_ctx(
    rental_id: str,
    *,
    name: str,
    distance_m: float,
    lat: float = 37.5,
    lng: float = 127.0,
    **reading_kwargs: Any,
) -> CandidateContext:
    return CandidateContext(
        candidate=RentalCandidate(
            station=_station(rental_id, name=name, lat=lat, lng=lng), distance_m=distance_m
        ),
        reading=_reading(**reading_kwargs),
    )


def _fired_ctx(
    *cand_ctxs: CandidateContext,
    target: RentalStation,
    target_reading: StockReading,
    eta_minutes: int,
    dest_station_id: str | None = None,
) -> AgentContext:
    """`trigger.evaluate()`를 실제로 통과시켜 `TriggerResult`를 얻는다 — 손으로 `facts`를
    지어 넣지 않는다. `fired=False`가 나오면 표본 설계값이 잘못된 것이라 즉시 예외로 드러낸다."""
    decision = trigger.evaluate(target_reading, eta_minutes=eta_minutes)
    if not decision.fired:
        raise AssertionError(
            f"표본 설계값이 트리거를 세우지 못했다(reason={decision.reason}) — "
            "target_reading·eta_minutes를 다시 맞춰야 한다."
        )
    return AgentContext(
        decision=decision,
        target=target,
        target_reading=target_reading,
        eta_minutes=eta_minutes,
        candidates=list(cand_ctxs),
        dest_station_id=dest_station_id,
    )


# ── 시나리오 ──


def _scenario_large_score_gap(i: int) -> AgentContext:
    target = _station(f"TARGET-{i}", name="역삼")
    target_reading = _reading(current_stock=0, predicted_stock=0.2, p_empty=0.92)
    near_safe = _candidate_ctx(
        f"C{i}A", name="교대", distance_m=80.0, current_stock=6, predicted_stock=5.5, p_empty=0.05
    )
    far_risky = _candidate_ctx(
        f"C{i}B", name="사당", distance_m=900.0, current_stock=1, predicted_stock=0.8, p_empty=0.85
    )
    return _fired_ctx(
        near_safe, far_risky, target=target, target_reading=target_reading, eta_minutes=10
    )


def _scenario_small_score_gap(i: int) -> AgentContext:
    target = _station(f"TARGET-{i}", name="잠실")
    target_reading = _reading(current_stock=0, predicted_stock=0.4, p_empty=0.8)
    a = _candidate_ctx(
        f"C{i}A",
        name="잠실나루",
        distance_m=150.0,
        current_stock=3,
        predicted_stock=2.8,
        p_empty=0.4,
    )
    b = _candidate_ctx(
        f"C{i}B",
        name="종합운동장",
        distance_m=170.0,
        current_stock=3,
        predicted_stock=2.6,
        p_empty=0.38,
    )
    return _fired_ctx(a, b, target=target, target_reading=target_reading, eta_minutes=8)


def _scenario_single_candidate(i: int) -> AgentContext:
    target = _station(f"TARGET-{i}", name="홍대입구")
    target_reading = _reading(current_stock=0, predicted_stock=0.3, p_empty=0.88)
    only = _candidate_ctx(
        f"C{i}A", name="합정", distance_m=120.0, current_stock=4, predicted_stock=3.5, p_empty=0.15
    )
    return _fired_ctx(only, target=target, target_reading=target_reading, eta_minutes=12)


def _scenario_near_risky_far_safe(i: int) -> AgentContext:
    target = _station(f"TARGET-{i}", name="강남")
    target_reading = _reading(current_stock=1, predicted_stock=0.6, p_empty=0.75)
    near_risky = _candidate_ctx(
        f"C{i}A", name="역삼", distance_m=90.0, current_stock=2, predicted_stock=1.0, p_empty=0.75
    )
    far_safe = _candidate_ctx(
        f"C{i}B",
        name="양재",
        distance_m=700.0,
        current_stock=8,
        predicted_stock=7.5,
        p_empty=0.05,
    )
    return _fired_ctx(
        near_risky, far_safe, target=target, target_reading=target_reading, eta_minutes=9
    )


def _scenario_many_candidates(i: int) -> AgentContext:
    target = _station(f"TARGET-{i}", name="서울역")
    target_reading = _reading(current_stock=0, predicted_stock=0.1, p_empty=0.95)
    specs = [
        ("남대문", 100.0, 5, 4.5, 0.1),
        ("회현", 300.0, 3, 2.8, 0.3),
        ("숙대입구", 500.0, 4, 3.9, 0.2),
        ("공덕", 150.0, 1, 0.9, 0.6),
    ]
    cand_ctxs = [
        _candidate_ctx(
            f"C{i}{idx}",
            name=name,
            distance_m=dist,
            current_stock=cur,
            predicted_stock=pred,
            p_empty=pe,
        )
        for idx, (name, dist, cur, pred, pe) in enumerate(specs)
    ]
    return _fired_ctx(*cand_ctxs, target=target, target_reading=target_reading, eta_minutes=15)


def _scenario_proxy_predicted_stock(i: int) -> AgentContext:
    """후보·대상 둘 다 `p_empty`가 없어 `predicted_stock` 근사(proxy)만으로 점수가 매겨진다
    (`strategy._p_empty_or_proxy`)."""
    target = _station(f"TARGET-{i}", name="여의도")
    target_reading = _reading(current_stock=0, predicted_stock=0.4, p_empty=None)
    risky_proxy = _candidate_ctx(
        f"C{i}A", name="당산", distance_m=200.0, current_stock=1, predicted_stock=0.5, p_empty=None
    )
    safe_proxy = _candidate_ctx(
        f"C{i}B",
        name="영등포",
        distance_m=350.0,
        current_stock=6,
        predicted_stock=4.0,
        p_empty=None,
    )
    return _fired_ctx(
        risky_proxy, safe_proxy, target=target, target_reading=target_reading, eta_minutes=11
    )


def _scenario_low_confidence_facts(i: int) -> AgentContext:
    """`facts`가 다른 값(ETA가 상한 30분에 가깝고, `p_full`이 0이 아닌 값)을 쓰는 표본 —
    다른 시나리오와 `decision.facts` 집합 자체가 달라진다."""
    target = _station(f"TARGET-{i}", name="건대입구")
    target_reading = _reading(
        current_stock=1, predicted_stock=0.9, p_empty=0.72, p_full=0.05, model_horizon_min=30
    )
    a = _candidate_ctx(
        f"C{i}A",
        name="성수",
        distance_m=250.0,
        current_stock=5,
        predicted_stock=4.2,
        p_empty=0.12,
        p_full=0.1,
        model_horizon_min=30,
    )
    b = _candidate_ctx(
        f"C{i}B",
        name="뚝섬",
        distance_m=600.0,
        current_stock=2,
        predicted_stock=1.8,
        p_empty=0.3,
        p_full=0.0,
        model_horizon_min=30,
    )
    return _fired_ctx(a, b, target=target, target_reading=target_reading, eta_minutes=28)


def _scenario_three_candidates_close(i: int) -> AgentContext:
    target = _station(f"TARGET-{i}", name="신촌")
    target_reading = _reading(current_stock=0, predicted_stock=0.2, p_empty=0.9)
    specs = [("이대", 100.0, 0.3), ("신촌역", 120.0, 0.28), ("아현", 140.0, 0.26)]
    cand_ctxs = [
        _candidate_ctx(
            f"C{i}{idx}",
            name=name,
            distance_m=dist,
            current_stock=3,
            predicted_stock=2.5,
            p_empty=pe,
        )
        for idx, (name, dist, pe) in enumerate(specs)
    ]
    return _fired_ctx(*cand_ctxs, target=target, target_reading=target_reading, eta_minutes=7)


SCENARIOS: list[tuple[str, str, Callable[[int], AgentContext]]] = [
    (
        "large_score_gap",
        "후보 2개, 점수 차 큼(가깝고 안전 vs 멀고 위험)",
        _scenario_large_score_gap,
    ),
    ("small_score_gap", "후보 2개, 점수 차 작음(거의 동점)", _scenario_small_score_gap),
    ("single_candidate", "후보 1개(LLM 미호출 지름길 경로)", _scenario_single_candidate),
    (
        "near_risky_far_safe",
        "가깝지만 재고 불안한 후보 vs 멀지만 안정적인 후보",
        _scenario_near_risky_far_safe,
    ),
    ("many_candidates", "후보 4개, 점수 분포가 넓다", _scenario_many_candidates),
    (
        "proxy_predicted_stock",
        "p_empty 없이 predicted_stock 근사(proxy)로만 판단",
        _scenario_proxy_predicted_stock,
    ),
    (
        "low_confidence_facts",
        "facts가 다른 값(ETA 상한 근접·p_full>0·horizon=30)",
        _scenario_low_confidence_facts,
    ),
    (
        "three_candidates_close",
        "후보 3개, 인접 점수가 촘촘해 순위가 민감하다",
        _scenario_three_candidates_close,
    ),
]


def build_synthetic(n: int) -> list[dict[str, Any]]:
    if n <= 0:
        raise ValueError("--n은 1 이상이어야 한다")
    records: list[dict[str, Any]] = []
    for i in range(n):
        label, description, factory = SCENARIOS[i % len(SCENARIOS)]
        ctx = factory(i)
        records.append(
            {
                "id": f"s{i:02d}_{label}",
                "label": label,
                "description": description,
                "n_candidates": len(ctx.usable_candidates),
                "context": to_json(ctx),
            }
        )
    return records


# ── --from-parquet ──


def build_from_parquet(path: Path, n: int) -> list[dict[str, Any]]:
    if not path.exists():
        print(
            f"[오류] 스냅샷 파일이 없다: {path}\n"
            "값을 지어내는 대신 여기서 멈춘다 — 실제 latest_stock.parquet을 그 경로에 두거나 "
            "--from-parquet 없이(합성 표본) 다시 실행하라.",
            file=sys.stderr,
        )
        sys.exit(1)

    import pandas as pd  # 지연 import — 합성 표본 경로는 pandas가 필요 없다

    frame = pd.read_parquet(path)
    if "lat" not in frame.columns or "lng" not in frame.columns:
        print(
            f"[오류] {path}에 lat/lng 컬럼이 없다(레거시 스냅샷) — 후보 탐색을 할 수 없어 "
            "표본을 만들 수 없다. 값을 지어내지 않는다.",
            file=sys.stderr,
        )
        sys.exit(1)

    depleting = frame[frame["current_stock"].fillna(99) <= 1].copy()
    if depleting.empty:
        print(
            f"[오류] {path}에 현재 재고 1대 이하인 대여소가 없다 — '고갈 임박' 표본을 만들 "
            "근거가 없다. 값을 지어내지 않는다.",
            file=sys.stderr,
        )
        sys.exit(1)
    depleting = depleting.sort_values("current_stock").head(n)
    if len(depleting) < n:
        print(
            f"[경고] 고갈 임박 대여소가 {len(depleting)}곳뿐이라 요청한 {n}건보다 적게 만든다.",
            file=sys.stderr,
        )

    index = ParquetStationIndex(path)
    records: list[dict[str, Any]] = []
    for i, row in enumerate(depleting.to_dict("records")):
        rental_id = str(row["rental_id"])
        target = index.get(rental_id)
        if target is None:
            continue  # 신선도 검사 등으로 색인에서 빠졌다 — 지어내지 않고 건너뛴다

        target_reading = _parquet_proxy_reading(target.current_stock)
        cand_rentals = candidates_mod.generate(
            target, index, radius_m=PARQUET_NEARBY_RADIUS_M, limit=PARQUET_NEARBY_LIMIT
        )
        cand_ctxs = [
            CandidateContext(
                candidate=cand, reading=_parquet_proxy_reading(cand.station.current_stock)
            )
            for cand in cand_rentals
        ]
        if not cand_ctxs:
            continue  # 후보가 없으면 두 전략이 비교할 것도 없다 — 굳이 안 만든다

        ctx = _fired_ctx(
            *cand_ctxs,
            target=target,
            target_reading=target_reading,
            eta_minutes=PARQUET_ASSUMED_ETA_MIN,
        )
        records.append(
            {
                "id": f"p{i:02d}_{rental_id}",
                "label": "from_parquet",
                "description": f"실제 스냅샷 고갈 임박 대여소({rental_id}, 재고 {target.current_stock})",
                "n_candidates": len(ctx.usable_candidates),
                "context": to_json(ctx),
            }
        )
    if not records:
        print(
            "[오류] 고갈 임박 대여소는 있었지만 전부 후보가 없거나 색인에서 빠져 표본을 "
            "하나도 못 만들었다.",
            file=sys.stderr,
        )
        sys.exit(1)
    return records


def _parquet_proxy_reading(current_stock: int | None) -> StockReading:
    """모델 아티팩트가 없을 때의 문서화된 근사(모듈 docstring `--from-parquet` 절 참고).
    `current_stock`이 `None`(모른다)이면 `predicted_stock`도 `None`이다 — 모르는 값을 0으로
    읽지 않는다."""
    predicted_stock = float(current_stock) if current_stock is not None else None
    p_empty = None if predicted_stock is None else (0.9 if predicted_stock <= 1 else 0.1)
    return StockReading(
        current_stock=current_stock,
        predicted_stock=predicted_stock,
        p_empty=p_empty,
        p_full=None,
        source=PARQUET_PROXY_SOURCE,
        model_horizon_min=PARQUET_ASSUMED_ETA_MIN,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--n", type=int, default=8, help="표본 수(기본 8)")
    parser.add_argument("--out", type=str, default=None, help=f"출력 경로(기본: {DEFAULT_OUT})")
    parser.add_argument(
        "--from-parquet",
        type=str,
        default=None,
        help="실제 latest_stock.parquet 경로 — 주면 고갈 임박 대여소로 표본을 만든다(파일 "
        "없으면 오류 후 종료, 값을 지어내지 않는다)",
    )
    args = parser.parse_args()

    out_path = Path(args.out) if args.out else DEFAULT_OUT

    if args.from_parquet:
        records = build_from_parquet(Path(args.from_parquet), args.n)
    else:
        records = build_synthetic(args.n)

    write_samples(records, out_path)
    print(f"[저장] {out_path} ({len(records)}건)")
    for record in records:
        print(f"  - {record['id']}: {record['description']} (후보 {record['n_candidates']}개)")


if __name__ == "__main__":
    main()
