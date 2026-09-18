"""경로 순위 뒤집힘 실험 — `RESOLUTION_LADDER.md` §6이 계획한 실험을 실행한다.

혼잡도가 경로 추천에 "의미 있게" 영향을 주는가를, 세 해상도에서 만든 표 사이의 **순위 변화**로
잰다. 세 해상도는 전부 우리가 이미 만든 표이고 BE 그래프는 쓰지 않는다.

    (a) lookup — `--predictor lookup`(요일유형 평균)으로 만든 슬롯 표(정적 표에 대응)
    (b) model  — 평소 배치가 만드는 슬롯 표(30분, 잔차 모델 포함)
    (c) train  — 열차·노드 표(`predictions_train_*.parquet`, 239)

같은 OD·같은 후보 경로·같은 출발 시각을 세 해상도에 그대로 돌려 채점한다(동등 조건,
`AI/CLAUDE.md`). 그래프·후보 경로 생성은 `graph.py`, 채점은 `score.py`(둘 다 순수 함수 —
단위 테스트는 `test/CROWD/test_crowd_route_ranking.py`).

## 실행

    cd AI
    python validation/CROWD/route-ranking-check/run_ranking.py --help
    python validation/CROWD/route-ranking-check/run_ranking.py \\
        --dates 2026-09-13 2026-09-14 --times 08:00 14:00 23:00 --n-od 300 --seed 0 --k 3 \\
        --serving-dir data/CROWD/serving \\
        --lookup-dir data/CROWD/interim/validation/route_ranking/lookup \\
        --out data/CROWD/interim/validation/route_ranking

`--lookup-dir`의 `predictions_{date}.parquet`은 미리 만들어 둔다(정적 표):

    python -m app.CROWD.pipeline.batch_predict --date <date> --predictor lookup \\
        --out-dir data/CROWD/interim/validation/route_ranking/lookup

`--serving-dir`에는 평소 배치가 만드는 슬롯 표와, `--trains`로 만든 열차·노드 표가 있어야
한다(없으면 이 스크립트가 만드는 명령을 안내하고 종료 코드 2로 끝난다).

## 산출물 (`--out` 아래)

- `candidates.csv` — (date, time, od_id, cand_id, resolution)별 한 행.
- `summary.json` — 해상도 쌍({lookup,model}·{model,train}·{lookup,train})별 1위 변경률·
  변경 시 격자(%p)·부트스트랩 95% CI(OD 쌍 단위, `--n-boot`회), 해상도별 "편안함 1위 ≠ 최단
  시간" 비율, 커버리지 평균, 시간대별 분해.

수치는 표시만 한다 — 판정은 사람이 `RESULTS.md`에 채운다.
"""

from __future__ import annotations

import argparse
import itertools
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

_HERE = Path(__file__).resolve().parent
AI_ROOT = _HERE.parents[2]
for _p in (str(AI_ROOT), str(_HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from graph import build_graph, candidate_routes, legs_of, schedule_path
from score import rank, score_slot_table, score_train_table

from app.core.config import get_settings
from app.CROWD.pipeline.timetable import load_timetable
from app.CROWD.pipeline.topology import load_topology, resolve_segments

PANEL_PATH = AI_ROOT / "data" / "CROWD" / "processed" / "crowd_panel_2024_2025.parquet"
PANEL_COLUMNS = ["station_no", "station_name", "line"]
RESOLUTIONS = ("lookup", "model", "train")
RESOLUTION_PAIRS = (("lookup", "model"), ("model", "train"), ("lookup", "train"))
CANDIDATE_COLUMNS = [
    "date",
    "time",
    "od_id",
    "origin",
    "dest",
    "cand_id",
    "total_min",
    "n_transfers",
    "resolution",
    "mean_tw",
    "max",
    "coverage",
    "comparable",
    "rank",
]
_WEEKDAY_TO_DAY_TYPE = {
    0: "평일",
    1: "평일",
    2: "평일",
    3: "평일",
    4: "평일",
    5: "토요일",
    6: "일요일",
}


def day_type_of(day, holidays: set[pd.Timestamp]) -> str:
    """날짜 → 시각표 요일유형(평일/토요일/일요일). 공휴일은 일요일 다이어를 쓴다(스펙 지시,
    `timetable.timetable_day_type`이 패널 "휴일"을 일요일로 접는 것과 같은 방향)."""
    ts = pd.Timestamp(day).normalize()
    if ts in holidays:
        return "일요일"
    return _WEEKDAY_TO_DAY_TYPE[ts.weekday()]


def _time_to_minutes(hhmm: str) -> float:
    """'HH:MM' → 운행일 기준 분(00~03시는 24시 이후로 접는다, `disaggregate.to_minutes`와 같은 규칙)."""
    hh, mm = hhmm.split(":")
    m = int(hh) * 60 + int(mm)
    return float(m if m >= 4 * 60 else m + 24 * 60)


def _fail_missing(path: Path, how_to_build: str) -> None:
    print(f"[안내] 파일이 없다: {path}\n먼저 만든다: {how_to_build}", file=sys.stderr)
    raise SystemExit(2)


def _load_slot_table(dir_path: Path, date_str: str, *, label: str, lookup: bool) -> pd.DataFrame:
    path = Path(dir_path) / f"predictions_{date_str}.parquet"
    if not path.exists():
        cmd = (
            f"python -m app.CROWD.pipeline.batch_predict --date {date_str} --predictor lookup "
            f"--out-dir {dir_path}"
            if lookup
            else f"python -m app.CROWD.pipeline.batch_predict --date {date_str} --out-dir {dir_path}"
        )
        _fail_missing(path, f"{label} 슬롯 표 — {cmd}")
    return pd.read_parquet(path)


def _load_train_table(serving_dir: Path, date_str: str) -> pd.DataFrame:
    path = Path(serving_dir) / f"predictions_train_{date_str}.parquet"
    if not path.exists():
        cmd = (
            f"python -m app.CROWD.pipeline.batch_predict --date {date_str} --trains "
            f"--out-dir {serving_dir}"
        )
        _fail_missing(path, f"열차·노드 표 — {cmd}")
    return pd.read_parquet(path)


def sample_od_pairs(
    g,
    stations: pd.DataFrame,
    n_od: int,
    seed: int,
    *,
    min_stations: int = 3,
    max_stations: int = 40,
) -> list[dict]:
    """서로 다른 역명의 OD 쌍을 무작위로 뽑아, 경로가 있고 승차역 수가 [min, max] 안인 것만 남긴다.

    "승차역 수"는 경로 노드 수에서 환승 간선 통과 횟수를 뺀 값이다 — 환승은 같은 물리적 역을
    다른 `station_no`로 옮겨 타는 것뿐이라 새 역이 아니다.
    """
    import networkx as nx

    names = (
        stations[["station_no", "station_name"]]
        .drop_duplicates("station_no")
        .set_index("station_no")["station_name"]
    )
    rng = np.random.default_rng(seed)
    nodes = np.array(list(g.nodes))
    pairs: list[dict] = []
    seen: set[tuple[int, int]] = set()
    max_attempts = max(n_od * 50, 500)
    for _ in range(max_attempts):
        if len(pairs) >= n_od:
            break
        o, d = rng.choice(nodes, size=2, replace=False)
        o, d = int(o), int(d)
        if (o, d) in seen:
            continue
        if names.get(o) is None or names.get(d) is None or names.get(o) == names.get(d):
            continue
        try:
            path = nx.shortest_path(g, o, d, weight="minutes")
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            continue
        n_transfer_hops = sum(
            1 for u, v in itertools.pairwise(path) if g[u][v]["kind"] == "transfer"
        )
        n_ride_stations = len(path) - n_transfer_hops
        if not (min_stations <= n_ride_stations <= max_stations):
            continue
        seen.add((o, d))
        pairs.append({"od_id": len(pairs), "origin": o, "dest": d})
    return pairs


def score_candidate(g, path, depart_min, timetable, day_type, lookup_tbl, model_tbl, train_tbl):
    """경로 하나를 세 해상도로 채점. 반환: (스케줄된 legs, {resolution: score_dict})."""
    legs = legs_of(g, path)
    scheduled = schedule_path(g, legs, depart_min, timetable, day_type)
    scores = {
        "lookup": score_slot_table(scheduled, lookup_tbl),
        "model": score_slot_table(scheduled, model_tbl),
        "train": score_train_table(scheduled, train_tbl),
    }
    return scheduled, scores


def run(args: argparse.Namespace) -> tuple[pd.DataFrame, dict]:
    if not PANEL_PATH.exists():
        _fail_missing(
            PANEL_PATH,
            "CROWD 패널(build_crowd_panel 등)로 crowd_panel_2024_2025.parquet을 먼저 만든다",
        )
    stations = pd.read_parquet(PANEL_PATH, columns=PANEL_COLUMNS).drop_duplicates("station_no")

    settings = get_settings()
    segments, _gaps = resolve_segments(load_topology(), set(stations["station_no"]))
    try:
        timetable = load_timetable(Path(settings.crowd_timetable_path))
    except FileNotFoundError as exc:
        print(f"[안내] {exc}", file=sys.stderr)
        raise SystemExit(2) from exc

    g = build_graph(segments, stations, timetable)
    print(
        f"[그래프] 노드 {g.number_of_nodes():,} · 간선 {g.number_of_edges():,} · "
        f"간선 시간 대체(호선 중앙값) {g.graph['fallback_line_median_edges']} · "
        f"대체(상수 2.0분) {g.graph['fallback_hard_edges']}",
        flush=True,
    )

    holidays = {pd.Timestamp(h).normalize() for h in args.holidays}
    od_pairs = sample_od_pairs(g, stations, args.n_od, args.seed)
    if not od_pairs:
        print(
            "[안내] 조건(3~40 승차역, 경로 존재)을 만족하는 OD 쌍을 찾지 못했다.", file=sys.stderr
        )
        raise SystemExit(2)
    print(f"[OD] {len(od_pairs)}쌍 표본", flush=True)

    rows: list[dict] = []
    for date_str in args.dates:
        day_type = day_type_of(date_str, holidays)
        lookup_tbl = _load_slot_table(Path(args.lookup_dir), date_str, label="lookup", lookup=True)
        model_tbl = _load_slot_table(Path(args.serving_dir), date_str, label="model", lookup=False)
        train_tbl = _load_train_table(Path(args.serving_dir), date_str)

        for time_str in args.times:
            depart_min = _time_to_minutes(time_str)
            for od in od_pairs:
                candidates = candidate_routes(g, od["origin"], od["dest"], k=args.k)
                if not candidates:
                    continue
                meta = []
                scores_by_resolution: dict[str, list[dict]] = {r: [] for r in RESOLUTIONS}
                for cand_id, path in enumerate(candidates):
                    scheduled, scores = score_candidate(
                        g, path, depart_min, timetable, day_type, lookup_tbl, model_tbl, train_tbl
                    )
                    total_min = scheduled[-1]["arrive_min"] - depart_min if scheduled else 0.0
                    n_transfers = sum(1 for leg in scheduled if leg["kind"] == "transfer")
                    meta.append({"total_min": total_min, "n_transfers": n_transfers})
                    for r in RESOLUTIONS:
                        scores_by_resolution[r].append(scores[r])

                for r in RESOLUTIONS:
                    order = rank(scores_by_resolution[r])
                    rank_of = {cand_id: pos + 1 for pos, cand_id in enumerate(order)}
                    for cand_id, s in enumerate(scores_by_resolution[r]):
                        rows.append(
                            {
                                "date": date_str,
                                "time": time_str,
                                "od_id": od["od_id"],
                                "origin": od["origin"],
                                "dest": od["dest"],
                                "cand_id": cand_id,
                                "total_min": meta[cand_id]["total_min"],
                                "n_transfers": meta[cand_id]["n_transfers"],
                                "resolution": r,
                                "mean_tw": s["mean_tw"],
                                "max": s["max"],
                                "coverage": s["coverage"],
                                "comparable": s["comparable"],
                                "rank": rank_of[cand_id],
                            }
                        )

    candidates_df = (
        pd.DataFrame(rows, columns=CANDIDATE_COLUMNS)
        if rows
        else pd.DataFrame(columns=CANDIDATE_COLUMNS)
    )
    summary = build_summary(candidates_df, args)
    return candidates_df, summary


# ── 요약 ──
def _top1_table(df: pd.DataFrame, resolution: str) -> pd.DataFrame:
    sub = df[(df["resolution"] == resolution) & (df["rank"] == 1)]
    return sub.drop_duplicates(["date", "time", "od_id"]).set_index(["date", "time", "od_id"])[
        ["cand_id", "mean_tw"]
    ]


def _bootstrap_rate_ci(flags: np.ndarray, group_ids: np.ndarray, n_boot: int, seed: int):
    """OD 쌍(od_id) 단위 복원추출로 `flags`(1위 변경 여부) 비율의 95% 백분위 CI."""
    unique_groups = np.unique(group_ids)
    if unique_groups.size == 0:
        return float("nan"), float("nan")
    rng = np.random.default_rng(seed)
    idx_by_group = {gid: np.where(group_ids == gid)[0] for gid in unique_groups}
    rates = np.empty(n_boot)
    for b in range(n_boot):
        sampled = rng.choice(unique_groups, size=unique_groups.size, replace=True)
        take = np.concatenate([idx_by_group[gid] for gid in sampled])
        rates[b] = flags[take].mean() if take.size else np.nan
    lo, hi = np.nanpercentile(rates, [2.5, 97.5])
    return float(lo), float(hi)


def compare_resolutions(df: pd.DataFrame, r1: str, r2: str, n_boot: int, seed: int) -> dict:
    """`r1` vs `r2`의 1위 변경률·변경 시 격자(%p)·부트스트랩 95% CI(OD 쌍 단위)."""
    t1, t2 = _top1_table(df, r1), _top1_table(df, r2)
    joined = t1.join(t2, lsuffix="_1", rsuffix="_2", how="inner").reset_index()
    if joined.empty:
        return {"pair": f"{r1}_vs_{r2}", "n": 0}
    changed = (joined["cand_id_1"] != joined["cand_id_2"]).to_numpy()
    gap = (joined["mean_tw_2"] - joined["mean_tw_1"]).abs().to_numpy()
    gap_changed = gap[changed & np.isfinite(gap)]
    lo, hi = _bootstrap_rate_ci(changed.astype(float), joined["od_id"].to_numpy(), n_boot, seed)
    return {
        "pair": f"{r1}_vs_{r2}",
        "n": len(joined),
        "top1_changed_rate": float(changed.mean()),
        "top1_changed_rate_ci95": [lo, hi],
        "gap_mean_when_changed": float(np.mean(gap_changed)) if gap_changed.size else float("nan"),
        "gap_median_when_changed": (
            float(np.median(gap_changed)) if gap_changed.size else float("nan")
        ),
    }


def comfort_vs_fastest(df: pd.DataFrame, resolution: str) -> float:
    """그 해상도의 "편안함 1위"(rank==1)가 "최단 시간 후보"(total_min 최소, 해상도 무관)와
    다른 (date, time, od_id) 비율."""
    sub = df[df["resolution"] == resolution]
    if sub.empty:
        return float("nan")
    fastest = sub.loc[sub.groupby(["date", "time", "od_id"])["total_min"].idxmin()].set_index(
        ["date", "time", "od_id"]
    )["cand_id"]
    top1 = (
        sub[sub["rank"] == 1]
        .drop_duplicates(["date", "time", "od_id"])
        .set_index(["date", "time", "od_id"])["cand_id"]
    )
    joined = pd.concat([fastest.rename("fastest"), top1.rename("top1")], axis=1).dropna()
    if joined.empty:
        return float("nan")
    return float((joined["fastest"] != joined["top1"]).mean())


def build_summary(df: pd.DataFrame, args: argparse.Namespace) -> dict:
    overall = [compare_resolutions(df, a, b, args.n_boot, args.seed) for a, b in RESOLUTION_PAIRS]
    by_time = {
        t: [
            compare_resolutions(df[df["time"] == t], a, b, args.n_boot, args.seed)
            for a, b in RESOLUTION_PAIRS
        ]
        for t in args.times
    }
    return {
        "n_od": int(df["od_id"].nunique()) if len(df) else 0,
        "n_candidate_rows": len(df),
        "pairs": overall,
        "by_time": by_time,
        "comfort_top1_differs_from_fastest_rate": {
            r: comfort_vs_fastest(df, r) for r in RESOLUTIONS
        },
        "coverage_mean": (df.groupby("resolution")["coverage"].mean().to_dict() if len(df) else {}),
    }


def print_markdown_summary(summary: dict) -> None:
    print("\n| 비교 | n | 1위 변경률 | 95% CI | 격차 평균(변경 시) | 격차 중앙값 |")
    print("| --- | ---: | ---: | --- | ---: | ---: |")
    for p in summary["pairs"]:
        if p.get("n", 0) == 0:
            print(f"| {p['pair']} | 0 | - | - | - | - |")
            continue
        lo, hi = p["top1_changed_rate_ci95"]
        print(
            f"| {p['pair']} | {p['n']} | {p['top1_changed_rate']:.3f} | "
            f"[{lo:.3f}, {hi:.3f}] | {p['gap_mean_when_changed']:.2f} | "
            f"{p['gap_median_when_changed']:.2f} |"
        )
    print("\n| 해상도 | 편안함 1위 ≠ 최단시간 비율 | coverage 평균 |")
    print("| --- | ---: | ---: |")
    for r in RESOLUTIONS:
        comfort = summary["comfort_top1_differs_from_fastest_rate"].get(r, float("nan"))
        cov = summary["coverage_mean"].get(r, float("nan"))
        print(f"| {r} | {comfort:.3f} | {cov:.3f} |")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--dates", nargs="+", default=["2026-09-13", "2026-09-14"])
    ap.add_argument("--times", nargs="+", default=["08:00", "14:00", "23:00"])
    ap.add_argument("--n-od", type=int, default=300)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--k", type=int, default=3)
    ap.add_argument("--n-boot", type=int, default=1000, help="부트스트랩 재표본 수")
    ap.add_argument(
        "--holidays", nargs="*", default=[], help="공휴일 목록(YYYY-MM-DD), 일요일 다이어로 접는다"
    )
    ap.add_argument("--serving-dir", default=str(AI_ROOT / "data" / "CROWD" / "serving"))
    ap.add_argument(
        "--lookup-dir",
        default=str(
            AI_ROOT / "data" / "CROWD" / "interim" / "validation" / "route_ranking" / "lookup"
        ),
    )
    ap.add_argument(
        "--out",
        default=str(AI_ROOT / "data" / "CROWD" / "interim" / "validation" / "route_ranking"),
    )
    args = ap.parse_args(argv)

    candidates_df, summary = run(args)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    candidates_path = out_dir / "candidates.csv"
    candidates_df.to_csv(candidates_path, index=False, encoding="utf-8")
    summary_path = out_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")

    print_markdown_summary(summary)
    print(f"\n저장: {candidates_path}\n저장: {summary_path}", flush=True)


if __name__ == "__main__":
    main(sys.argv[1:])
