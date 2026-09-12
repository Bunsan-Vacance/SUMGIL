"""데이터·라벨·분해 분석 결과 그림 세트 — 136번. 수치 기록(RESULTS.md)을 그림으로.

그림 하나 = 함수 하나(`fig_*`). 입력은 이미 있는 parquet/캐시이고, 그림 코드에 수치를 하드코딩하지 않는다.
없는 입력은 그 그림만 건너뛰고 마지막에 인벤토리로 알린다(조용히 빈 그림을 내지 않는다). 무거운 입력
(패널 400만 행)은 한 번만 읽어 함수들이 공유한다(`AI/CLAUDE.md` 실험 효율).

| # | 이름 | 내용 | 출처 |
| --- | --- | --- | --- |
| 1 | panel_heatmap_station_slot_<요일유형> | 역(호선순) × 20슬롯 승차 평균 히트맵 | 88 |
| 2 | panel_daily_total_by_line | 호선별 일 총 승차 7일 이동평균, 공휴일 표시 | 88 |
| 3 | direction_validation_scatter | 재귀식 raw 평균 vs 실측 스냅샷(방향별), 호선별 상관 | 88 방향 검증 |
| 4 | calibration_ratio_heatmap | 호선별 역 × 30분 배율(평일, 하선/내선) | 88 배율표 |
| 5 | half_hour_share_curve | 시간대별 후반 30분 비중 평균·표준편차 띠 | 135 1층 |
| 6 | residual_concentration | 잔차 쏠림 상위 15역 + 시간대·요일 | 87·90 |
| 7 | station_residual_timeseries | 서울역·종합운동장 2025 일별 잔차, 경기일 표시 | 90 미해결 |
| 8 | feature_set_improvement_steps | 세트별 RMSE/MAE 개선율 계단, 실시간 필요 세트 구분 | 89 |
| 9 | grade_threshold_sensitivity | 임계치 후보별 등급 분포 + 일치율 | 90 |
| 10 | train_load_gangnam_rush | 강남 내선 08시대 열차별 재차 막대, 배차 주석 | 135 2층 |
| 11 | headway_distribution_by_line | 호선별 배차 간격 분포(러시/비러시) | 135 |
| 12 | line9_* | 기존 9호선 히트맵·군집 재생성(report_crowd 위임) | 88 |
| 13 | sim_predictor_comparison | 시뮬레이션 정답 위 예측기 4종 등급 일치율·MAE, 시나리오별 | 92 |
| 14 | sim_sensitivity_grid | 생성기 가정(σ_shape × 도착 혼합) 격자에서 mix−flat 일치율 차이 | 92 |
| 15 | split_by_line | 전역 vs 호선별·6호선 분리·군집 모델의 호선별 RMSE 개선율 | 93 |

8번 입력(`compare_results.parquet`)은 `compare_models.py --save-results`로 만든다. 9번은
`grade_sensitivity.py --save-cells`의 셀 표.

**선택 인자(141).** 모든 `fig_*`는 기본값이 위 표의 그림이고, 호선·역·요일유형·타깃 같은 선택 인자를
받는다(`fig_panel_heatmap(inp, lines=["2호선"], day_types=["평일"])`). 기본값이 아닐 때 저장 파일명에
선택이 접미로 붙어 기본 그림을 덮어쓰지 않는다. 노트북에서는 `fs.apply(inline=True)` 뒤 호출하면
figure가 그대로 셀에 그려진다(`crowd_eda.ipynb`).

실행:
    cd AI
    python -m DATA_ENGINE.eda.report_figures                 # 전체
    python -m DATA_ENGINE.eda.report_figures --only 5,10,11  # 번호 선택
    python -m DATA_ENGINE.eda.report_figures --mirror        # + data/CROWD/reports/figures/ 복사(Drive)
"""

from __future__ import annotations

import argparse
import math
import shutil
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from app.CROWD.pipeline.disaggregate import half_hour_shares
from app.CROWD.pipeline.features import SLOT_ORDER
from DATA_ENGINE.eda import figstyle as fs

AI_ROOT = Path(__file__).resolve().parents[2]
PROCESSED = AI_ROOT / "data" / "CROWD" / "processed"
INTERIM = AI_ROOT / "data" / "CROWD" / "interim"
VALIDATION_CACHE = AI_ROOT / "data" / "CROWD" / "interim" / "validation"

PANEL = PROCESSED / "crowd_panel_2024_2025.parquet"
EVENTS = PROCESSED / "crowd_station_events_2024_2025.parquet"
CALIBRATION = PROCESSED / "crowd_congestion_calibration.parquet"
TIMETABLE = INTERIM / "timetable_long.parquet"
COMPARE_RESULTS = VALIDATION_CACHE / "compare_results.parquet"
GRADE_CELLS = VALIDATION_CACHE / "grade_cells.parquet"
SIM_EVAL_BASE = VALIDATION_CACHE / "sim_eval_base.parquet"
SIM_EVAL_GRID = VALIDATION_CACHE / "sim_eval_grid.parquet"
SPLIT_RESULTS = VALIDATION_CACHE / "split_results.parquet"
# Drive 동기화 스크립트는 AI/data/ 만 옮기므로 그림을 공유할 때는 여기로 복사한다(--mirror).
DATA_MIRROR = AI_ROOT / "data" / "CROWD" / "reports" / "figures"

LINE_ORDER = [f"{i}호선" for i in range(1, 9)]
DAY_TYPES = ["평일", "토요일", "일요일", "휴일"]
RUSH_SLOTS = {"07:30", "08:00", "08:30", "18:00", "18:30", "19:00"}
TARGET_LABEL = {"boarding": "승차", "alighting": "하차"}
DAY_TYPE_COLORS = {
    "평일": fs.COLOR_MODEL,
    "토요일": fs.LINE_COLORS["3호선"],
    "일요일": fs.LINE_COLORS["8호선"],
    "휴일": fs.LINE_COLORS["5호선"],
}
GRADE_THRESHOLDS = {
    "국토부 150/170/190": [150, 170, 190],
    "분포 50/100": [50, 100],
    "분포 50/80/100": [50, 80, 100],
}

# 실시간 집계가 있어야 쓸 수 있는 세트(89 RESULTS). 8번 그림에서 색으로 구분한다.
REALTIME_SETS = {
    "neighbors_resid",
    "neighbors_raw",
    "festival_neighbors_resid",
    "festival_neighbors_raw",
    "festival_neighbors_xfer_resid",
    "festival_slotlag_resid",
    "festival_all_derived_resid",
}
SET_LABELS = {
    "events_station_time_festival": "87 권장(이벤트·축제)",
    "festival_neighbors_raw": "+인접역 원본값",
    "festival_neighbors_resid": "+인접역 잔차",
    "festival_neighbors_xfer_resid": "+환승 노드",
    "festival_lag_d7_resid": "+1주 전 시차",
    "festival_selflag_d1d7_resid": "+전날·1주 전 자기 시차",
    "festival_lag_d1d7_resid": "+인접역 시차",
    "festival_slotlag_resid": "+직전 시간대",
    "festival_all_derived_resid": "전부",
}


class Inputs:
    """무거운 입력을 한 번만 읽는 지연 로더."""

    def __init__(self) -> None:
        self._cache: dict[str, pd.DataFrame] = {}

    def _load(self, key: str, path: Path, **kw) -> pd.DataFrame | None:
        if key not in self._cache:
            if not path.exists():
                return None
            self._cache[key] = pd.read_parquet(path, **kw)
        return self._cache[key]

    @property
    def panel(self):
        return self._load(
            "panel",
            PANEL,
            columns=[
                "date",
                "station_no",
                "station_name",
                "line",
                "time_slot",
                "day_type",
                "boarding",
                "alighting",
            ],
        )

    @property
    def events(self):
        return self._load("events", EVENTS)

    @property
    def calibration(self):
        return self._load("calibration", CALIBRATION)

    @property
    def timetable(self):
        return self._load("timetable", TIMETABLE)

    @property
    def compare_results(self):
        return self._load("compare", COMPARE_RESULTS)

    @property
    def grade_cells(self):
        return self._load("grade", GRADE_CELLS)

    @property
    def sim_eval_base(self):
        return self._load("sim_base", SIM_EVAL_BASE)

    @property
    def sim_eval_grid(self):
        return self._load("sim_grid", SIM_EVAL_GRID)

    @property
    def split_results(self):
        return self._load("split", SPLIT_RESULTS)

    def load_by_train(self) -> pd.DataFrame | None:
        files = sorted(PROCESSED.glob("crowd_load_by_train_*.parquet"))
        return pd.read_parquet(files[-1]) if files else None

    def stations(self) -> pd.DataFrame | None:
        """역 목록(station_no, station_name, line) — 노트북에서 역을 고를 때."""
        panel = self.panel
        return None if panel is None else _station_order(panel).drop(columns="line_rank")


# ── 공통 ──
def _station_order(panel: pd.DataFrame) -> pd.DataFrame:
    st = panel[["station_no", "station_name", "line"]].drop_duplicates("station_no")
    st["line_rank"] = st["line"].map({ln: i for i, ln in enumerate(LINE_ORDER)})
    return st.sort_values(["line_rank", "station_no"])


def _name(base: str, *parts, default: bool) -> str:
    """기본 선택이면 base, 아니면 선택을 접미로 붙여 기본 그림을 덮어쓰지 않는다."""
    if default:
        return base
    suffix = "_".join(str(p) for p in parts if p not in (None, ""))
    for ch in r'/\:*?"<>| ':  # 파일명에 못 쓰는 문자·공백은 -로
        suffix = suffix.replace(ch, "-")
    return f"{base}__{suffix}" if suffix else base


def _grid(n: int, cols: int = 4, cell=(4.0, 3.5)):
    """n개 패널을 최대 cols열 격자로. (fig, axes 1차원 배열) — 남는 축은 숨긴다."""
    cols = max(1, min(cols, n))
    rows = math.ceil(n / cols)
    fig, axes = plt.subplots(rows, cols, figsize=(cell[0] * cols, cell[1] * rows), squeeze=False)
    flat = axes.ravel()
    for ax in flat[n:]:
        ax.set_visible(False)
    return fig, flat[:n]


def _lines_label(lines: Sequence[str]) -> str:
    return "1~8호선" if list(lines) == LINE_ORDER else "·".join(lines)


def _station_name(panel: pd.DataFrame, station_no: int, with_line: bool = False) -> str:
    """station_no → 역명. 서울역처럼 호선마다 다른 station_no를 갖는 이름은 with_line으로 구분."""
    hit = panel.loc[panel["station_no"] == station_no, ["station_name", "line"]]
    if not len(hit):
        return str(station_no)
    name, line = hit.iloc[0]
    return f"{name}({line})" if with_line else str(name)


# ── 1 ──
def fig_panel_heatmap(
    inp: Inputs,
    day_types: Sequence[str] = DAY_TYPES,
    lines: Sequence[str] = LINE_ORDER,
    target: str = "boarding",
) -> list:
    """역(호선 순) × 20슬롯 평균 히트맵, 요일유형마다 한 장. `lines`로 호선을 좁힐 수 있다."""
    panel = inp.panel
    if panel is None:
        return []
    default = list(lines) == LINE_ORDER and target == "boarding"
    panel = panel[panel["line"].isin(lines)]
    st = _station_order(panel)
    out = []
    for dt in day_types:
        sub = panel[panel["day_type"] == dt]
        mat = sub.pivot_table(
            index="station_no", columns="time_slot", values=target, aggfunc="mean"
        )
        mat = mat.reindex(index=st["station_no"], columns=SLOT_ORDER)
        height = max(4.0, min(14.0, 0.05 * len(mat) + 1.5))
        fig, ax = plt.subplots(figsize=(11, height))
        im = ax.imshow(
            np.log1p(mat.to_numpy()), aspect="auto", cmap="YlOrRd", interpolation="nearest"
        )
        ax.set_xticks(range(len(SLOT_ORDER)))
        ax.set_xticklabels(SLOT_ORDER, rotation=90)
        bounds = st.groupby("line", sort=False).size().cumsum()
        prev = 0
        for line, b in bounds.items():
            ax.axhline(b - 0.5, color="white", lw=1.2)
            ax.text(
                -0.7,
                (prev + b) / 2,
                line,
                ha="right",
                va="center",
                fontsize=9,
                color=fs.line_color(line),
                fontweight="bold",
            )
            prev = b
        if len(lines) == 1:
            ax.set_yticks(range(len(mat)))
            ax.set_yticklabels(st["station_name"], fontsize=7)
        else:
            ax.set_yticks([])
        ax.set_title(
            f"역 × 시간대 평균 {TARGET_LABEL[target]} 인원 — {dt} "
            f"(log 스케일, {_lines_label(lines)} {len(mat)}역)"
        )
        ax.set_xlabel("시간대(1시간)")
        ax.grid(False)
        cb = fig.colorbar(im, ax=ax, fraction=0.03, pad=0.01)
        cb.set_label(f"log(1+{TARGET_LABEL[target]} 인원)")
        fs.caption(
            fig, f"출처: crowd_panel_2024_2025 (2024-01-01~2025-12-31 {dt} 평균). 색은 로그 스케일."
        )
        out.append(
            fs.save(fig, _name(f"panel_heatmap_station_slot_{dt}", *lines, target, default=default))
        )
    return out


# ── 2 ──
def fig_daily_total_by_line(
    inp: Inputs,
    lines: Sequence[str] = LINE_ORDER,
    target: str = "boarding",
    start: str | None = None,
    end: str | None = None,
    window: int = 7,
) -> list:
    """호선별 일 총량 이동평균. `start/end`('YYYY-MM-DD')로 기간, `window`로 평균 창."""
    panel = inp.panel
    if panel is None:
        return []
    default = list(lines) == LINE_ORDER and target == "boarding" and not (start or end)
    p = panel[panel["line"].isin(lines)]
    if start:
        p = p[p["date"] >= start]
    if end:
        p = p[p["date"] <= end]
    daily = p.groupby(["date", "line"], observed=True)[target].sum().unstack("line")
    daily = daily.reindex(columns=[c for c in lines if c in daily.columns])
    smooth = daily.rolling(window, center=True, min_periods=max(1, window // 2)).mean()
    holidays = p[p["day_type"] == "휴일"]["date"].drop_duplicates()
    fig, ax = plt.subplots()
    for line in smooth.columns:
        ax.plot(smooth.index, smooth[line] / 1e4, color=fs.line_color(line), lw=1.6, label=line)
    for h in holidays:
        ax.axvline(h, color=fs.PALETTE_NEUTRAL[2], lw=0.6, alpha=0.6, zorder=0)
    ax.set_ylabel(f"일 총 {TARGET_LABEL[target]} (만 명, {window}일 이동평균)")
    span = f"{smooth.index.min():%Y-%m}~{smooth.index.max():%Y-%m}" if len(smooth) else ""
    ax.set_title(f"호선별 일 총 {TARGET_LABEL[target]} 추이 {span} — 회색 세로선은 평일 공휴일")
    ax.legend(ncol=4, loc="upper left", frameon=False)
    fs.caption(
        fig, f"출처: crowd_panel_2024_2025. {window}일 중심 이동평균. 9호선 제외(패널 기간 상이)."
    )
    return [
        fs.save(
            fig, _name("panel_daily_total_by_line", *lines, target, start, end, default=default)
        )
    ]


# ── 3 ──
def fig_direction_validation(
    inp: Inputs, lines: Sequence[str] = LINE_ORDER, day_type: str = "평일"
) -> list:
    """재귀식 raw 평균 vs 실측 스냅샷 산점, 호선별 상관. 방향 라벨이 맞는지의 근거."""
    cal = inp.calibration
    if cal is None:
        return []
    default = list(lines) == LINE_ORDER and day_type == "평일"
    c = cal[cal["line"].isin(lines) & (cal["day_type"] == day_type)].dropna(
        subset=["raw_mean", "congestion_pct"]
    )
    fig, axes = _grid(len(lines))
    for ax, line in zip(axes, lines):
        s = c[c["line"] == line]
        for direction, marker in zip(sorted(s["direction"].unique()), ("o", "^")):
            d = s[s["direction"] == direction]
            ax.scatter(
                d["raw_mean"],
                d["congestion_pct"],
                s=6,
                alpha=0.35,
                marker=marker,
                color=fs.line_color(line),
                label=direction,
            )
        r = np.corrcoef(s["raw_mean"], s["congestion_pct"])[0, 1] if len(s) > 2 else np.nan
        ax.set_title(f"{line}  r={r:.2f}", fontsize=12)
        ax.set_xlabel("재귀식 raw 혼잡도 평균(%)", fontsize=9)
        ax.set_ylabel("실측 스냅샷(%)", fontsize=9)
        ax.legend(fontsize=8, frameon=False, markerscale=2)
    fig.suptitle(
        f"방향 분해 검증 — 재귀식(배차 미보정) vs 실측 30분 스냅샷, 역·방향·30분 셀 ({day_type})",
        y=1.01,
    )
    fig.tight_layout()
    fs.caption(
        fig,
        f"출처: crowd_congestion_calibration({day_type}). 양의 상관이 방향 라벨이 맞다는 근거(88: 뒤집었을 때 -0.80).",
    )
    return [fs.save(fig, _name("direction_validation_scatter", *lines, day_type, default=default))]


# ── 4 ──
def fig_calibration_ratio_heatmap(
    inp: Inputs,
    lines: Sequence[str] = LINE_ORDER,
    day_type: str = "평일",
    directions: Sequence[str] = ("하선", "내선"),
) -> list:
    """호선별 역 × 30분 배율 히트맵. `directions`로 상선/외선도 볼 수 있다."""
    cal = inp.calibration
    if cal is None:
        return []
    default = (
        list(lines) == LINE_ORDER and day_type == "평일" and tuple(directions) == ("하선", "내선")
    )
    c = cal[cal["line"].isin(lines) & (cal["day_type"] == day_type)]
    c = c[c["direction"].isin(directions)]
    slots = sorted(c["time_slot"].unique(), key=lambda t: (int(t[:2]) < 4, t))
    fig, axes = _grid(len(lines), cell=(4.0, 4.5))
    im = None
    for ax, line in zip(axes, lines):
        s = c[c["line"] == line]
        mat = s.pivot_table(index="station_no", columns="time_slot", values="ratio").reindex(
            columns=slots
        )
        im = ax.imshow(
            mat.to_numpy(),
            aspect="auto",
            cmap="viridis",
            vmin=0,
            vmax=np.nanpercentile(c["ratio"].dropna(), 95) if c["ratio"].notna().any() else 1,
        )
        ax.set_title(f"{line} ({len(mat)}역)", color=fs.line_color(line), fontsize=12)
        ax.set_xticks(range(0, len(slots), 6))
        ax.set_xticklabels(slots[::6], rotation=90, fontsize=8)
        if len(lines) == 1:
            names = inp.stations()
            lab = (
                mat.index.map(names.set_index("station_no")["station_name"])
                if names is not None
                else mat.index
            )
            ax.set_yticks(range(len(mat)))
            ax.set_yticklabels(lab, fontsize=7)
        else:
            ax.set_yticks([])
        ax.grid(False)
    if im is not None:
        fig.colorbar(
            im, ax=list(axes), fraction=0.015, pad=0.01, label="배율 = 실측30분 ÷ mean(raw 1시간)"
        )
    fig.suptitle(
        f"배율표 — 역 × 30분 ({day_type}, {'/'.join(directions)}). 배차 보정과 30분 모양을 동시에 담는다",
        y=0.98,
    )
    fs.caption(
        fig, "출처: crowd_congestion_calibration. 색 상한은 95분위. 빈 칸은 배율 없음(결측)."
    )
    return [
        fs.save(
            fig, _name("calibration_ratio_heatmap", *lines, day_type, *directions, default=default)
        )
    ]


# ── 5 ──
def fig_half_hour_share_curve(
    inp: Inputs,
    day_types: Sequence[str] = ("평일", "토요일", "일요일"),
    lines: Sequence[str] | None = None,
    stations: Sequence[int] | None = None,
) -> list:
    """시간대별 후반 30분 비중 평균 ± 1σ. `stations`(station_no)로 특정 역만 보면 띠는 역 간 산포가 아니라 방향 간 산포다."""
    cal = inp.calibration
    if cal is None:
        return []
    default = tuple(day_types) == ("평일", "토요일", "일요일") and not lines and not stations
    c = cal[cal["line"] != "9호선"]
    if lines:
        c = c[c["line"].isin(lines)]
    if stations:
        c = c[c["station_no"].isin(stations)]
    sh = half_hour_shares(c)
    late = sh[sh["time_slot_30min"].str.endswith(":30")]
    hours = [h for h in SLOT_ORDER if h not in ("~06",)]
    fig, ax = plt.subplots()
    for dt in day_types:
        g = (
            late[late["day_type"] == dt]
            .groupby("time_slot")["share"]
            .agg(["mean", "std"])
            .reindex(hours)
        )
        x = np.arange(len(hours))
        color = DAY_TYPE_COLORS.get(dt, fs.PALETTE_NEUTRAL[1])
        ax.plot(x, g["mean"] * 100, color=color, lw=2, label=dt)
        ax.fill_between(
            x,
            (g["mean"] - g["std"].fillna(0)) * 100,
            (g["mean"] + g["std"].fillna(0)) * 100,
            color=color,
            alpha=0.15,
        )
    ax.axhline(50, color=fs.PALETTE_NEUTRAL[1], lw=1, ls="--")
    ax.set_xticks(range(len(hours)))
    ax.set_xticklabels(hours, rotation=90)
    ax.set_ylabel("후반 30분(HH:30) 비중 (%)")
    scope = f"{len(stations)}역" if stations else (_lines_label(lines) if lines else "1~8호선 전체")
    ax.set_title(f"1시간 안 전반/후반 비중 — {scope} 평균 ± 1σ")
    ax.legend(frameon=False)
    fs.caption(
        fig,
        "출처: half_hour_shares(crowd_congestion_calibration). 띠는 역 간 표준편차(러시 2.6~3.7%p).",
    )
    return [
        fs.save(
            fig,
            _name(
                "half_hour_share_curve",
                *(lines or []),
                *(stations or []),
                *day_types,
                default=default,
            ),
        )
    ]


# ── 6·7 잔차 ──
def residuals(
    panel: pd.DataFrame, target: str = "boarding", split: str = "2025-01-01"
) -> pd.DataFrame:
    """split 이전 lookup(요일유형×역×시간대 평균)으로 split 이후 잔차. 그림·노트북 공용 경량 계산."""
    train = panel[panel["date"] < split]
    test = panel[panel["date"] >= split].copy()
    table = (
        train.groupby(["day_type", "station_no", "time_slot"], observed=True)[target]
        .mean()
        .rename("pred")
    )
    test = test.merge(table.reset_index(), on=["day_type", "station_no", "time_slot"], how="left")
    test["resid"] = test[target] - test["pred"]
    return test.dropna(subset=["resid"])


def fig_residual_concentration(
    inp: Inputs,
    target: str = "boarding",
    top_n: int = 15,
    lines: Sequence[str] | None = None,
) -> list:
    """잔차 쏠림 — 상위 역·시간대·요일유형. `lines`로 좁히면 그 호선 안에서의 비중."""
    panel = inp.panel
    if panel is None:
        return []
    default = target == "boarding" and top_n == 15 and not lines
    if lines:
        panel = panel[panel["line"].isin(lines)]
    r = residuals(panel, target)
    r["sq"] = r["resid"] ** 2
    total = r["sq"].sum()
    by_st = (
        r.groupby(["station_no", "station_name", "line"], observed=True)["sq"].sum().reset_index()
    )
    by_st["share"] = by_st["sq"] / total * 100
    top = by_st.sort_values("share", ascending=False).head(top_n)[::-1]
    fig, axes = plt.subplots(1, 3, figsize=(16, 6), gridspec_kw={"width_ratios": [1.4, 1, 0.8]})
    axes[0].barh(
        top["station_name"] + " (" + top["line"] + ")",
        top["share"],
        color=[fs.line_color(x) for x in top["line"]],
    )
    axes[0].set_xlabel("전체 제곱오차 비중 (%)")
    axes[0].set_title(f"역별 잔차 쏠림 상위 {top_n} ({TARGET_LABEL[target]}, 2025)")
    by_slot = r.groupby("time_slot", observed=True)["sq"].sum().reindex(SLOT_ORDER) / total * 100
    axes[1].bar(range(len(SLOT_ORDER)), by_slot, color=fs.COLOR_MODEL)
    axes[1].axhline(100 / len(SLOT_ORDER), color=fs.PALETTE_NEUTRAL[1], ls="--", lw=1)
    axes[1].set_xticks(range(len(SLOT_ORDER)))
    axes[1].set_xticklabels(SLOT_ORDER, rotation=90, fontsize=8)
    axes[1].set_title("시간대별 제곱오차 비중 (%)")
    by_dt = r.groupby("day_type", observed=True)["sq"].sum().reindex(DAY_TYPES) / total * 100
    rows = r.groupby("day_type", observed=True).size().reindex(DAY_TYPES) / len(r) * 100
    x = np.arange(len(DAY_TYPES))
    axes[2].bar(x - 0.2, rows, width=0.4, color=fs.COLOR_BASELINE, label="행 비중")
    axes[2].bar(x + 0.2, by_dt, width=0.4, color=fs.COLOR_ACCENT, label="오차 비중")
    axes[2].set_xticks(x)
    axes[2].set_xticklabels(DAY_TYPES)
    axes[2].set_title("요일유형 — 행 비중 vs 오차 비중 (%)")
    axes[2].legend(frameon=False)
    fig.tight_layout()
    fs.caption(
        fig,
        f"잔차 = 2025 실측 - 2024 lookup(요일유형×역×시간대 평균). 범위: {_lines_label(lines) if lines else '1~8호선'}.",
    )
    return [
        fs.save(
            fig, _name("residual_concentration", *(lines or []), target, top_n, default=default)
        )
    ]


def fig_station_residual_timeseries(
    inp: Inputs,
    stations: Sequence[int] = (150, 218),
    target: str = "boarding",
    year: int = 2025,
) -> list:
    """역별 일별 잔차 합 시계열(경기일 표시). `stations`는 station_no 목록, 역 수만큼 행이 늘어난다."""
    panel = inp.panel
    if panel is None:
        return []
    default = tuple(stations) == (150, 218) and target == "boarding" and year == 2025
    r = residuals(panel, target, split=f"{year}-01-01")
    events = inp.events
    fig, axes = plt.subplots(len(stations), 1, figsize=(11, 3.5 * len(stations)), sharex=True)
    axes = np.atleast_1d(axes)
    for ax, no in zip(axes, stations):
        name = _station_name(panel, no, with_line=True)
        s = r[r["station_no"] == no].groupby("date")["resid"].sum()
        ax.plot(s.index, s.values, color=fs.COLOR_MODEL, lw=0.9)
        ax.axhline(0, color=fs.PALETTE_NEUTRAL[1], lw=0.8)
        if events is not None:
            g = events[
                (events["station_no"] == no)
                & (events["game_count"] > 0)
                & (events["date"] >= f"{year}-01-01")
            ]["date"]
            for d in g:
                ax.axvline(d, color=fs.COLOR_ACCENT, lw=0.5, alpha=0.5, zorder=0)
        ax.set_title(f"{name} — {year} 일별 {TARGET_LABEL[target]} 잔차 합 (빨간 세로선: 경기일)")
        ax.set_xlim(pd.Timestamp(f"{year}-01-01"), pd.Timestamp(f"{year + 1}-01-01"))
        ax.set_ylabel("잔차 (명/일)")
    fig.tight_layout()
    fs.caption(
        fig, f"잔차 = 실측 - {year - 1} lookup. 경기일은 crowd_station_events(game_count>0)."
    )
    return [
        fs.save(fig, _name("station_residual_timeseries", *stations, target, year, default=default))
    ]


# ── 8 ──
def fig_feature_set_steps(
    inp: Inputs, model: str = "xgboost", feature_sets: Sequence[str] | None = None
) -> list:
    """세트별 RMSE/MAE 개선율. `model`은 compare_results의 model 컬럼 값(lightgbm/xgboost)."""
    res = inp.compare_results
    if res is None:
        return []
    default = model == "xgboost" and not feature_sets
    res = res[res["model"] == model]
    order = [k for k in SET_LABELS if k in set(res["feature_set"])]
    if feature_sets:
        order = [k for k in order if k in feature_sets]
    fig, axes = plt.subplots(1, 2, figsize=(14, 6), sharey=True)
    for ax, metric, title in zip(
        axes, ("RMSE_개선율_%", "MAE_개선율_%"), ("RMSE 개선율", "MAE 개선율")
    ):
        for j, target in enumerate(("boarding", "alighting")):
            vals = [
                float(res[(res["feature_set"] == k) & (res["target"] == target)][metric].iloc[0])
                for k in order
            ]
            colors = [fs.COLOR_REALTIME if k in REALTIME_SETS else fs.COLOR_MODEL for k in order]
            ax.barh(
                np.arange(len(order)) + (0.2 if j else -0.2),
                vals,
                height=0.4,
                color=colors,
                alpha=1.0 if j == 0 else 0.55,
                label="승차" if j == 0 else "하차",
            )
        ax.set_yticks(range(len(order)))
        ax.set_yticklabels([SET_LABELS[k] for k in order])
        ax.set_title(f"{title} (베이스라인 lookup 대비, {model})")
        ax.set_xlabel("%")
        ax.legend(frameon=False, loc="lower right")
    fig.text(
        0.5,
        -0.02,
        "파랑 = 사전 예측(D-1)에서 쓸 수 있는 세트, 주황 = 실시간 집계가 필요한 세트",
        ha="center",
        fontsize=10,
    )
    fig.tight_layout()
    fs.caption(
        fig, "출처: compare_results.parquet (compare_models --save-results, 2024 학습 / 2025 평가)."
    )
    return [fs.save(fig, _name("feature_set_improvement_steps", model, default=default))]


# ── 9 ──
def fig_grade_threshold_sensitivity(
    inp: Inputs,
    thresholds: dict[str, list[float]] | None = None,
    lines: Sequence[str] | None = None,
) -> list:
    """임계치 후보별 등급 분포 + lookup/모델 일치율. `thresholds={'이름': [50, 100], ...}`로 후보 교체."""
    cells = inp.grade_cells
    if cells is None:
        return []
    default = thresholds is None and not lines
    thresholds = thresholds or GRADE_THRESHOLDS
    if lines:
        cells = cells[cells["line"].isin(lines)]
    n_grade = max(len(v) for v in thresholds.values()) + 1
    palette = [fs.COLOR_BASELINE, fs.COLOR_MODEL, fs.COLOR_ACCENT, fs.COLOR_REALTIME]
    fig, axes = plt.subplots(1, 2, figsize=(14, 5.5))
    width = 0.8 / len(thresholds)
    for i, (name, ths) in enumerate(thresholds.items()):
        ga = np.searchsorted(ths, cells["actual"], side="right")
        dist = np.bincount(ga, minlength=n_grade) / len(ga) * 100
        axes[0].bar(
            np.arange(len(dist)) + i * width,
            dist,
            width=width,
            label=name,
            color=palette[i % len(palette)],
        )
        gl = np.searchsorted(ths, cells["lookup"], side="right")
        gm = np.searchsorted(ths, cells["model"], side="right")
        axes[1].bar(
            i - 0.15,
            (gl == ga).mean() * 100,
            width=0.3,
            color=fs.COLOR_BASELINE,
            label="lookup" if i == 0 else None,
        )
        axes[1].bar(
            i + 0.15,
            (gm == ga).mean() * 100,
            width=0.3,
            color=fs.COLOR_MODEL,
            label="모델" if i == 0 else None,
        )
    axes[0].set_xticks(np.arange(n_grade) + width * (len(thresholds) - 1) / 2)
    axes[0].set_xticklabels([f"{i + 1}등급" for i in range(n_grade)])
    axes[0].set_xlabel("등급(1=가장 여유)")
    axes[0].set_ylabel("실측 셀 비율 (%)")
    axes[0].set_title("임계치 후보별 실측 등급 분포")
    axes[0].legend(frameon=False)
    axes[1].set_xticks(range(len(thresholds)))
    axes[1].set_xticklabels(list(thresholds))
    axes[1].set_ylim(85, 100)
    axes[1].set_ylabel("실측 등급 일치율 (%)")
    axes[1].set_title(f"lookup vs 모델 등급 일치율 ({_lines_label(lines) if lines else '1~8호선'})")
    axes[1].legend(frameon=False)
    fig.tight_layout()
    fs.caption(
        fig,
        f"출처: grade_cells.parquet (grade_sensitivity --save-cells, 2025 평가, {len(cells):,} 셀).",
    )
    return [
        fs.save(
            fig,
            _name(
                "grade_threshold_sensitivity",
                *(lines or []),
                *(thresholds.keys() if not default else []),
                default=default,
            ),
        )
    ]


# ── 10·11 ──
def fig_train_load(
    inp: Inputs,
    station_no: int = 222,
    direction: str = "내선",
    date: str | None = None,
    slots: Sequence[str] = ("07:30", "08:00", "08:30", "09:00"),
) -> list:
    """한 역·방향·날짜의 열차별 혼잡도 추정 막대(배차 주석). 기본은 강남 내선 첫 날 08시대."""
    lbt = inp.load_by_train()
    if lbt is None:
        return []
    default = (
        station_no == 222
        and direction == "내선"
        and date is None
        and tuple(slots) == ("07:30", "08:00", "08:30", "09:00")
    )
    day = pd.Timestamp(date) if date else lbt["date"].min()
    s = lbt[
        (lbt["station_no"] == station_no) & (lbt["direction"] == direction) & (lbt["date"] == day)
    ]
    s = s[s["time_slot_30min"].isin(slots)].sort_values("arrival_time")
    if s.empty:
        return []
    name = (
        _station_name(inp.panel, station_no, with_line=True)
        if inp.panel is not None
        else str(station_no)
    )
    fig, ax = plt.subplots(figsize=(max(11, 0.28 * len(s)), 6))
    colors = [fs.COLOR_ACCENT if h else fs.COLOR_MODEL for h in s["headway_long"]]
    ax.bar(range(len(s)), s["congestion_pct_est"], color=colors)
    ax.set_xticks(range(len(s)))
    ax.set_xticklabels([t[:5] for t in s["arrival_time"]], rotation=90, fontsize=8)
    for i, (h, v) in enumerate(zip(s["headway_min"], s["congestion_pct_est"])):
        ax.text(i, v + 1, f"{h:.0f}′", ha="center", fontsize=7, color=fs.PALETTE_NEUTRAL[0])
    for b in list(slots)[1:]:
        idx = np.where(s["time_slot_30min"].to_numpy() == b)[0]
        if len(idx):
            ax.axvline(idx[0] - 0.5, color=fs.PALETTE_NEUTRAL[2], lw=1)
    ax.set_ylabel("열차별 혼잡도 추정 (%)")
    ax.set_title(
        f"{name} {direction} {slots[0]}~ 열차별 혼잡도 추정 — {day:%Y-%m-%d}, 막대 위 숫자 = 직전 열차 간격(분)"
    )
    fs.caption(
        fig,
        "30분 평균 혼잡도(88 배율 라벨) × 열차 수를 직전 간격 비례로 배분(135). 빨강 = 간격 12분 초과. '열차별 추정'이며 실측 아님.",
    )
    return [
        fs.save(
            fig,
            _name(
                "train_load_gangnam_rush", station_no, direction, date, slots[0], default=default
            ),
        )
    ]


def fig_headway_distribution(
    inp: Inputs,
    lines: Sequence[str] = LINE_ORDER,
    day_type: str = "평일",
    long_headway_min: float = 12.0,
) -> list:
    """호선별 배차 간격 분포(러시/비러시). `long_headway_min`은 빨간 점선(플래그 임계)."""
    tt = inp.timetable
    if tt is None:
        return []
    default = list(lines) == LINE_ORDER and day_type == "평일" and long_headway_min == 12.0
    t = tt[(tt["day_type"] == day_type) & tt["line"].isin(lines)].copy()
    t["m"] = t["pass_time"].str.slice(0, 2).astype(int) * 60 + t["pass_time"].str.slice(
        3, 5
    ).astype(int)
    t["m"] = t["m"].where(t["m"] >= 240, t["m"] + 1440)
    t = t.sort_values(["station_no", "direction", "m"])
    t["headway"] = t.groupby(["station_no", "direction"], observed=True)["m"].diff()
    t["slot"] = ((t["m"] // 30) * 30 % 1440).map(lambda m: f"{m // 60:02d}:{m % 60:02d}")
    t["rush"] = t["slot"].isin(RUSH_SLOTS)
    t = t.dropna(subset=["headway"])
    t = t[t["headway"] <= 30]
    fig, axes = _grid(len(lines))
    bins = np.arange(0.5, 30.5, 1)
    for ax, line in zip(axes, lines):
        s = t[t["line"] == line]
        ax.hist(
            s[s["rush"]]["headway"],
            bins=bins,
            color=fs.line_color(line),
            alpha=0.9,
            density=True,
            label="러시",
        )
        ax.hist(
            s[~s["rush"]]["headway"],
            bins=bins,
            color=fs.PALETTE_NEUTRAL[2],
            alpha=0.6,
            density=True,
            label="비러시",
        )
        ax.axvline(long_headway_min, color=fs.COLOR_ACCENT, lw=1, ls="--")
        med = s[s["rush"]]["headway"].median()
        over = (s["headway"] > long_headway_min).mean() * 100 if len(s) else float("nan")
        ax.set_title(
            f"{line}  러시 중앙값 {med:.0f}분, {long_headway_min:.0f}분 초과 {over:.1f}%",
            fontsize=11,
        )
        ax.set_xlabel("직전 열차 간격 (분)")
        ax.legend(frameon=False, fontsize=8)
    fig.suptitle(
        f"호선별 배차 간격 분포 ({day_type} 시각표) — 빨간 점선 = {long_headway_min:.0f}분(무작위 도착 가정 상한 플래그)",
        y=1.0,
    )
    fig.tight_layout()
    fs.caption(
        fig,
        "출처: timetable_long (서울교통공사 열차운행시각표 2026-09-01판). 러시 = 07:30~08:59, 18:00~19:29.",
    )
    return [
        fs.save(
            fig,
            _name(
                "headway_distribution_by_line", *lines, day_type, long_headway_min, default=default
            ),
        )
    ]


# ── 12 ──
def fig_line9(inp: Inputs) -> list:
    try:
        from DATA_ENGINE.eda import report_crowd
    except Exception:  # noqa: BLE001
        return []
    try:
        report_crowd.generate()
    except Exception as e:  # noqa: BLE001
        print(f"[12] 9호선 그림 재생성 실패 — {type(e).__name__}: {e}")
        return []
    return [
        fs.FIGURES_DIR / "crowd_line9_weekday_heatmap.png",
        fs.FIGURES_DIR / "crowd_line9_station_clusters.png",
    ]


# ── 13·14 시뮬레이션 평가(92) ──
PREDICTOR_LABELS = {
    "slot_flat": "30분 그대로",
    "prop": "간격 비례(135)",
    "mix": "도착 혼합(92)",
    "oracle_tt": "실제 배차 알 때",
}
SCENARIO_LABELS = {"none": "운행 편차 없음", "delay": "러시 20% 지연", "skip": "러시 5% 결행"}


def fig_sim_predictor_comparison(inp: Inputs, unit: str = "train") -> list:
    """시나리오 × 예측기 등급 일치율(50/100)과 MAE. `unit`은 train / bin5."""
    base = inp.sim_eval_base
    if base is None:
        return []
    default = unit == "train"
    b = base[base["unit"] == unit]
    agg = b.groupby(["cfg_scenario", "predictor"], sort=False)[["등급일치_%", "MAE_%p"]].mean()
    scenarios = [s for s in SCENARIO_LABELS if s in set(b["cfg_scenario"])]
    preds = [p for p in PREDICTOR_LABELS if p in set(b["predictor"])]
    colors = {
        "slot_flat": fs.COLOR_BASELINE,
        "prop": fs.LINE_COLORS["4호선"],
        "mix": fs.COLOR_MODEL,
        "oracle_tt": fs.COLOR_ACCENT,
    }
    fig, axes = plt.subplots(1, 2, figsize=(14, 5.5))
    width = 0.8 / len(preds)
    for ax, metric, title in zip(
        axes, ("등급일치_%", "MAE_%p"), ("등급(50/100) 일치율 (%)", "혼잡도 MAE (%p)")
    ):
        for i, p in enumerate(preds):
            vals = [
                agg.loc[(sc, p), metric] if (sc, p) in agg.index else np.nan for sc in scenarios
            ]
            ax.bar(
                np.arange(len(scenarios)) + i * width,
                vals,
                width=width,
                color=colors.get(p, fs.PALETTE_NEUTRAL[1]),
                label=PREDICTOR_LABELS[p],
            )
            for x, v in zip(np.arange(len(scenarios)) + i * width, vals):
                if not np.isnan(v):
                    ax.text(x, v, f"{v:.1f}", ha="center", va="bottom", fontsize=8)
        ax.set_xticks(np.arange(len(scenarios)) + width * (len(preds) - 1) / 2)
        ax.set_xticklabels([SCENARIO_LABELS[s] for s in scenarios])
        ax.set_title(title)
        if metric == "등급일치_%":
            lo = float(np.nanmin(agg[metric])) - 2
            ax.set_ylim(lo, 100)
        ax.legend(frameon=False, fontsize=9)
    unit_label = "열차" if unit == "train" else "5분 빈"
    fig.suptitle(
        f"시뮬레이션 정답 위 예측기 비교 — {unit_label} 단위, 예측기는 계획 시각표와 30분 라벨만 안다",
        y=1.02,
    )
    fig.tight_layout()
    fs.caption(
        fig,
        "출처: sim_eval_base.parquet (validation/CROWD/sim-eval/evaluate.py, 2025-06-02~08, seed 평균). "
        "'실제 배차 알 때'와 '도착 혼합'의 차 = 실시간 배차 정보의 가치.",
    )
    return [fs.save(fig, _name("sim_predictor_comparison", unit, default=default))]


def fig_sim_sensitivity_grid(inp: Inputs, metric: str = "등급일치_%") -> list:
    """생성기 가정 격자(σ_shape × 도착 혼합 h0-h1) × 시나리오 — mix − slot_flat 차이 히트맵."""
    grid = inp.sim_eval_grid
    if grid is None:
        return []
    default = metric == "등급일치_%"
    g = grid[(grid["unit"] == "train") & grid["predictor"].isin(["slot_flat", "mix"])]
    piv = g.pivot_table(
        index=["cfg_scenario", "cfg_sigma_shape"],
        columns=["cfg_mix_h0", "cfg_mix_h1", "predictor"],
        values=metric,
    )
    scenarios = [s for s in SCENARIO_LABELS if s in piv.index.get_level_values(0)]
    mixes = sorted({(h0, h1) for h0, h1, _ in piv.columns})
    fig, axes = _grid(len(scenarios), cols=3, cell=(4.6, 3.8))
    sign = 1.0 if metric == "등급일치_%" else -1.0  # MAE는 낮을수록 좋아 부호를 뒤집는다
    vmax = 0.0
    mats = []
    for sc in scenarios:
        sub = piv.loc[sc]
        mat = np.array(
            [
                [
                    sign * (sub.loc[sig, (h0, h1, "mix")] - sub.loc[sig, (h0, h1, "slot_flat")])
                    for (h0, h1) in mixes
                ]
                for sig in sub.index
            ]
        )
        mats.append((sc, sub.index.tolist(), mat))
        vmax = max(vmax, float(np.nanmax(np.abs(mat))))
    im = None
    for ax, (sc, sigmas, mat) in zip(axes, mats):
        im = ax.imshow(mat, cmap="RdBu", vmin=-vmax, vmax=vmax, aspect="auto")
        ax.set_xticks(range(len(mixes)))
        ax.set_xticklabels([f"{h0:g}-{h1:g}분" for h0, h1 in mixes])
        ax.set_yticks(range(len(sigmas)))
        ax.set_yticklabels([f"σ={s:g}" for s in sigmas])
        for i in range(mat.shape[0]):
            for j in range(mat.shape[1]):
                ax.text(j, i, f"{mat[i, j]:+.1f}", ha="center", va="center", fontsize=9)
        ax.set_title(SCENARIO_LABELS.get(sc, sc), fontsize=12)
        ax.set_xlabel("생성기 도착 혼합 h0-h1")
        ax.grid(False)
    if im is not None:
        fig.colorbar(
            im,
            ax=list(axes),
            fraction=0.02,
            pad=0.02,
            label=f"도착 혼합 − 30분 그대로 ({metric}, 좋아지는 방향이 +)",
        )
    fig.suptitle(
        "생성기 가정 민감도 — 열차 단위. 예측기(도착 혼합 5-15분)는 고정, 정답 생성 가정만 바꾼다",
        y=1.0,
    )
    fs.caption(
        fig, "출처: sim_eval_grid.parquet (evaluate.py 민감도 격자, seed 0). 판정 기준 +3%p."
    )
    return [fs.save(fig, _name("sim_sensitivity_grid", metric, default=default))]


# ── 15 분할 검토(93) ──
RUN_LABELS = {
    "global": "전역(90)",
    "line": "호선별 8모델",
    "line6": "6호선만 분리",
    "cluster": "군집별",
    "cluster_feat": "전역+군집 피처",
    "sameday": "B′ 같은 요일유형 시차",
    "d1sd": "전날+같은 유형+1주",
    "global_no150": "전역(서울역 제외)",
    "line1_no150": "1호선 분리(서울역 제외)",
}


def fig_split_by_line(
    inp: Inputs,
    runs: Sequence[str] = ("global", "line", "line6", "cluster", "sameday"),
    target: str = "boarding",
    metric: str = "RMSE_개선율_%",
) -> list:
    """호선별 lookup 대비 개선율 — 전역 모델과 분할·대안 세트를 나란히. 오른쪽은 전역 대비 차이."""
    res = inp.split_results
    if res is None:
        return []
    default = (
        tuple(runs) == ("global", "line", "line6", "cluster", "sameday") and target == "boarding"
    )
    r = res[(res["axis"] == "line") & (res["target"] == target) & res["run"].isin(runs)]
    piv = r.pivot_table(index="group", columns="run", values=metric).reindex(LINE_ORDER)
    runs = [x for x in runs if x in piv.columns]
    palette = [
        fs.COLOR_BASELINE,
        fs.COLOR_MODEL,
        fs.LINE_COLORS["4호선"],
        fs.LINE_COLORS["5호선"],
        fs.COLOR_ACCENT,
        fs.COLOR_REALTIME,
    ]
    fig, axes = plt.subplots(1, 2, figsize=(15, 5.5), gridspec_kw={"width_ratios": [1.3, 1]})
    width = 0.8 / len(runs)
    x = np.arange(len(piv))
    for i, run in enumerate(runs):
        axes[0].bar(
            x + i * width,
            piv[run],
            width=width,
            color=palette[i % len(palette)],
            label=RUN_LABELS.get(run, run),
        )
    axes[0].set_xticks(x + width * (len(runs) - 1) / 2)
    axes[0].set_xticklabels(piv.index)
    axes[0].set_ylabel(f"{metric} ({TARGET_LABEL[target]}, lookup 대비)")
    axes[0].set_title("호선별 개선율 — 실행별")
    axes[0].legend(frameon=False, fontsize=9)
    if "global" in runs:
        others = [x for x in runs if x != "global"]
        for i, run in enumerate(others):
            d = piv[run] - piv["global"]
            axes[1].plot(
                piv.index,
                d,
                marker="o",
                color=palette[(runs.index(run)) % len(palette)],
                label=RUN_LABELS.get(run, run),
            )
        axes[1].axhline(0, color=fs.PALETTE_NEUTRAL[1], lw=0.8)
        axes[1].axhline(-2, color=fs.COLOR_ACCENT, lw=0.8, ls="--")
        axes[1].set_ylabel("전역 대비 차이 (%p)")
        axes[1].set_title("전역 대비 — 빨간 점선(−2%p) 아래면 그 호선이 악화")
        axes[1].legend(frameon=False, fontsize=9)
    fig.tight_layout()
    fs.caption(
        fig,
        "출처: split_results.parquet (validation/CROWD/split-check/compare_split.py, 2024 학습 / 2025 평가, 같은 파라미터).",
    )
    return [fs.save(fig, _name("split_by_line", *runs, target, default=default))]


FIGURES: dict[int, tuple[str, Callable[[Inputs], list]]] = {
    1: ("panel_heatmap_station_slot", fig_panel_heatmap),
    2: ("panel_daily_total_by_line", fig_daily_total_by_line),
    3: ("direction_validation_scatter", fig_direction_validation),
    4: ("calibration_ratio_heatmap", fig_calibration_ratio_heatmap),
    5: ("half_hour_share_curve", fig_half_hour_share_curve),
    6: ("residual_concentration", fig_residual_concentration),
    7: ("station_residual_timeseries", fig_station_residual_timeseries),
    8: ("feature_set_improvement_steps", fig_feature_set_steps),
    9: ("grade_threshold_sensitivity", fig_grade_threshold_sensitivity),
    10: ("train_load_gangnam_rush", fig_train_load),
    11: ("headway_distribution_by_line", fig_headway_distribution),
    12: ("line9", fig_line9),
    13: ("sim_predictor_comparison", fig_sim_predictor_comparison),
    14: ("sim_sensitivity_grid", fig_sim_sensitivity_grid),
    15: ("split_by_line", fig_split_by_line),
}


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--only", default=None, help="예: 5,10,11")
    ap.add_argument(
        "--mirror",
        action="store_true",
        help="생성한 PNG를 data/CROWD/reports/figures/ 에도 복사(Drive 동기화 대상)",
    )
    args = ap.parse_args(argv)
    wanted = [int(x) for x in args.only.split(",")] if args.only else sorted(FIGURES)

    font = fs.apply()
    print(f"[스타일] 한글 폰트: {font or '없음(라벨 깨질 수 있음)'} → {fs.FIGURES_DIR}")
    inp = Inputs()
    made, skipped = [], []
    for n in wanted:
        name, fn = FIGURES[n]
        paths = fn(inp)
        if paths:
            made.extend(paths)
            print(f"[{n:>2}] {name}: {len(paths)}장")
        else:
            skipped.append((n, name))
            print(f"[{n:>2}] {name}: 입력 없음 — 건너뜀")
    print(f"\n생성 {len(made)}장" + (f", 건너뜀 {len(skipped)}: {skipped}" if skipped else ""))
    if args.mirror and made:
        DATA_MIRROR.mkdir(parents=True, exist_ok=True)
        for p in made:
            shutil.copy2(p, DATA_MIRROR / p.name)
        print(f"[미러] {len(made)}장 → {DATA_MIRROR}")


if __name__ == "__main__":
    main(sys.argv[1:])
