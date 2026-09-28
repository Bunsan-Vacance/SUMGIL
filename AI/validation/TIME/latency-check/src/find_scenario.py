"""dev E2E 테스트(S15P21A104-323, 323-4)용 실제 재고 고갈 시나리오 조회.

이 스크립트는 조회만 하며 외부 호출·쓰기가 없다 — `latest_stock.parquet` 스냅샷을 읽기만
하고, 결과는 표준출력과 이 폴더 밑 `out/` 보고서 파일에만 남긴다. 프로덕션 데이터를 바꾸거나
BE·LLM 등 외부 서비스를 부르지 않는다.

**목적**: dev E2E 테스트에 쓸 "진짜 존재하는 대여소"를 최신 스냅샷에서 골라준다. 가짜 데이터를
만들지 않는다 — `app.TIME.station_index.ParquetStationIndex`를 그대로 써서 서비스가 트리거
판정·후보 탐색에 쓰는 것과 같은 색인 로직(신선도 처리 포함)으로 후보를 뽑는다. 자체 nearby
구현은 하지 않는다 — 재고 0 판정, 좌표 결측 제외, 신선도 컷오프까지 전부
`ParquetStationIndex`/`InMemoryStationIndex`에 위임한다.

두 종류 후보를 찾는다.
- **A. 실고갈 시나리오**: 재고 0인 대여소 중, 반경 `--radius-m`(기본 500) 안에 재고 ≥1인
  대여소가 `--min-neighbors`(기본 2)개 이상인 것. `POST /time/reroute/check`가 자연 트리거로
  뜨는 상황을 그대로 재현한다.
- **B. 강제 트리거 시나리오**(`debugForceTrigger`용): 재고와 무관하게(0이든 몇 대든) 반경 안에
  재고 ≥1인 이웃이 `--min-neighbors`개 이상인 것. 색인에 대여소가 많으면 조건을 만족하는 수가
  커질 수 있어 `--limit`(기본 10)만 출력한다.

신선도 때문에 빈 색인이 나오면(스냅샷이 오래돼 `current_stock`이 전부 "모름"으로 비워지는
경우) `--ignore-staleness`로 신선도 컷오프를 사실상 무한대로 늘려 우회할 수 있다. 기본은
서비스와 같은 기준(`Settings.bike_live_stock_max_staleness_seconds`)이다.

실행:
    cd AI
    python validation/TIME/latency-check/src/find_scenario.py
    python validation/TIME/latency-check/src/find_scenario.py --ignore-staleness
    python validation/TIME/latency-check/src/find_scenario.py \\
        --stock-path <parquet 경로> --radius-m 500 --min-neighbors 2 --limit 10 \\
        --out validation/TIME/latency-check/out/scenario_직접지정.md

parquet이 없으면(J15A104A에서 아직 못 받은 경우) 어디서 받아야 하는지 안내하고 종료 코드
2로 끝난다.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

_HERE = Path(__file__).resolve().parent
AI_ROOT = _HERE.parents[3]
if str(AI_ROOT) not in sys.path:
    sys.path.insert(0, str(AI_ROOT))

from app.core.config import get_settings
from app.TIME.station_index import ParquetStationIndex, RentalStation

KST = ZoneInfo("Asia/Seoul")

IGNORE_STALENESS_SECONDS = 1e12
"""`--ignore-staleness`일 때 쓰는 사실상 무한대 신선도 기준(약 3만 년). 신선도 판정 자체를
없애는 게 아니라 어떤 `updated_at`도 이 값을 넘지 못하게 해서 결과적으로 컷오프를 끈다 —
`ParquetStationIndex`의 "오래되면 재고만 모름으로 비운다" 로직은 그대로 남는다."""


@dataclass
class Neighbor:
    """이웃 대여소 하나(거리·재고 포함) — 표 출력용 얕은 스냅샷."""

    rental_id: str
    name: str | None
    distance_m: float
    current_stock: int | None


@dataclass
class Candidate:
    """시나리오 후보 대여소 하나 + 재고 있는 이웃 목록(거리 오름차순)."""

    station: RentalStation
    neighbors: list[Neighbor]

    @property
    def neighbor_count(self) -> int:
        return len(self.neighbors)


def _resolve_stock_path(arg: str | None) -> Path:
    if arg:
        return Path(arg)
    return get_settings().bike_live_stock_path


def _missing_file_guidance(path: Path) -> str:
    return (
        f"parquet 파일이 없습니다: {path}\n"
        "J15A104A(Spark EC2) 서버가 Kafka bike.stock 컨슈머로 유지하는 latest_stock.parquet을\n"
        "받아 이 경로에 두거나 --stock-path로 실제 경로를 지정하세요.\n"
        "기본 경로는 app.core.config.Settings.bike_live_stock_path 설정값입니다."
    )


def _all_rental_ids(frame: pd.DataFrame) -> list[str]:
    """원본 parquet에 있는 rental_id 목록(등장 순서 유지, 중복 제거).

    좌표·재고 파싱은 여기서 하지 않는다 — 그건 `ParquetStationIndex.get()`에 그대로 맡긴다.
    이 함수는 "무엇을 조회해야 하는가"의 목록만 낸다.
    """
    if "rental_id" not in frame.columns:
        return []
    ids = frame["rental_id"].dropna().astype(str).str.strip()
    ids = ids[ids != ""]
    return list(dict.fromkeys(ids.tolist()))


def _snapshot_latest(frame: pd.DataFrame) -> datetime | None:
    """스냅샷에서 가장 최근 updated_at(헤더 표시용). 컬럼이 없거나 전부 결측이면 None."""
    if frame.empty or "updated_at" not in frame.columns:
        return None
    series = pd.to_datetime(frame["updated_at"], errors="coerce").dropna()
    if series.empty:
        return None
    latest = series.max()
    return latest.to_pydatetime() if hasattr(latest, "to_pydatetime") else latest


def _neighbors_with_stock(
    index: ParquetStationIndex,
    station: RentalStation,
    *,
    radius_m: float,
    scan_limit: int,
    now: datetime,
) -> list[Neighbor]:
    """반경 안에서 재고 ≥1인 이웃만 거리 오름차순으로 골라낸다.

    `scan_limit`은 색인 전체 크기 이상으로 줘야 한다 — `ParquetStationIndex.nearby`의 limit은
    "거리순 상위 N개"만 자르므로, 재고 필터(이 함수의 몫)를 걸기 전에 반경 안 대여소를 전부
    받아둬야 재고 있는 먼 이웃이 상한에 밀려 누락되지 않는다.
    """
    pairs = index.nearby(station.lat, station.lng, radius_m, scan_limit, now=now)
    return [
        Neighbor(
            rental_id=other.rental_id,
            name=other.name,
            distance_m=distance,
            current_stock=other.current_stock,
        )
        for other, distance in pairs
        if other.rental_id != station.rental_id
        and other.current_stock is not None
        and other.current_stock >= 1
    ]


def _build_candidates(
    index: ParquetStationIndex,
    stations: list[RentalStation],
    *,
    radius_m: float,
    min_neighbors: int,
    scan_limit: int,
    now: datetime,
    require_zero_stock: bool,
) -> list[Candidate]:
    candidates: list[Candidate] = []
    for station in stations:
        if require_zero_stock and station.current_stock != 0:
            continue  # A는 "확실히 0대"만 본다 — 모름(None)은 실고갈로 우기지 않는다
        neighbors = _neighbors_with_stock(
            index, station, radius_m=radius_m, scan_limit=scan_limit, now=now
        )
        if len(neighbors) >= min_neighbors:
            candidates.append(Candidate(station=station, neighbors=neighbors))
    candidates.sort(
        key=lambda c: (
            -c.neighbor_count,
            c.neighbors[0].distance_m if c.neighbors else 0.0,
            c.station.rental_id,
        )
    )
    return candidates


def _format_stock(value: int | None) -> str:
    return "모름" if value is None else f"{value}대"


def _format_neighbor(neighbor: Neighbor | None) -> str:
    if neighbor is None:
        return ""
    name = neighbor.name or "(이름 없음)"
    return f"{neighbor.rental_id}({name}, {neighbor.distance_m:.0f}m, {_format_stock(neighbor.current_stock)})"


def _candidate_row(candidate: Candidate) -> str:
    station = candidate.station
    top3 = (candidate.neighbors + [None, None, None])[:3]
    cells = [
        station.rental_id,
        station.name or "(이름 없음)",
        _format_stock(station.current_stock),
        str(candidate.neighbor_count),
        *(_format_neighbor(n) for n in top3),
    ]
    return "| " + " | ".join(cells) + " |"


def _candidate_table(candidates: list[Candidate], *, limit: int) -> list[str]:
    shown = candidates[:limit]
    lines = [
        "| rental_id | 이름 | 재고 | 이웃 수 | 이웃1 | 이웃2 | 이웃3 |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    lines.extend(_candidate_row(c) for c in shown)
    if len(candidates) > limit:
        lines.append("")
        lines.append(f"(총 {len(candidates)}건 중 상위 {limit}건만 표시)")
    return lines


def _section(
    title: str, candidates: list[Candidate], *, limit: int, empty_reason: str
) -> list[str]:
    lines = [f"## {title}", ""]
    if candidates:
        lines.extend(_candidate_table(candidates, limit=limit))
    else:
        lines.append(f"해당 없음 — {empty_reason}")
    lines.append("")
    return lines


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--stock-path",
        type=str,
        default=None,
        help="latest_stock.parquet 경로(기본: settings.bike_live_stock_path)",
    )
    parser.add_argument(
        "--radius-m",
        type=float,
        default=None,
        help="이웃 탐색 반경(m, 기본: settings.time_nearby_radius_m)",
    )
    parser.add_argument(
        "--min-neighbors", type=int, default=2, help="반경 안 재고 ≥1 이웃 최소 개수(기본 2)"
    )
    parser.add_argument(
        "--limit", type=int, default=10, help="시나리오별 출력 상한(다건일 때, 기본 10)"
    )
    parser.add_argument(
        "--ignore-staleness",
        action="store_true",
        help="신선도 컷오프를 사실상 무한대로 늘려 우회한다(기본은 서비스와 동일한 기준)",
    )
    parser.add_argument(
        "--out",
        type=str,
        default=None,
        help="결과 저장 경로(기본: out/scenario_<YYYYMMDD-HHMM>.md)",
    )
    args = parser.parse_args()

    settings = get_settings()
    stock_path = _resolve_stock_path(args.stock_path)

    if not stock_path.exists():
        print(_missing_file_guidance(stock_path), file=sys.stderr)
        sys.exit(2)

    radius_m = args.radius_m if args.radius_m is not None else float(settings.time_nearby_radius_m)
    max_staleness = (
        IGNORE_STALENESS_SECONDS
        if args.ignore_staleness
        else settings.bike_live_stock_max_staleness_seconds
    )

    now = datetime.now(KST).replace(tzinfo=None)
    frame = pd.read_parquet(stock_path)
    rental_ids = _all_rental_ids(frame)
    snapshot_latest = _snapshot_latest(frame)

    index = ParquetStationIndex(stock_path, max_staleness_seconds=max_staleness)
    total_index_size = index.size(now=now)
    scan_limit = max(total_index_size, 1)

    stations: list[RentalStation] = []
    for rental_id in rental_ids:
        station = index.get(rental_id, now=now)
        if station is not None:
            stations.append(station)

    scenario_a = _build_candidates(
        index,
        stations,
        radius_m=radius_m,
        min_neighbors=args.min_neighbors,
        scan_limit=scan_limit,
        now=now,
        require_zero_stock=True,
    )
    scenario_b = _build_candidates(
        index,
        stations,
        radius_m=radius_m,
        min_neighbors=args.min_neighbors,
        scan_limit=scan_limit,
        now=now,
        require_zero_stock=False,
    )

    freshness_note = (
        "신선도 컷오프 사실상 해제(--ignore-staleness)"
        if args.ignore_staleness
        else f"max_staleness_seconds={max_staleness:.0f}(서비스 기본값과 동일)"
    )

    lines = [
        f"# TIME 재안내 dev 시나리오 후보 — {now:%Y-%m-%d %H:%M} KST",
        "",
        f"- parquet: `{stock_path}`",
        f"- 원본 행 수: {len(frame)}, 좌표 있어 색인에 실린 대여소 수: {total_index_size}",
        f"- 스냅샷 최신 updated_at: {snapshot_latest if snapshot_latest is not None else '없음(컬럼 결측)'}",
        f"- 신선도 판정: {freshness_note}",
        f"- 반경: {radius_m:.0f}m, min-neighbors: {args.min_neighbors}, limit: {args.limit}",
        "",
    ]
    lines.extend(
        _section(
            "A. 실고갈 시나리오 (재고 0 + 이웃 재고 확보)",
            scenario_a,
            limit=args.limit,
            empty_reason=(
                f"재고 0이면서 반경 {radius_m:.0f}m 안에 재고 ≥1 이웃이 "
                f"{args.min_neighbors}개 이상인 대여소가 없습니다."
            ),
        )
    )
    lines.extend(
        _section(
            "B. 강제 트리거 시나리오 (재고 무관 + 이웃 재고 확보, debugForceTrigger용)",
            scenario_b,
            limit=args.limit,
            empty_reason=(
                f"반경 {radius_m:.0f}m 안에 재고 ≥1 이웃이 {args.min_neighbors}개 이상인 "
                "대여소가 없습니다."
            ),
        )
    )

    report = "\n".join(lines) + "\n"
    print(report, end="")

    out_path = (
        Path(args.out) if args.out else _HERE.parent / "out" / f"scenario_{now:%Y%m%d-%H%M}.md"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(report, encoding="utf-8")
    print(f"[저장] {out_path}")


if __name__ == "__main__":
    main()
