"""146 1·2단계 — `no_calibration` 셀이 왜 생기는지 원인별로 세고, 공휴일 대체·지선 방향 대응의
근거 수치를 낸다.

## 왜 필요한가

배치 표의 `data_status`는 지금까지 "배율이 없다"(`no_calibration`) 한 덩어리였다. 원인이 셋
(1~8호선 공휴일 / 2호선 지선 방향 라벨 / 결번·종점 링크)인데 구분이 없어, 어느 쪽을 고치면 몇 셀이
살아나는지 알 수 없었다. 여기서 원인별로 갈라 세고, 고칠 수 있는 두 원인에 대해 "대체해도 되는가"를
수치로 확인한다.

## 계획(`.claude/plans/S15P21A104-146-congestion-criteria.md`)과 달라진 점 — 2절

계획은 "9호선은 배율표에 휴일이 있으므로 9호선에서 휴일 배율 vs 일요일 배율을 비교"하라고 했지만,
**9호선 스냅샷에는 일요일 구간이 아예 없다**(평일·휴일 2종뿐 — 스냅샷 자체가 토·일·공휴일을 "휴일"
하나로 묶는다). 같은 원천 안에서 두 배율을 비교하는 것은 불가능해 세 가지 대체 근거로 바꿨다.

1. **운행 다이어**(`timetable_long.parquet`) — 요일유형이 평일·토요일·일요일 3종이고 공휴일 다이어가
   따로 없다. 배율의 주 성분이 배차라 "공휴일에 어느 다이어가 도는가"가 직접 근거다.
2. **1~8호선 토요일 vs 일요일 배율 차이** — 공휴일을 주말 쪽으로 접을 때 어느 쪽을 고르느냐가 얼마나
   차이를 만드는지의 상한.
3. **2025 공휴일 승하차 프로파일**이 토요일·일요일 중 어느 쪽에 가까운가 — 실제 수요 모양의 판정.

실행(약 3분):
    cd AI
    python validation/CROWD/congestion-criteria-check/diagnose.py --out RESULTS_draft.md
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

_HERE = Path(__file__).resolve().parent
AI_ROOT = _HERE.parents[2]
for p in (str(AI_ROOT), str(AI_ROOT / "validation" / "CROWD" / "baseline-check")):
    if p not in sys.path:
        sys.path.insert(0, p)

from evaluate_final import to_markdown

from app.core.config import get_settings
from app.CROWD.pipeline.batch_predict import (
    CALIBRATION_NAME,
    fixed_predictor_factory,
    predict_day,
    to_congestion_table,
)
from app.CROWD.pipeline.calendar import load_holidays
from app.CROWD.pipeline.congestion import (
    ASCENDING,
    BRANCH_DIRECTION_MAP,
    BRANCH_JUNCTION_STATIONS,
    DESCENDING,
    hour_bucket_to_30min_slots,
    recursive_congestion,
    truncated_boundary_cells,
)
from app.CROWD.pipeline.dataset import (
    CROWD_INTERIM,
    CROWD_PROCESSED,
    EVENTS_NAME,
    load_panel,
    resolved_segments,
)
from app.CROWD.pipeline.predictor import build_predictor
from app.CROWD.pipeline.topology import load_capacity

# 기준일 — 평일 1 · 토요일 1 · 공휴일 1(2025-10-03 개천절, 금요일). 패널 안 날짜라 실측이 있다.
REFERENCE_DATES = ["2025-06-02", "2025-06-07", "2025-10-03"]
BRANCH_SEGMENTS = tuple(BRANCH_DIRECTION_MAP)
TIMETABLE_PATH = CROWD_INTERIM / "timetable_long.parquet"
AM_SLOTS = ("07:00", "07:30", "08:00", "08:30")
PM_SLOTS = ("18:00", "18:30", "19:00", "19:30")
AM_BUCKETS = ("07-08", "08-09")
PM_BUCKETS = ("18-19", "19-20")


# ── 1. 기준일 전후 data_status ──
def status_tables(
    panel: pd.DataFrame,
    segments: list[dict],
    capacity: dict,
    calibration: pd.DataFrame,
    holidays: pd.DataFrame,
    events: pd.DataFrame | None,
    thresholds: list[float],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """기준일별 `data_status` 분포(146 전/후)와 `no_calibration` 원인별 집계.

    "전"은 `to_congestion_table(..., holiday_fallback=None)`이다 — 146 이전 코드와 같은 동작이라
    같은 프로세스에서 전후를 한 번에 낼 수 있다(재실행·브랜치 전환 없이 비교하려는 의도).
    """
    lookup = build_predictor("lookup", train_panel=panel)
    cal_stations = set(calibration["station_no"].unique())
    branch_only = {
        s
        for seg in segments
        if seg["segment"] in BRANCH_SEGMENTS
        for s in seg["stations"]
        if s not in BRANCH_JUNCTION_STATIONS
    }
    # 146의 원인 분류는 1호선 전용이었다 — 199가 기본값을 넓혔으므로 여기서는 명시한다.
    boundary = truncated_boundary_cells(segments, lines=("1호선",))

    dist_rows: list[dict] = []
    cause_rows: list[dict] = []
    for date in REFERENCE_DATES:
        day = pd.Timestamp(date)
        predicted, _ = predict_day(
            fixed_predictor_factory(lookup),
            panel,
            day,
            segments,
            holidays,
            events,
            override_kind=lookup.kind,
        )
        before = to_congestion_table(
            predicted, segments, capacity, calibration, thresholds, holiday_fallback=None
        )
        after = to_congestion_table(predicted, segments, capacity, calibration, thresholds)
        day_type = str(predicted["day_type"].iloc[0])
        # 146 이전에는 절단면 셀도 그냥 `no_calibration`이었다 — "전" 열을 그 시절 값으로 되돌린다.
        before["data_status"] = before["data_status"].replace(
            {"segment_truncated": "no_calibration"}
        )
        for name, table in (("전(146 이전)", before), ("후(146 적용)", after)):
            counts = table["data_status"].value_counts().to_dict()
            dist_rows.append(
                {
                    "날짜": date,
                    "요일유형": day_type,
                    "시점": name,
                    "셀": len(table),
                    **{k: int(counts.get(k, 0)) for k in STATUS_ORDER},
                }
            )
        # 원인 분류는 **구조적 원인 우선**이다. 공휴일에는 모든 셀이 결측이라, 결번·지선·절단 셀까지
        # "공휴일"로 세면 공휴일 대체로 살아날 셀 수를 과대평가한다.
        miss = before[before["data_status"] == "no_calibration"]
        default = (
            "1~8호선 공휴일" if day_type == "휴일" else "기타(배율 NaN — 타 호선 종점 링크 등)"
        )
        cause = pd.Series(default, index=miss.index)
        cause[~miss["station_no"].isin(cal_stations)] = "결번(배율표에 역 없음)"
        cause[miss["station_no"].isin(branch_only)] = "2호선 지선 방향 라벨"
        cause[
            pd.MultiIndex.from_arrays([miss["station_no"], miss["direction"]]).isin(list(boundary))
        ] = "1호선 절단면 종점 링크"
        for label, n in cause.value_counts().items():
            cause_rows.append({"날짜": date, "요일유형": day_type, "원인": label, "셀": int(n)})
    return pd.DataFrame(dist_rows).fillna(0), pd.DataFrame(cause_rows)


STATUS_ORDER = [
    "ok",
    "calibration_fallback",
    "no_lookup",
    # 199에서 `line1_truncated` → `segment_truncated`(전 절단 구간)로 넓어졌다.
    "segment_truncated",
    "no_calibration",
]


# ── 2. 공휴일을 어느 요일유형으로 접을 것인가 ──
def timetable_day_types(path: Path = TIMETABLE_PATH) -> pd.DataFrame:
    """운행 다이어의 요일유형별 30분 슬롯 편수 — 토요일과 일요일이 별도 다이어인지 확인한다."""
    tt = pd.read_parquet(path)
    tt = tt.dropna(subset=["direction"])
    clock = tt["pass_time"].fillna(tt["departure_time"]).fillna(tt["arrival_time"]).astype("string")
    tt = tt[clock.notna()]
    clock = clock.dropna()
    tt["slot"] = clock.str.slice(0, 2) + np.where(
        clock.str.slice(3, 5).astype(int) < 30, ":00", ":30"
    )
    per = tt.groupby(["day_type", "line", "slot"]).size().rename("trains").reset_index()
    wide = per.pivot_table(index=["line", "slot"], columns="day_type", values="trains")
    rows = []
    for a, b in (("평일", "토요일"), ("토요일", "일요일"), ("평일", "일요일")):
        d = wide[[a, b]].dropna()
        rows.append(
            {
                "비교": f"{a} vs {b}",
                "슬롯수": len(d),
                "편수_MAE": round(float((d[a] - d[b]).abs().mean()), 2),
                "상관": round(float(d[a].corr(d[b])), 4),
                "중위_상대차_%": round(float(((d[b] - d[a]).abs() / d[a]).median() * 100), 2),
            }
        )
    return pd.DataFrame(rows)


def ratio_day_type_gap(calibration: pd.DataFrame) -> pd.DataFrame:
    """1~8호선 배율표에서 요일유형 쌍의 셀별 차이 — 공휴일 대체 후보의 상한을 잰다."""
    cal = calibration[calibration["line"] != "9호선"]
    wide = cal.pivot_table(
        index=["station_no", "direction", "time_slot"], columns="day_type", values="ratio"
    )
    rows = []
    for a, b in (("토요일", "일요일"), ("평일", "일요일"), ("평일", "토요일")):
        d = wide[[a, b]].dropna()
        rel = (d[b] - d[a]).abs() / d[a].abs()
        rows.append(
            {
                "비교(기준 vs 대체)": f"{a} vs {b}",
                "셀": len(d),
                "MAE": round(float((d[a] - d[b]).abs().mean()), 4),
                "상관": round(float(d[a].corr(d[b])), 4),
                "중위_상대차_%": round(float(rel.median() * 100), 2),
                "상대차_90분위_%": round(float(rel.quantile(0.9) * 100), 2),
            }
        )
    return pd.DataFrame(rows)


def holiday_profile_similarity(panel: pd.DataFrame) -> pd.DataFrame:
    """2025 공휴일 승하차 프로파일이 토요일·일요일 중 어느 쪽에 가까운가.

    역×시간대 평균 수요(승차+하차)를 요일유형별로 낸 뒤, 공휴일 프로파일과 각 후보의 절대차·상관을
    잰다. **모양만이 아니라 수준도 본다** — 배율은 수준(배차 보정)까지 담기 때문이다.
    """
    p = panel[panel["date"].dt.year == 2025]
    demand = p.assign(demand=p["boarding"].fillna(0) + p["alighting"].fillna(0))
    prof = (
        demand.groupby(["day_type", "station_no", "time_slot"])["demand"]
        .mean()
        .rename("v")
        .reset_index()
    )
    wide = prof.pivot_table(index=["station_no", "time_slot"], columns="day_type", values="v")
    rows = []
    base = wide["휴일"]
    cands = {
        "토요일": wide["토요일"],
        "일요일": wide["일요일"],
        "토·일 평균": (wide["토요일"] + wide["일요일"]) / 2,
        "평일": wide["평일"],
    }
    for name, cand in cands.items():
        d = pd.concat([base, cand.rename("cand")], axis=1).dropna()
        rel = (d["cand"] - d["휴일"]).abs() / d["휴일"].replace(0, np.nan).abs()
        rows.append(
            {
                "공휴일 대비 후보": name,
                "셀": len(d),
                "MAE_명": round(float((d["cand"] - d["휴일"]).abs().mean()), 1),
                "상관": round(float(d["cand"].corr(d["휴일"])), 4),
                "중위_상대차_%": round(float(rel.median() * 100), 2),
            }
        )
    return pd.DataFrame(rows)


# ── 3. 2호선 지선 방향 대응 ──
def branch_direction_evidence(
    panel: pd.DataFrame, segments: list[dict], capacity: dict, calibration: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """지선의 (상선/하선) ↔ (내선/외선) 대응 후보 두 가지를 출퇴근 비대칭·상관으로 가른다."""
    segs = [s for s in segments if s["segment"] in BRANCH_SEGMENTS]
    stations = sorted({s for seg in segs for s in seg["stations"]})
    sub = panel[panel["station_no"].isin(stations)]
    raw = recursive_congestion(sub, segs, capacity)
    day_type = panel[["date", "station_no", "day_type"]].drop_duplicates(["date", "station_no"])
    raw = raw.merge(day_type, on=["date", "station_no"], how="left")
    raw = raw[(raw["day_type"] == "평일") & (~raw["station_no"].isin(BRANCH_JUNCTION_STATIONS))]

    hourly = (
        raw.groupby(["segment", "station_no", "direction", "time_slot"])["congestion_raw_pct"]
        .mean()
        .reset_index()
    )
    peak = hourly.pivot_table(
        index=["segment", "station_no", "direction"],
        columns="time_slot",
        values="congestion_raw_pct",
    )
    peak["AM"] = peak[list(AM_BUCKETS)].mean(axis=1)
    peak["PM"] = peak[list(PM_BUCKETS)].mean(axis=1)

    cal = calibration[
        calibration["station_no"].isin(stations)
        & (~calibration["station_no"].isin(BRANCH_JUNCTION_STATIONS))
        & (calibration["day_type"] == "평일")
    ]
    meas = cal.pivot_table(
        index=["station_no", "direction"], columns="time_slot", values="congestion_pct"
    )
    meas["AM"] = meas[list(AM_SLOTS)].mean(axis=1)
    meas["PM"] = meas[list(PM_SLOTS)].mean(axis=1)

    raw_side = (
        peak[["AM", "PM"]]
        .reset_index()
        .assign(원천="재귀식 raw")
        .rename(columns={"direction": "방향"})
    )
    meas_side = (
        meas[["AM", "PM"]]
        .reset_index()
        .assign(원천="실측 스냅샷")
        .rename(columns={"direction": "방향"})
    )
    seg_of = {s: seg["segment"] for seg in segs for s in seg["stations"]}
    meas_side["segment"] = meas_side["station_no"].map(seg_of)
    asym = pd.concat([raw_side, meas_side], ignore_index=True)
    asym["AM"] = asym["AM"].round(1)
    asym["PM"] = asym["PM"].round(1)
    asym["AM_우세"] = asym["AM"] > asym["PM"]
    asym = asym[["segment", "station_no", "원천", "방향", "AM", "PM", "AM_우세"]]

    # 후보별 상관 — 30분으로 펼친 raw 평균 vs 실측
    g = hourly.copy()
    g["time_slot_30min"] = g["time_slot"].map(hour_bucket_to_30min_slots)
    g = g.explode("time_slot_30min")
    long_meas = cal[["station_no", "direction", "time_slot", "congestion_pct"]].rename(
        columns={"direction": "meas_dir", "time_slot": "time_slot_30min"}
    )
    rows = []
    candidates = {
        "A: 하선→내선 / 상선→외선": {ASCENDING: "내선", DESCENDING: "외선"},
        "B: 하선→외선 / 상선→내선": {ASCENDING: "외선", DESCENDING: "내선"},
    }
    for name, mapping in candidates.items():
        gg = g.assign(meas_dir=g["direction"].map(mapping))
        m = gg.merge(
            long_meas, on=["station_no", "meas_dir", "time_slot_30min"], how="inner"
        ).dropna(subset=["congestion_raw_pct", "congestion_pct"])
        for seg_name, d in m.groupby("segment"):
            rows.append(
                {
                    "지선": seg_name,
                    "후보": name,
                    "셀": len(d),
                    "피어슨": round(float(d["congestion_raw_pct"].corr(d["congestion_pct"])), 4),
                    "스피어만": round(
                        float(d["congestion_raw_pct"].corr(d["congestion_pct"], method="spearman")),
                        4,
                    ),
                }
            )
    return asym.sort_values(["segment", "station_no", "원천", "방향"]), pd.DataFrame(
        rows
    ).sort_values(["지선", "후보"])


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--out", default=str(_HERE / "RESULTS_draft.md"))
    args = ap.parse_args(argv)

    chunks: list[str] = []

    def emit(title: str, frame: pd.DataFrame) -> None:
        print(f"\n### {title}", flush=True)
        print(frame.to_string(index=False), flush=True)
        chunks.append(f"### {title}\n\n{to_markdown(frame)}\n")

    settings = get_settings()
    panel = load_panel(with_events=True)
    holidays = load_holidays()
    events_path = CROWD_PROCESSED / EVENTS_NAME
    events = pd.read_parquet(events_path) if events_path.exists() else None
    segments, gaps = resolved_segments(panel)
    capacity = load_capacity()
    calibration = pd.read_parquet(CROWD_PROCESSED / CALIBRATION_NAME)
    print(
        f"[입력] 패널 {len(panel):,}행 · 역 {panel['station_no'].nunique()}개 · 결번 {len(gaps)}건"
    )

    dist, cause = status_tables(
        panel, segments, capacity, calibration, holidays, events, settings.grade_thresholds
    )
    emit("1-A. 기준일 `data_status` 분포 — 146 전/후", dist)
    emit("1-B. `no_calibration` 원인별(146 이전 기준)", cause)

    emit("2-A. 운행 다이어 요일유형 — 공휴일 다이어는 없다", timetable_day_types())
    emit("2-B. 1~8호선 배율표 요일유형 쌍별 차이", ratio_day_type_gap(calibration))
    emit(
        "2-C. 2025 공휴일 승하차 프로파일과 후보 요일유형의 거리", holiday_profile_similarity(panel)
    )

    asym, corr = branch_direction_evidence(panel, segments, capacity, calibration)
    emit("3-A. 2호선 지선 평일 출퇴근 비대칭 — 실측 vs 재귀식", asym)
    emit("3-B. 2호선 지선 방향 대응 후보별 상관", corr)

    out = Path(args.out)
    out.write_text("\n".join(chunks), encoding="utf-8")
    store = CROWD_INTERIM / "validation"
    store.mkdir(parents=True, exist_ok=True)
    dist.to_parquet(store / "congestion_criteria_status.parquet", index=False)
    cause.to_parquet(store / "congestion_criteria_causes.parquet", index=False)
    print(f"\n[저장] {out} · {store / 'congestion_criteria_status.parquet'}")


if __name__ == "__main__":
    main(sys.argv[1:])
