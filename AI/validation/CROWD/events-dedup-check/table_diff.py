"""318 축제 중복 제거 수정 전/후로 배포 이벤트 표가 왜 달라졌는지 가르는 재현 스크립트.

**배경**: 배포된 `crowd_station_events_2024_2025.parquet`(구 버전, 7,958행)를 원본 원천으로
다시 만들었더니(`REGEN-20260921`) 8,881행이 나왔다 — 923행이 늘었다. 이게 데이터 갱신 때문인지
파이프라인 결함 때문인지가 불분명했다. `parsers_festival.py`의 `_DEDUPE_KEYS`가 이때는 아직
`["name", "start_date", "end_date", "lat", "lon"]`이었는데, 227 1.2절이 기록한 대로 같은
축제라도 좌표가 원본 파일마다 소수점 4~6번째 자리에서 드리프트한다(189개 중복 그룹 중 34개는
최대 위도 0.064도까지 벌어진다) — 그래서 좌표를 식별 키에 넣으면 시간이 지날수록(원본을 다시
받을수록) 점점 더 많은 중복을 놓치게 된다. 318은 이 키에서 `lat`·`lon`을 빼는 수정이었다
(`_DEDUPE_KEYS = ["name", "start_date", "end_date"]`, 좌표는 어느 행을 남길지 정하는
타이브레이커로만 남긴다).

이 스크립트는 그 수정 전후로 배포 표가 어떻게 바뀌었는지를 세 갈래로 잰다.

1. **표 1 행 대조** — 배포(구, `PRE318`) vs 재생성(구 dedup, `REGEN-20260921`) vs 재생성
   (신 dedup, 현재)의 행 수·`festival_count` 값 차이. `old vs regen`이 갈리면 원본 데이터
   갱신만으로도 좌표 드리프트 결함이 시간에 따라 커진다는 뜻이고, `regen vs new`가 갈리면
   그게 이번 dedup 키 수정의 순수 효과라는 뜻이다.
2. **표 2 interim 중복** — 수정 전/후 interim 축제 표 자체의 중복 건수·중복 그룹의 좌표
   편차 크기(227 1.2절 수치의 재현).
3. **표 3 추가분 귀속** — 신 dedup이 "새로 추가"한 게 아니라 "중복을 안 지운" 것인지 보려고,
   2023년 이전 파일에서 온 축제 중 이 구간과 겹치는 것들의 역·역-일 규모를 잰다.
4. **표 4 사라진 행 귀속** — `regen`에는 있는데 `new`에는 없는 923행이 구 interim의 어느
   축제(들)의 그림자인지, 월별 분포와 함께 역-일 조인으로 짚는다.

표는 markdown으로 stdout에 찍고, `--out`을 주면 같은 내용을 파일로도 남긴다.

실행:
    cd AI
    python validation/CROWD/events-dedup-check/table_diff.py
    python validation/CROWD/events-dedup-check/table_diff.py --out validation/CROWD/events-dedup-check/RESULTS.md
"""

from __future__ import annotations

import argparse
import io
import sys
from pathlib import Path

import pandas as pd

AI_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(AI_ROOT))

from DATA_ENGINE.eda import map_events_to_stations as m  # noqa: E402

try:
    import tabulate  # noqa: F401

    _HAS_TABULATE = True
except ImportError:
    _HAS_TABULATE = False

KEY = ["date", "station_no"]
# 신 dedup 키(`parsers_festival._DEDUPE_KEYS`)와 같다 — interim 표 자체의 중복을 잴 때 쓴다.
DEDUPE_KEYS = ["name", "start_date", "end_date"]
COORD_DRIFT_THRESHOLD = 1e-3


def to_md(df: pd.DataFrame) -> str:
    """`tabulate`가 있으면 markdown 표로, 없으면 `to_string`으로 대체한다."""
    if df.empty:
        return "(행 없음)"
    if _HAS_TABULATE:
        return df.to_markdown(index=False)
    return df.to_string(index=False)


def load_events(path: Path) -> pd.DataFrame:
    return pd.read_parquet(path)


def load_interim(path: Path) -> pd.DataFrame:
    return pd.read_parquet(path)


# ---------------------------------------------------------------------------
# 표 1 — 이벤트 표 행 대조
# ---------------------------------------------------------------------------


def compare_event_tables(name_a: str, df_a: pd.DataFrame, name_b: str, df_b: pd.DataFrame) -> dict:
    """`(date, station_no)` 키로 두 이벤트 표를 맞춰 both/left_only/right_only를 세고,
    both 행 중 `festival_count`가 다른 행 수를 같이 낸다.
    """
    ind = df_a[KEY].merge(df_b[KEY], on=KEY, how="outer", indicator=True)
    counts = ind["_merge"].value_counts()
    joined = df_a.merge(df_b, on=KEY, how="inner", suffixes=("_a", "_b"))
    n_diff = int((joined["festival_count_a"] != joined["festival_count_b"]).sum())
    return {
        "비교": f"{name_a} vs {name_b}",
        "both": int(counts.get("both", 0)),
        f"{name_a}_only": int(counts.get("left_only", 0)),
        f"{name_b}_only": int(counts.get("right_only", 0)),
        "festival_count_다른_both_행": n_diff,
    }


def event_row_diff_table(tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    pairs = [("old", "regen"), ("regen", "new"), ("old", "new")]
    rows = [compare_event_tables(a, tables[a], b, tables[b]) for a, b in pairs]
    return pd.DataFrame(rows)


def event_value_summary(tables: dict[str, pd.DataFrame]) -> tuple[pd.DataFrame, pd.DataFrame]:
    """각 표(단독)의 `festival_count` 합계와 값 분포."""
    sums = pd.DataFrame(
        [
            {
                "테이블": name,
                "행수": len(df),
                "festival_count_합계": int(df["festival_count"].sum()),
            }
            for name, df in tables.items()
        ]
    )
    dist_rows = []
    for name, df in tables.items():
        vc = df["festival_count"].value_counts().sort_index()
        for value, count in vc.items():
            dist_rows.append({"테이블": name, "festival_count": int(value), "행수": int(count)})
    dist = pd.DataFrame(dist_rows)
    return sums, dist


# ---------------------------------------------------------------------------
# 표 2 — interim 중복
# ---------------------------------------------------------------------------


def interim_dup_stats(name: str, df: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> dict:
    """구간과 겹치는 축제 중 `DEDUPE_KEYS` 기준 중복 건수·중복 그룹의 좌표 편차를 잰다."""
    window = df[(df["end_date"] >= start) & (df["start_date"] <= end)].copy()
    dup_mask = window.duplicated(subset=DEDUPE_KEYS, keep=False)
    dup_rows = window[dup_mask]
    groups = dup_rows.groupby(DEDUPE_KEYS, dropna=False)
    n_groups = groups.ngroups
    if n_groups:
        spread = groups.agg(
            lat_spread=("lat", lambda s: float(s.max() - s.min())),
            lon_spread=("lon", lambda s: float(s.max() - s.min())),
        )
        n_over = int(
            (
                (spread["lat_spread"] > COORD_DRIFT_THRESHOLD)
                | (spread["lon_spread"] > COORD_DRIFT_THRESHOLD)
            ).sum()
        )
        max_lat_spread = float(spread["lat_spread"].max())
        max_lon_spread = float(spread["lon_spread"].max())
    else:
        n_over = 0
        max_lat_spread = 0.0
        max_lon_spread = 0.0
    return {
        "interim": name,
        "구간_내_축제_행수": len(window),
        "중복_행수": int(dup_mask.sum()),
        "중복_그룹수": n_groups,
        f"좌표편차_{COORD_DRIFT_THRESHOLD:g}도_초과_그룹수": n_over,
        "최대_위도_편차": round(max_lat_spread, 6),
        "최대_경도_편차": round(max_lon_spread, 6),
    }


def interim_dup_table(
    old_interim: pd.DataFrame, new_interim: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp
) -> pd.DataFrame:
    rows = [
        interim_dup_stats("old(PRE318)", old_interim, start, end),
        interim_dup_stats("new", new_interim, start, end),
    ]
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# 표 3 — 추가분(2023년 이전 파일 유래) 귀속
# ---------------------------------------------------------------------------


def clip_days(df: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> pd.Series:
    clip_start = df["start_date"].clip(lower=start)
    clip_end = df["end_date"].clip(upper=end)
    return (clip_end - clip_start).dt.days + 1


def old_year_addition_table(
    new_interim: pd.DataFrame,
    stations: pd.DataFrame,
    radius_km: float,
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> tuple[pd.DataFrame, int]:
    """new interim 중 `source_year<=2023` 파일에서 온, 구간과 겹치는 축제의 역·역-일 규모.

    2023년 이전 원천 파일에서 새로 살아난 축제라면 "구간 밖 데이터가 새로 들어온 것"이고,
    2024~2025 파일에서도 중복으로 잡히던 축제라면 "중복 제거가 정상 동작한 것"이다 — 어느
    쪽이 많은지가 이번 923행 증가를 "결함 수정"으로 볼지 "데이터 추가"로 볼지를 가른다.
    """
    cand = (
        new_interim[
            (new_interim["source_year"] <= 2023)
            & (new_interim["end_date"] >= start)
            & (new_interim["start_date"] <= end)
        ]
        .dropna(subset=["lat", "lon"])
        .copy()
    )

    if cand.empty:
        return (
            pd.DataFrame(
                columns=[
                    "name",
                    "start_date",
                    "end_date",
                    "source_year",
                    "n_stations",
                    "일수",
                    "station_days",
                ]
            ),
            0,
        )

    within, _ = m.nearest_stations(
        cand.drop_duplicates("festival_id")[["festival_id", "lat", "lon"]], stations, radius_km
    )
    n_stations = within.groupby("festival_id").size().rename("n_stations")

    cand = cand.set_index("festival_id")
    cand["n_stations"] = n_stations.reindex(cand.index).fillna(0).astype(int)
    cand["일수"] = clip_days(cand, start, end)
    cand["station_days"] = cand["n_stations"] * cand["일수"]

    out = (
        cand.reset_index()[
            [
                "festival_id",
                "name",
                "start_date",
                "end_date",
                "source_year",
                "n_stations",
                "일수",
                "station_days",
            ]
        ]
        .sort_values("station_days", ascending=False)
        .reset_index(drop=True)
    )
    return out, int(out["station_days"].sum())


# ---------------------------------------------------------------------------
# 표 4 — regen에만 있는(사라진) 행의 귀속
# ---------------------------------------------------------------------------


def explode_festival_station_days(
    fest: pd.DataFrame,
    stations: pd.DataFrame,
    radius_km: float,
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> pd.DataFrame:
    """interim 축제 표를 (festival, date, station_no) 행으로 편다.

    `map_events_to_stations.load_festivals`와 같은 방식(구간으로 자르고 날짜를 explode)이되,
    역까지 붙여 `KEY`(`date`, `station_no`) 조인에 바로 쓸 수 있게 한다.
    """
    fest = fest.dropna(subset=["lat", "lon"]).copy()
    fest = fest[(fest["end_date"] >= start) & (fest["start_date"] <= end)].copy()
    fest["start_date"] = fest["start_date"].clip(lower=start)
    fest["end_date"] = fest["end_date"].clip(upper=end)

    within, _ = m.nearest_stations(
        fest.drop_duplicates("festival_id")[["festival_id", "lat", "lon"]], stations, radius_km
    )
    links = within[["festival_id", "station_no"]]

    fest["date"] = [
        pd.date_range(s, e, freq="D") for s, e in zip(fest["start_date"], fest["end_date"])
    ]
    exploded = fest.explode("date")[
        ["festival_id", "name", "start_date", "end_date", "source_year", "date"]
    ]
    return exploded.merge(links, on="festival_id", how="inner")


def vanished_rows_table(
    old_interim: pd.DataFrame,
    stations: pd.DataFrame,
    radius_km: float,
    start: pd.Timestamp,
    end: pd.Timestamp,
    vanished: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """regen에만 있는 행(923행 근방)의 월별 분포와, old interim 어느 축제가 그 자리를 덮는지."""
    month_dist = (
        vanished.assign(월=vanished["date"].dt.to_period("M").astype(str))
        .groupby("월")
        .size()
        .rename("행수")
        .reset_index()
        .sort_values("월")
    )

    old_daily = explode_festival_station_days(old_interim, stations, radius_km, start, end)
    matched = old_daily.merge(vanished[KEY], on=KEY, how="inner")
    attribution = (
        matched.groupby(["name", "start_date", "end_date", "source_year"], dropna=False)
        .size()
        .rename("일치_행수")
        .reset_index()
        .sort_values("일치_행수", ascending=False)
        .head(12)
        .reset_index(drop=True)
    )
    return month_dist, attribution


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def build_report(args: argparse.Namespace) -> str:
    start, end = pd.Timestamp(args.start), pd.Timestamp(args.end)

    old_events = load_events(AI_ROOT / args.old_events)
    regen_events = load_events(AI_ROOT / args.regen_events)
    new_events = load_events(AI_ROOT / args.new_events)
    tables = {"old": old_events, "regen": regen_events, "new": new_events}

    old_interim = load_interim(AI_ROOT / args.old_interim)
    new_interim = load_interim(AI_ROOT / args.new_interim)

    stations = m.load_panel_stations()
    _, radius_km = m.load_venues()

    buf = io.StringIO()

    def emit(title: str, df: pd.DataFrame) -> None:
        print(f"\n## {title}\n", file=buf)
        print(to_md(df), file=buf)

    print("# 318 이벤트 중복 제거 검증 — table_diff", file=buf)
    print(
        f"\n구간: {start:%Y-%m-%d} ~ {end:%Y-%m-%d}"
        f"\n입력: old={args.old_events} / regen={args.regen_events} / new={args.new_events}"
        f"\n      old-interim={args.old_interim} / new-interim={args.new_interim}",
        file=buf,
    )

    emit(
        "표 1 행 대조 — 이벤트 표 쌍별 both/left_only/right_only·festival_count 차이",
        event_row_diff_table(tables),
    )
    sums, dist = event_value_summary(tables)
    emit("표 1-부속 — 테이블별 festival_count 합계", sums)
    emit("표 1-부속 — 테이블별 festival_count 값 분포", dist)

    emit(
        "표 2 interim 중복 — DEDUPE_KEYS(name, start_date, end_date) 기준",
        interim_dup_table(old_interim, new_interim, start, end),
    )

    addition, addition_total = old_year_addition_table(new_interim, stations, radius_km, start, end)
    emit(
        f"표 3 추가분 귀속 — new interim의 source_year<=2023 축제, 상위 20건 "
        f"(전체 station_days 합계 {addition_total:,})",
        addition.head(20),
    )

    ind = regen_events[KEY].merge(new_events[KEY], on=KEY, how="outer", indicator=True)
    vanished_keys = ind[ind["_merge"] == "left_only"][KEY]
    vanished = vanished_keys.merge(regen_events, on=KEY, how="left")
    month_dist, attribution = vanished_rows_table(
        old_interim, stations, radius_km, start, end, vanished
    )
    emit(f"표 4-1 사라진 행({len(vanished):,}행, regen에만 있음) — 월별 분포", month_dist)
    emit("표 4-2 사라진 행 귀속 — old interim 축제별 일치 행수 상위 12건", attribution)

    return buf.getvalue()


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--old-events",
        default="data/CROWD/processed/crowd_station_events_2024_2025_PRE318.parquet",
        help="배포된(수정 전) 이벤트 표. AI 루트 기준 상대 경로",
    )
    ap.add_argument(
        "--regen-events",
        default="data/CROWD/processed/crowd_station_events_2024_2025_REGEN-20260921.parquet",
        help="구 dedup 키로 재생성한(09-21) 이벤트 표",
    )
    ap.add_argument(
        "--new-events",
        default="data/CROWD/processed/crowd_station_events_2024_2025.parquet",
        help="신 dedup 키(318 수정 후)로 재생성한 이벤트 표",
    )
    ap.add_argument(
        "--old-interim",
        default="data/EXTERNAL/events/interim/festival_capital_PRE318.parquet",
        help="수정 전 축제 interim 표",
    )
    ap.add_argument(
        "--new-interim",
        default="data/EXTERNAL/events/interim/festival_capital.parquet",
        help="수정 후 축제 interim 표",
    )
    ap.add_argument("--start", default="2024-01-01", help="구간 시작(YYYY-MM-DD)")
    ap.add_argument("--end", default="2025-12-31", help="구간 끝(YYYY-MM-DD)")
    ap.add_argument("--out", default=None, help="결과를 마크다운으로도 저장할 경로")
    args = ap.parse_args(argv)

    report = build_report(args)
    print(report)

    if args.out:
        out_path = Path(args.out)
        if not out_path.is_absolute():
            out_path = AI_ROOT / out_path
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(report, encoding="utf-8", newline="\n")
        print(f"\n저장 완료: {out_path}")


if __name__ == "__main__":
    main(sys.argv[1:])
