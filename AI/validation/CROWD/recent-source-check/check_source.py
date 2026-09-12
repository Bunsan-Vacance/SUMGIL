"""143 1단계 — `getStnPsgr` 하루치 원문을 받아 패널과의 정합성을 표로 점검한다.

연간 CSV(2025-12-31까지)와 API(최근 7일)는 겹치는 날짜가 없어 **값 대조는 불가능**하다. 대신 정의·규모 수준에서
넷을 본다.
  (a) 커버리지 — API `stnCd` 집합 vs 패널 273역(누락·초과 목록)
  (b) 심야 귀속 — `pasngHr` 00~05시 합계를 2025 같은 요일유형의 `24~`·`~06` 평균과 비교해 `HOUR_TO_SLOT` 확정
  (c) 규모 — 역×슬롯 합산 후 하루 총 승차·하차 vs 2025 같은 요일유형 평균(±10% 안이면 정의 동일), 서울역(150) 별도
  (d) 시간대별 하차/승차 비 — 심야 하차>승차가 정상인지

실행:
    cd AI
    python validation/CROWD/recent-source-check/check_source.py --date 20260912            # 어제(≈66회 호출)
    python validation/CROWD/recent-source-check/check_source.py --date 20260912 --reuse    # 저장된 원문 재사용
"""

from __future__ import annotations

import argparse
import sys
from datetime import timedelta
from pathlib import Path

import pandas as pd

_HERE = Path(__file__).resolve().parent
AI_ROOT = _HERE.parents[2]
for p in (str(AI_ROOT), str(AI_ROOT / "validation" / "CROWD" / "baseline-check")):
    if p not in sys.path:
        sys.path.insert(0, p)

from evaluate_final import to_markdown

from app.CROWD.pipeline.calendar import attach_calendar, load_holidays
from app.CROWD.pipeline.dataset import CROWD_INTERIM, CROWD_PROCESSED, PANEL_NAME
from DATA_ENGINE.collect.common import now_kst
from DATA_ENGINE.collect.subway_ridership_daily import (
    CROWD_RAW_DAILY,
    SERVICE,
    fetch_day,
    save_raw,
    to_long,
)

DAILY_LONG = CROWD_INTERIM / "crowd_daily_ridership_long.parquet"


def load_raw(day: str, reuse: bool) -> pd.DataFrame:
    path = CROWD_RAW_DAILY / f"dt={pd.Timestamp(day).date().isoformat()}" / f"{SERVICE}.parquet"
    if reuse and path.exists():
        return pd.read_parquet(path)
    raw = fetch_day(day)
    if raw.empty:
        raise SystemExit(f"{day}: 0건 — 보존 창 밖이거나 미갱신")
    save_raw(raw, day)
    return raw


def reference_2025(day_type: str, stations: set[int]) -> pd.DataFrame:
    """2025년 같은 요일유형의 (station_no, time_slot, direction) 일평균 — 패널 역만."""
    ref = pd.read_parquet(DAILY_LONG)
    ref = ref[(ref["date"] >= "2025-01-01") & (ref["date"] <= "2025-12-31")]
    ref = ref[ref["station_no"].isin(stations)]
    cal = attach_calendar(ref[["date"]].drop_duplicates(), load_holidays())[["date", "day_type"]]
    ref = ref.merge(cal, on="date")
    ref = ref[ref["day_type"] == day_type]
    n_days = ref["date"].nunique()
    per_day = ref.groupby(["date", "station_no", "time_slot", "direction"], as_index=False)[
        "passengers"
    ].sum()
    mean = per_day.groupby(["station_no", "time_slot", "direction"], as_index=False)[
        "passengers"
    ].mean()
    mean.attrs["n_days"] = n_days
    return mean


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--date", default=(now_kst().date() - timedelta(days=1)).strftime("%Y%m%d"))
    ap.add_argument(
        "--reuse", action="store_true", help="저장된 원문 parquet이 있으면 호출하지 않는다"
    )
    ap.add_argument("--out", default=None, help="마크다운 표 저장 경로")
    args = ap.parse_args(argv)

    raw = load_raw(args.date, args.reuse)
    panel = pd.read_parquet(
        CROWD_PROCESSED / PANEL_NAME, columns=["station_no", "station_name", "line"]
    ).drop_duplicates()
    stations = set(panel["station_no"].astype(int))
    day = pd.Timestamp(args.date)
    day_type = attach_calendar(pd.DataFrame({"date": [day]}), load_holidays())["day_type"].iloc[0]
    chunks: list[str] = [
        f"# getStnPsgr 원문 점검 — {day.date()} ({day_type}), 원문 {len(raw):,}행\n"
    ]

    def emit(title: str, tbl: pd.DataFrame) -> None:
        print(f"\n### {title}\n{tbl.to_string(index=False)}")
        chunks.append(f"### {title}\n\n{to_markdown(tbl)}\n")

    # (a) 커버리지
    api_st = raw[["lineNm", "stnCd", "stnNm"]].drop_duplicates()
    api_st["station_no"] = pd.to_numeric(api_st["stnCd"], errors="coerce")
    api_set = set(api_st["station_no"].dropna().astype(int))
    missing = panel[~panel["station_no"].isin(api_set)].sort_values("station_no")
    extra = api_st[~api_st["station_no"].isin(stations)].sort_values(["lineNm", "stnCd"])
    emit(
        "(a) 커버리지",
        pd.DataFrame(
            {
                "항목": [
                    "API 역 수",
                    "패널 역 수",
                    "패널에 있는데 API에 없음",
                    "API에 있는데 패널에 없음",
                ],
                "값": [len(api_set), len(stations), len(missing), len(extra)],
            }
        ),
    )
    if len(missing):
        emit("(a-1) 패널에만 있는 역", missing[["line", "station_no", "station_name"]])
    if len(extra):
        emit(
            "(a-2) API에만 있는 역",
            extra[["lineNm", "stnCd", "stnNm"]].rename(
                columns={"lineNm": "line", "stnCd": "stnCd", "stnNm": "station_name"}
            ),
        )
    emit(
        "(a-3) 호선별 API 역 수",
        api_st.groupby("lineNm", as_index=False)["stnCd"]
        .nunique()
        .rename(columns={"lineNm": "line", "stnCd": "역 수"}),
    )

    # (b) 심야 귀속 — 패널 역만, 시간별 총 승차·하차
    r = raw[pd.to_numeric(raw["stnCd"], errors="coerce").isin(stations)].copy()
    r["hour"] = r["pasngHr"].astype(int)
    by_hour = (
        r.groupby("hour", as_index=False)[["rideNope", "gffNope"]]
        .sum()
        .rename(columns={"rideNope": "승차", "gffNope": "하차"})
    )
    by_hour["행 수"] = r.groupby("hour").size().to_numpy()
    by_hour["하차/승차"] = (by_hour["하차"] / by_hour["승차"]).round(2)
    emit("(b)/(d) 시간별 합계(패널 역)", by_hour)

    ref = reference_2025(day_type, stations)
    ref_slot = ref.groupby(["time_slot", "direction"])["passengers"].sum().unstack("direction")
    ref_slot.columns = [f"2025 {day_type} 평균 {c}" for c in ref_slot.columns]
    night = pd.DataFrame(
        {
            "구간": ["API 00~03시", "API 04~05시", "API 00~05시", "2025 24~", "2025 ~06"],
            "승차": [
                by_hour.loc[by_hour["hour"] <= 3, "승차"].sum(),
                by_hour.loc[by_hour["hour"].between(4, 5), "승차"].sum(),
                by_hour.loc[by_hour["hour"] <= 5, "승차"].sum(),
                round(ref_slot.loc["24~", f"2025 {day_type} 평균 boarding"]),
                round(ref_slot.loc["~06", f"2025 {day_type} 평균 boarding"]),
            ],
            "하차": [
                by_hour.loc[by_hour["hour"] <= 3, "하차"].sum(),
                by_hour.loc[by_hour["hour"].between(4, 5), "하차"].sum(),
                by_hour.loc[by_hour["hour"] <= 5, "하차"].sum(),
                round(ref_slot.loc["24~", f"2025 {day_type} 평균 alighting"]),
                round(ref_slot.loc["~06", f"2025 {day_type} 평균 alighting"]),
            ],
        }
    )
    emit(
        f"(b) 심야 귀속 — API 시간 합계 vs 2025 {day_type} 슬롯 평균({ref.attrs['n_days']}일)",
        night,
    )

    # (c) 규모 — 슬롯 합산 후 비교
    lg = to_long(raw)
    lg = lg[lg["station_no"].isin(stations)]
    api_slot = lg.groupby(["time_slot", "direction"])["passengers"].sum().unstack("direction")
    api_slot.columns = [f"API {c}" for c in api_slot.columns]
    cmp = api_slot.join(ref_slot, how="outer")
    for d in ("boarding", "alighting"):
        cmp[f"{d} 비"] = (cmp[f"API {d}"] / cmp[f"2025 {day_type} 평균 {d}"]).round(3)
    from app.CROWD.pipeline.features import SLOT_ORDER

    cmp = cmp.reindex(SLOT_ORDER).reset_index().rename(columns={"index": "time_slot"})
    for c in cmp.columns:
        if c != "time_slot" and not c.endswith(" 비"):
            cmp[c] = cmp[c].round(0).astype("Int64")
    emit("(c) 슬롯별 총량 — API vs 2025 같은 요일유형 평균", cmp)
    tot = pd.DataFrame(
        {
            "항목": ["총 승차", "총 하차"],
            "API": [api_slot["API boarding"].sum(), api_slot["API alighting"].sum()],
            f"2025 {day_type} 평균": [
                ref_slot[f"2025 {day_type} 평균 boarding"].sum(),
                ref_slot[f"2025 {day_type} 평균 alighting"].sum(),
            ],
        }
    )
    tot["비"] = (tot["API"] / tot[f"2025 {day_type} 평균"]).round(3)
    tot["API"] = tot["API"].round(0).astype("Int64")
    tot[f"2025 {day_type} 평균"] = tot[f"2025 {day_type} 평균"].round(0).astype("Int64")
    emit("(c-1) 하루 총량", tot)
    s150 = lg[lg["station_no"] == 150].groupby("direction")["passengers"].sum()
    r150 = ref[ref["station_no"] == 150].groupby("direction")["passengers"].sum()
    t150 = pd.DataFrame(
        {
            "direction": s150.index,
            "API": s150.to_numpy(),
            f"2025 {day_type} 평균": r150.reindex(s150.index).round(0).to_numpy(),
        }
    )
    t150["비"] = (t150["API"] / t150[f"2025 {day_type} 평균"]).round(3)
    emit("(c-2) 서울역(150) 하루 총량", t150)
    by_line = lg.groupby(["line", "direction"])["passengers"].sum().unstack("direction")
    ref_line = (
        ref.merge(panel[["station_no", "line"]], on="station_no")
        .groupby(["line", "direction"])["passengers"]
        .sum()
        .unstack("direction")
    )
    line_cmp = pd.DataFrame(
        {"API 승차": by_line["boarding"], "2025 평균 승차": ref_line["boarding"].round(0)}
    )
    line_cmp["비"] = (line_cmp["API 승차"] / line_cmp["2025 평균 승차"]).round(3)
    emit("(c-3) 호선별 총 승차", line_cmp.reset_index())

    if args.out:
        Path(args.out).write_text("\n".join(chunks), encoding="utf-8")
        print(f"\n저장: {args.out}")


if __name__ == "__main__":
    main(sys.argv[1:])
