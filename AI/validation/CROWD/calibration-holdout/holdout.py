"""142 1단계 — 배율표(88)의 연도 홀드아웃. 변환 층에 대한 유일한 "진짜" 검증.

## 왜 필요한가

`crowd_congestion_calibration.parquet`의 배율은 **분자가 그 스냅샷 자체**다
(`ratio = 실측_30분 ÷ mean_날짜(raw_1시간)`). 그래서 같은 스냅샷으로 되돌려 재는 MAE는
성능이 아니라 항등식이고, 146 §4-B가 이미 순환 참조임을 밝혀 뒀다. 배율표를 **다른 연도**로
적합해 이 연도를 맞히게 하면 순환이 끊긴다 — 공공데이터포털 15071311(= 서울 열린데이터광장
OA-12928)이 연도판을 따로 내려주므로 가능하다.

## 설계

    배율표 = A연도 스냅샷 ÷ A연도 승하차의 재귀식 raw 평균      (적합)
    예측(B) = 배율표 × B연도 승하차의 재귀식 raw 평균           (적용)
    정답    = B연도 스냅샷

배율이 셀 안에서 상수이므로 `mean_날짜(raw_B × ratio) = mean_날짜(raw_B) × ratio`다 —
날짜별로 곱한 뒤 평균 내는 것과 같고, 식을 펴면 예측은

    예측(B) = 스냅샷(A) × raw평균(B) / raw평균(A)

이 된다. 즉 **파이프라인이 전년도 표에 얹는 것은 "재귀식이 본 연도 대비 변화율" 하나**이고,
대조군 `copy_prev`(전년도 표 복사)는 그 변화율을 1로 두는 안이다. 두 안의 차이가 곧
"재귀식 + 배율 구조가 연도 변화를 따라가는가"의 답이다.

대조군 4종:

| 코드 | 예측 | 뜻 |
| --- | --- | --- |
| `pipeline` | 셀별 배율 × raw평균(B) | 지금 파이프라인 |
| `copy_prev` | 스냅샷(A) 그대로 | 우리가 이겨야 할 최소선 |
| `scale_only` | s·raw평균(B), s는 방향×요일유형×30분마다 하나 | 역 자유도를 뺀 거친 적합(146 §4-C) |
| `scale_const` | s·raw평균(B) + c | 위 + 상수항(경계 유입) |

## 쓰는 원천

- 스냅샷 연도판: `data/CROWD/raw/congestion_snapshots/`(gitignore). 2026-09-14에
  OA-12928에서 내려받았다. **`raw/` 바로 밑이 아니라 하위 폴더에 둔 이유**는
  `parsers_crowd.build_congestion_long()`이 `raw/*지하철혼잡도정보*.csv`를 전부 읽어
  이어 붙이기 때문이다 — 연도판을 같은 자리에 두면 스냅샷 여러 벌이 겹쳐 쌓인다.
- 승하차: `data/CROWD/interim/crowd_daily_ridership_long.parquet`(2023~2025).
- 재귀식·배율 적용·등급은 전부 `app.CROWD.pipeline.congestion`을 그대로 쓴다(재구현 금지).

**역 집합은 연도와 무관하게 패널(273역)로 고정한다.** 원천 승하차의 역 수가 연도마다
다른데(2023년 282 / 2024년 273), 세그먼트 구성이 달라지면 같은 역의 raw 값이 연도별로
다른 링크 구조에서 나와 비교가 흐려진다.

## 199 — 변형을 같은 심판으로 잰다

이 하네스가 199(배율표 재적합)의 **out-of-sample 심판**이다. 세 축을 인자로 받아 임의 변형을 같은
방식으로 채점한다 — 기본값은 142가 낸 수치를 그대로 재현한다.

| 인자 | 뜻 | 기본 |
| --- | --- | --- |
| `--branch-map / --no-branch-map` | 2호선 지선 상·하선을 내/외선으로 접고 조인할 것인가(A) | 켜짐 |
| `--fit-window {year,multi,season}` | 적합 연도의 승하차 평균 창(C) — 그 해만 / 두 해 / 기준일 ±13주 | `year` |

실행(폴더명에 하이픈이 있어 `python -m`이 아니라 다른 `*-check` 폴더와 같은 파일 경로 호출이다):
    cd AI
    python validation/CROWD/calibration-holdout/holdout.py --fit-year 2024 --eval-year 2025
    python validation/CROWD/calibration-holdout/holdout.py --fit-year 2023 --eval-year 2024
예상: 연도별 재귀식 1회 2~4분(결과는 `interim/validation/`에 캐시, 두 번째부터 수 초).
"""

from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

_HERE = Path(__file__).resolve().parent
AI_ROOT = _HERE.parents[2]
if str(AI_ROOT) not in sys.path:
    sys.path.insert(0, str(AI_ROOT))

from app.CROWD.pipeline import congestion
from DATA_ENGINE.eda.build_congestion_label import (
    load_capacity,
    load_topology,
    resolve_segments,
)
from DATA_ENGINE.eda.build_crowd_panel import attach_calendar
from DATA_ENGINE.eda.parsers_crowd import load_seoul_congestion_csv

CROWD_RAW = AI_ROOT / "data" / "CROWD" / "raw"
CROWD_INTERIM = AI_ROOT / "data" / "CROWD" / "interim"
CROWD_PROCESSED = AI_ROOT / "data" / "CROWD" / "processed"
VALIDATION_DIR = CROWD_INTERIM / "validation"

SNAPSHOT_DIR = CROWD_RAW / "congestion_snapshots"
# 연도판 파일명 — 포털 원본 이름 그대로. 2025판만 기준일이 11-30이다(분기 갱신본 중 최신).
SNAPSHOT_FILES = {
    2023: "서울교통공사_지하철혼잡도정보_20231231.csv",
    2024: "서울교통공사_지하철혼잡도정보_20241231.csv",
    2025: "서울교통공사_지하철혼잡도정보_20251130.csv",
}
RIDERSHIP_LONG = CROWD_INTERIM / "crowd_daily_ridership_long.parquet"
PANEL_NAME = "crowd_panel_2024_2025.parquet"

# 90·146이 쓰는 분포 기준 등급(임계값 확정은 팀 논의 A-2 — 여기서는 기본값만 본다).
GRADE_THRESHOLDS = (50.0, 100.0)

METHODS = ("pipeline", "copy_prev", "scale_only", "scale_const")
GROUP_COLS = ["direction", "day_type", "time_slot_30min"]

# 연도판 스냅샷의 기준일 — 적합 창 `season`이 이 날짜 ±`SEASON_WEEKS`주를 쓴다.
SNAPSHOT_REFERENCE = {2023: "2023-12-31", 2024: "2024-12-31", 2025: "2025-11-30"}
SEASON_WEEKS = 13


@dataclass(frozen=True)
class HoldoutVariant:
    """채점할 배율 적합 규칙(199). 기본값은 142가 낸 수치를 그대로 재현한다."""

    branch_map: bool = True
    fit_window: str = "year"  # year / multi / season

    @property
    def code(self) -> str:
        head = "branch" if self.branch_map else "nobranch"
        return f"{head}_{self.fit_window}"

    def fit_years(self, fit_year: int, eval_year: int) -> tuple[int, ...]:
        """적합 연도 raw 평균에 넣을 승하차 연도. `multi`는 평가 연도 승하차까지 평균에 넣는다.

        `multi`는 현행 배율표의 구조(2025판 스냅샷 + 2024~2026 승하차 평균)를 홀드아웃에서 흉내
        내려는 것이라 **평가 연도 승하차가 분모에 들어간다** — 정답(평가 연도 스냅샷)은 여전히
        out-of-sample이지만 완전한 out-of-sample은 아니다. C절 판정에서 이 한계를 그대로 적는다.
        """
        return (fit_year, eval_year) if self.fit_window == "multi" else (fit_year,)

    def season_range(self, fit_year: int) -> tuple[pd.Timestamp, pd.Timestamp] | None:
        if self.fit_window != "season":
            return None
        ref = pd.Timestamp(SNAPSHOT_REFERENCE[fit_year])
        span = pd.Timedelta(weeks=SEASON_WEEKS)
        return ref - span, ref + span


# ── 원천 ──
def panel_stations() -> set[int]:
    """학습 패널(273역)의 역 집합 — 연도 간 세그먼트 구성을 고정하는 데 쓴다."""
    panel = pd.read_parquet(CROWD_PROCESSED / PANEL_NAME, columns=["station_no"])
    return set(panel["station_no"].astype("int64").unique())


def load_snapshot(year: int) -> pd.DataFrame:
    """연도판 스냅샷(1~8호선)을 (역·호선·방향·요일유형·30분) 프레임으로."""
    path = SNAPSHOT_DIR / SNAPSHOT_FILES[year]
    if not path.exists():
        raise FileNotFoundError(
            f"{year}년판 스냅샷이 없다: {path}\n"
            "OA-12928(= 포털 15071311) 파일 목록에서 내려받아 이 경로에 원본 파일명 그대로 둘 것."
        )
    snap = load_seoul_congestion_csv(path)
    snap = snap.dropna(subset=["congestion_pct", "station_no"])
    snap["station_no"] = snap["station_no"].astype("int64")
    snap = snap.rename(columns={"time_slot": "time_slot_30min"})
    return snap[
        ["station_no", "line", "direction", "day_type", "time_slot_30min", "congestion_pct"]
    ].reset_index(drop=True)


def yearly_panel(
    years: tuple[int, ...],
    stations: set[int],
    season: tuple[pd.Timestamp, pd.Timestamp] | None = None,
) -> pd.DataFrame:
    """해당 연도들의 승하차를 재귀식 입력 격자(date·station_no·time_slot·boarding·alighting)로.

    `build_crowd_panel`의 전체 패널(기상·좌표·이벤트까지 붙인다)은 여기서 필요 없다 —
    재귀식이 읽는 다섯 컬럼만 만든다. 2023년은 기상 원천이 없어 전체 패널을 만들 수도 없다
    (`build_crowd_panel` 모듈 docstring). 이 축약이 홀드아웃에 영향을 주지 않는 이유는
    재귀식이 승하차 외의 컬럼을 쓰지 않기 때문이다.
    """
    rid = pd.read_parquet(
        RIDERSHIP_LONG, columns=["date", "station_no", "time_slot", "direction", "passengers"]
    )
    rid = rid[rid["date"].dt.year.isin(years)]
    if season is not None:
        rid = rid[(rid["date"] >= season[0]) & (rid["date"] <= season[1])]
    rid["station_no"] = rid["station_no"].astype("int64")
    rid = rid[rid["station_no"].isin(stations)]
    if rid.empty:
        raise ValueError(f"{years}년 승하차가 원천에 없다: {RIDERSHIP_LONG}")
    wide = rid.pivot_table(
        index=["date", "station_no", "time_slot"],
        columns="direction",
        values="passengers",
        aggfunc="sum",
    ).reset_index()
    wide.columns.name = None
    for col in ("boarding", "alighting"):
        if col not in wide.columns:
            wide[col] = 0.0
    return wide


def raw_mean_cache_name(
    years: tuple[int, ...], branch_map: bool, season: tuple[pd.Timestamp, pd.Timestamp] | None
) -> str:
    """캐시 파일명. 기본 조합(한 해·대응표 켬·창 없음)은 142가 만든 이름을 그대로 쓴다."""
    name = f"calibration_holdout_rawmean_{'-'.join(str(y) for y in years)}"
    if not branch_map:
        name += "_nobranch"
    if season is not None:
        name += f"_season{season[0]:%Y%m%d}"
    return f"{name}.parquet"


def yearly_raw_mean(
    years: int | tuple[int, ...],
    branch_map: bool = True,
    season: tuple[pd.Timestamp, pd.Timestamp] | None = None,
    rebuild: bool = False,
) -> pd.DataFrame:
    """(역·호선·방향·요일유형·1시간) 재귀식 raw 혼잡도의 날짜 평균. 결과는 캐시한다.

    방향·요일유형은 **스냅샷 체계로 접은 뒤** 집계한다(`congestion.bucket_*`) — `branch_map`을 켜면
    2호선 지선의 상선/하선을 내선/외선으로 옮기는 146 대응표까지 서빙 경로와 똑같이 적용한다
    (199 A의 대조군을 만들려면 끈다). 1~8호선 공휴일은 대응 구간이 없어
    (`holiday_fallback=None`) 여기서 떨어진다.
    """
    years = (years,) if isinstance(years, int) else tuple(years)
    cache = VALIDATION_DIR / raw_mean_cache_name(years, branch_map, season)
    if cache.exists() and not rebuild:
        return pd.read_parquet(cache)

    t0 = time.time()
    stations = panel_stations()
    panel = yearly_panel(years, stations, season)
    segments, _ = resolve_segments(load_topology(), stations)
    labels = congestion.recursive_congestion(panel, segments, load_capacity())

    calendar = attach_calendar(pd.DataFrame({"date": panel["date"].drop_duplicates()}))
    labels = labels.merge(calendar[["date", "day_type"]], on="date", how="left")
    labels["day_type_bucket"] = congestion.bucket_day_type(
        labels["line"], labels["day_type"], holiday_fallback=None
    )
    labels["direction_bucket"] = (
        congestion.bucket_direction(labels["segment"], labels["direction"], labels["station_no"])
        if branch_map
        else labels["direction"]
    )
    labels = labels.dropna(subset=["day_type_bucket"])

    out = (
        labels.groupby(
            ["station_no", "line", "direction_bucket", "day_type_bucket", "time_slot"],
            observed=True,
        )["congestion_raw_pct"]
        .agg(raw_mean="mean", n_dates="count")
        .reset_index()
        .rename(columns={"direction_bucket": "direction", "day_type_bucket": "day_type"})
    )
    VALIDATION_DIR.mkdir(parents=True, exist_ok=True)
    out.to_parquet(cache, index=False)
    print(
        f"[재귀식] {years} {len(panel):,}행 → raw 평균 {len(out):,}셀 · {time.time() - t0:.0f}s "
        f"({cache.name})",
        flush=True,
    )
    return out


def discontinuous_stations(fit_year: int, eval_year: int, threshold: float = 0.25) -> set[int]:
    """두 해 사이에 **원천 자체가 끊긴** 역 — 연간 승하차 총량이 ±threshold를 넘게 변한 역.

    개통·연장(8호선 별내선 암사역사공원 2810은 2024-08 개통이라 2024 평균이 7개월치 0으로
    희석된다)과 집계 정의 변화 의심 구간(서울역 150, 2024→2025 +32% — 141이 남긴 미해결)을
    잡아낸다. 배율 구조의 문제가 아니라 입력이 바뀐 것이므로 슬라이스로 갈라 본다.
    한쪽 해에만 있는 역(결번·연장 구간)도 같이 잡힌다.
    """
    rid = pd.read_parquet(RIDERSHIP_LONG, columns=["date", "station_no", "passengers"])
    rid["year"] = rid["date"].dt.year
    total = rid.pivot_table(index="station_no", columns="year", values="passengers", aggfunc="sum")
    for year in (fit_year, eval_year):
        if year not in total.columns:
            raise ValueError(f"{year}년 승하차가 없다")
    change = total[eval_year] / total[fit_year]
    flagged = change[(change > 1 + threshold) | (change < 1 - threshold) | change.isna()]
    return {int(s) for s in flagged.index}


def classify_source_continuity(cells: pd.DataFrame, flagged: set[int]) -> pd.Series:
    """셀을 원천 연속성으로 3분류 — 불연속은 역 하나로 끝나지 않는다.

    재귀식은 노선을 따라 누적하므로 한 역의 불연속이 같은 호선의 다른 역 재차까지 민다
    (서울역 승하차가 뛰면 종로3가·종로5가 하선 아침 raw가 같이 뛴다). 그래서 "그 역"과
    "그 호선의 나머지 역"을 갈라 둔다.
    """
    bad_lines = set(cells.loc[cells["station_no"].isin(flagged), "line"].unique())
    out = pd.Series("연속", index=cells.index, dtype=object)
    out[cells["line"].isin(bad_lines)] = "불연속 호선의 다른 역"
    out[cells["station_no"].isin(flagged)] = "불연속 역"
    return out


def expand_to_30min(raw_mean: pd.DataFrame) -> pd.DataFrame:
    """1시간 버킷의 raw 평균을 스냅샷과 같은 30분 축으로 펼친다(값은 같은 값이 둘로 간다)."""
    frame = raw_mean.copy()
    frame["time_slot_30min"] = frame["time_slot"].map(congestion.hour_bucket_to_30min_slots)
    return frame.explode("time_slot_30min", ignore_index=True).drop(columns=["time_slot"])


# ── 적합(순수 함수) ──
def fit_linear_by_group(
    frame: pd.DataFrame, group_cols: list[str], x: str, y: str, with_const: bool
) -> pd.DataFrame:
    """그룹마다 `y ≈ slope·x (+ intercept)` 최소제곱 계수. 146 §4-C와 같은 형태.

    셀별 배율은 역마다 자유도를 하나씩 갖지만 이쪽은 그룹당 1~2개뿐이다 — 셀별 배율이
    연도를 넘어 살아남는 값인지, 그 해 표본을 외운 값인지 가르는 대조군이다.
    표본이 모자라(상수항까지 재려면 2점 이상) 풀 수 없는 그룹은 계수를 NaN으로 둔다.
    """
    rows = []
    for key, sub in frame.groupby(group_cols, observed=True, sort=True):
        xs = sub[x].to_numpy(dtype=float)
        ys = sub[y].to_numpy(dtype=float)
        ok = np.isfinite(xs) & np.isfinite(ys)
        xs, ys = xs[ok], ys[ok]
        slope, intercept = np.nan, 0.0
        if with_const:
            if len(xs) >= 2 and np.ptp(xs) > 0:
                slope, intercept = np.polyfit(xs, ys, 1)
        else:
            denom = float((xs * xs).sum())
            if denom > 0:
                slope = float((xs * ys).sum() / denom)
        key_tuple = key if isinstance(key, tuple) else (key,)
        rows.append(
            {
                **dict(zip(group_cols, key_tuple)),
                "slope": float(slope),
                "intercept": float(intercept),
            }
        )
    return pd.DataFrame(rows, columns=[*group_cols, "slope", "intercept"])


def apply_linear(
    frame: pd.DataFrame, coefs: pd.DataFrame, group_cols: list[str], x: str
) -> pd.Series:
    """`fit_linear_by_group` 계수를 다른 연도 raw에 적용한다."""
    merged = frame[[*group_cols, x]].merge(coefs, on=group_cols, how="left")
    return pd.Series(
        merged["slope"].to_numpy() * merged[x].to_numpy() + merged["intercept"].to_numpy(),
        index=frame.index,
    )


# ── 지표(순수 함수) ──
def cell_metrics(truth: pd.Series, pred: pd.Series) -> dict[str, float]:
    """셀 단위 MAE(%p)·RMSE(%p)·피어슨 상관·등급(50/100) 일치율."""
    t = pd.Series(truth).astype(float).reset_index(drop=True)
    p = pd.Series(pred).astype(float).reset_index(drop=True)
    ok = t.notna() & p.notna()
    t, p = t[ok], p[ok]
    n = len(t)
    if n == 0:
        return {"n": 0, "mae": np.nan, "rmse": np.nan, "corr": np.nan, "grade_agree_%": np.nan}
    err = p - t
    corr = float(t.corr(p)) if n > 1 and t.std() > 0 and p.std() > 0 else np.nan
    g_t = congestion.grade(t, GRADE_THRESHOLDS)
    g_p = congestion.grade(p, GRADE_THRESHOLDS)
    return {
        "n": n,
        "mae": float(err.abs().mean()),
        "rmse": float(np.sqrt((err**2).mean())),
        "corr": corr,
        "grade_agree_%": float((g_t == g_p).mean() * 100),
    }


def metrics_by_axis(cells: pd.DataFrame, method: str) -> list[dict]:
    """전체 + 방향·요일유형·호선 슬라이스."""
    axes = {
        "전체": pd.Series("전체", index=cells.index),
        "방향": cells["direction"],
        "요일유형": cells["day_type"],
        "호선": cells["line"],
        "원천 연속성": cells["source_continuity"],
        # 199 B의 채택 규칙이 "경계 셀 MAE ≤ 해당 호선 평균 × 2"라 호선별로 갈라 둔다.
        "경계 셀": cells["line"].where(cells.get("is_boundary", False), "내부"),
    }
    rows = []
    for axis, series in axes.items():
        for group, idx in series.groupby(series, observed=True).groups.items():
            sub = cells.loc[idx]
            rows.append(
                {
                    "method": method,
                    "axis": axis,
                    "group": str(group),
                    **cell_metrics(sub["truth"], sub[f"pred_{method}"]),
                }
            )
    return rows


# ── 실행 ──
def build_cells(
    fit_year: int,
    eval_year: int,
    variant: HoldoutVariant | None = None,
    rebuild: bool = False,
) -> pd.DataFrame:
    """평가 셀 한 장 — 정답(B스냅샷) + A스냅샷 + 두 해의 raw 평균 + 네 안의 예측."""
    variant = variant or HoldoutVariant()
    key = ["station_no", "direction", "day_type", "time_slot_30min"]
    snap_fit = load_snapshot(fit_year).rename(columns={"congestion_pct": "snap_fit"})
    snap_eval = load_snapshot(eval_year).rename(columns={"congestion_pct": "truth"})
    raw_fit = expand_to_30min(
        yearly_raw_mean(
            variant.fit_years(fit_year, eval_year),
            branch_map=variant.branch_map,
            season=variant.season_range(fit_year),
            rebuild=rebuild,
        )
    ).rename(columns={"raw_mean": "raw_fit", "n_dates": "n_fit"})
    raw_eval = expand_to_30min(
        yearly_raw_mean(eval_year, branch_map=variant.branch_map, rebuild=rebuild)
    ).rename(columns={"raw_mean": "raw_eval", "n_dates": "n_eval"})

    cells = snap_eval.merge(snap_fit.drop(columns=["line"]), on=key, how="left")
    cells = cells.merge(raw_fit.drop(columns=["line"]), on=key, how="left")
    cells = cells.merge(raw_eval.drop(columns=["line"]), on=key, how="left")
    cells["raw_fit_adj"] = cells["raw_fit"]
    cells["raw_eval_adj"] = cells["raw_eval"]
    cells["is_boundary"] = False

    total = len(cells)
    cells = cells[
        cells["truth"].notna()
        & cells["snap_fit"].notna()
        & cells["raw_fit"].notna()
        & (cells["raw_fit_adj"] > 0)
        & cells["raw_eval"].notna()
    ].reset_index(drop=True)
    print(
        f"[셀] {eval_year} 스냅샷 {total:,}셀 중 네 안을 모두 낼 수 있는 셀 "
        f"{len(cells):,} ({len(cells) / total * 100:.1f}%) · 변형 {variant.code}"
        f" · 경계 셀 {int(cells['is_boundary'].sum()):,}",
        flush=True,
    )

    flagged = discontinuous_stations(fit_year, eval_year)
    cells["source_continuity"] = classify_source_continuity(cells, flagged)
    print(
        "[원천] 연간 승하차가 ±25% 넘게 변한 역: "
        f"{sorted(flagged & set(cells['station_no'].unique()))}",
        flush=True,
    )

    cells["pred_copy_prev"] = cells["snap_fit"]
    cells["pred_pipeline"] = cells["snap_fit"] / cells["raw_fit_adj"] * cells["raw_eval_adj"]
    for method, with_const in (("scale_only", False), ("scale_const", True)):
        coefs = fit_linear_by_group(cells, GROUP_COLS, "raw_fit_adj", "snap_fit", with_const)
        cells[f"pred_{method}"] = apply_linear(cells, coefs, GROUP_COLS, "raw_eval_adj")
    return cells


def verdict(metrics: pd.DataFrame) -> str:
    """계획이 사전에 고정한 판정 문장(전체 축, 파이프라인 vs 전년도 표 복사)."""
    total = metrics[metrics["axis"] == "전체"].set_index("method")
    d_mae = total.loc["pipeline", "mae"] - total.loc["copy_prev", "mae"]
    d_grade = total.loc["pipeline", "grade_agree_%"] - total.loc["copy_prev", "grade_agree_%"]
    if d_mae < 0 and d_grade > 0:
        head = "변환 층이 전년도 표 복사를 이긴다"
    elif d_mae < 0 or d_grade > 0:
        head = "변환 층이 전년도 표 복사와 갈린다(한 지표만 우세)"
    else:
        head = "변환 층이 전년도 표 복사를 이기지 못한다 → 공식표 재현 수준으로 서술한다"
    return (
        f"{head} — MAE {d_mae:+.3f}%p, 등급 일치율 {d_grade:+.2f}%p "
        f"(파이프라인 MAE {total.loc['pipeline', 'mae']:.3f} / 일치율 "
        f"{total.loc['pipeline', 'grade_agree_%']:.2f}%, 복사 MAE "
        f"{total.loc['copy_prev', 'mae']:.3f} / 일치율 {total.loc['copy_prev', 'grade_agree_%']:.2f}%)"
    )


def run_holdout(
    fit_year: int,
    eval_year: int,
    variant: HoldoutVariant | None = None,
    rebuild: bool = False,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    variant = variant or HoldoutVariant()
    cells = build_cells(fit_year, eval_year, variant, rebuild=rebuild)
    rows: list[dict] = []
    for method in METHODS:
        rows += metrics_by_axis(cells, method)
    metrics = pd.DataFrame(rows).assign(
        fit_year=fit_year, eval_year=eval_year, variant=variant.code
    )
    return metrics, cells


def summarize(metrics: pd.DataFrame) -> list[tuple[str, pd.DataFrame]]:
    out = []
    total = metrics[metrics["axis"] == "전체"].set_index("method").loc[list(METHODS)]
    out.append(
        ("전체", total.reset_index()[["method", "n", "mae", "rmse", "corr", "grade_agree_%"]])
    )
    for axis in ("방향", "요일유형", "호선", "원천 연속성", "경계 셀"):
        sub = metrics[metrics["axis"] == axis]
        for value, title in (("mae", "MAE %p"), ("grade_agree_%", "등급 일치율 %")):
            piv = sub.pivot_table(index="group", columns="method", values=value)
            out.append((f"{axis}별 {title}", piv.reindex(columns=list(METHODS)).reset_index()))
    return out


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--fit-year", type=int, default=2024, choices=sorted(SNAPSHOT_FILES))
    ap.add_argument("--eval-year", type=int, default=2025, choices=sorted(SNAPSHOT_FILES))
    ap.add_argument("--rebuild", action="store_true", help="raw 평균 캐시를 다시 만든다")
    ap.add_argument("--save-results", default=None, help="지표 long parquet 경로")
    ap.add_argument("--save-cells", default=None, help="셀 단위 parquet 경로(노트북용)")
    ap.add_argument(
        "--no-branch-map",
        dest="branch_map",
        action="store_false",
        help="2호선 지선 방향 대응을 끈다(199 A의 대조군)",
    )
    ap.add_argument("--fit-window", default="year", choices=("year", "multi", "season"))
    args = ap.parse_args(argv)
    if args.fit_year == args.eval_year:
        raise SystemExit("--fit-year와 --eval-year는 달라야 한다(홀드아웃이 성립하지 않는다).")

    variant = HoldoutVariant(branch_map=args.branch_map, fit_window=args.fit_window)
    metrics, cells = run_holdout(args.fit_year, args.eval_year, variant, rebuild=args.rebuild)
    for title, table in summarize(metrics):
        print(f"\n### {title}\n{table.round(3).to_string(index=False)}")
    print(f"\n[판정] {verdict(metrics)}")

    default_metrics = (
        VALIDATION_DIR / f"calibration_holdout_{args.fit_year}_{args.eval_year}.parquet"
    )
    default_cells = (
        VALIDATION_DIR / f"calibration_holdout_cells_{args.fit_year}_{args.eval_year}.parquet"
    )
    for path, frame in (
        (Path(args.save_results) if args.save_results else default_metrics, metrics),
        (Path(args.save_cells) if args.save_cells else default_cells, cells),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        frame.to_parquet(path, index=False)
        print(f"저장: {path}")


if __name__ == "__main__":
    main(sys.argv[1:])
