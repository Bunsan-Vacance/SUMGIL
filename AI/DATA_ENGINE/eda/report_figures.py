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

8번 입력(`compare_results.parquet`)은 `compare_models.py --save-results`로 만든다. 9번은
`grade_sensitivity.py --save-cells`의 셀 표.

실행:
    cd AI
    python -m DATA_ENGINE.eda.report_figures                 # 전체
    python -m DATA_ENGINE.eda.report_figures --only 5,10,11  # 번호 선택
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
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

LINE_ORDER = [f"{i}호선" for i in range(1, 9)]
DAY_TYPES = ["평일", "토요일", "일요일", "휴일"]
RUSH_SLOTS = {"07:30", "08:00", "08:30", "18:00", "18:30", "19:00"}

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

    def load_by_train(self) -> pd.DataFrame | None:
        files = sorted(PROCESSED.glob("crowd_load_by_train_*.parquet"))
        return pd.read_parquet(files[-1]) if files else None


def _station_order(panel: pd.DataFrame) -> pd.DataFrame:
    st = panel[["station_no", "station_name", "line"]].drop_duplicates("station_no")
    st["line_rank"] = st["line"].map({ln: i for i, ln in enumerate(LINE_ORDER)})
    return st.sort_values(["line_rank", "station_no"])


# ── 1 ──
def fig_panel_heatmap(inp: Inputs) -> list[Path]:
    panel = inp.panel
    if panel is None:
        return []
    st = _station_order(panel)
    out = []
    for dt in DAY_TYPES:
        sub = panel[panel["day_type"] == dt]
        mat = sub.pivot_table(
            index="station_no", columns="time_slot", values="boarding", aggfunc="mean"
        )
        mat = mat.reindex(index=st["station_no"], columns=SLOT_ORDER)
        fig, ax = plt.subplots(figsize=(11, 14))
        im = ax.imshow(
            np.log1p(mat.to_numpy()), aspect="auto", cmap="YlOrRd", interpolation="nearest"
        )
        ax.set_xticks(range(len(SLOT_ORDER)))
        ax.set_xticklabels(SLOT_ORDER, rotation=90)
        # 호선 경계선과 라벨
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
        ax.set_yticks([])
        ax.set_title(f"역 × 시간대 평균 승차 인원 — {dt} (log 스케일, 1~8호선 273역)")
        ax.set_xlabel("시간대(1시간)")
        ax.grid(False)
        cb = fig.colorbar(im, ax=ax, fraction=0.03, pad=0.01)
        cb.set_label("log(1+승차 인원)")
        fs.caption(
            fig, f"출처: crowd_panel_2024_2025 (2024-01-01~2025-12-31 {dt} 평균). 색은 로그 스케일."
        )
        out.append(fs.save(fig, f"panel_heatmap_station_slot_{dt}"))
    return out


# ── 2 ──
def fig_daily_total_by_line(inp: Inputs) -> list[Path]:
    panel = inp.panel
    if panel is None:
        return []
    daily = panel.groupby(["date", "line"], observed=True)["boarding"].sum().unstack("line")
    daily = daily.reindex(columns=[c for c in LINE_ORDER if c in daily.columns])
    smooth = daily.rolling(7, center=True, min_periods=4).mean()
    holidays = panel[panel["day_type"] == "휴일"]["date"].drop_duplicates()
    fig, ax = plt.subplots()
    for line in smooth.columns:
        ax.plot(smooth.index, smooth[line] / 1e4, color=fs.line_color(line), lw=1.6, label=line)
    for h in holidays:
        ax.axvline(h, color=fs.PALETTE_NEUTRAL[2], lw=0.6, alpha=0.6, zorder=0)
    ax.set_ylabel("일 총 승차 (만 명, 7일 이동평균)")
    ax.set_title("호선별 일 총 승차 추이 2024~2025 — 회색 세로선은 평일 공휴일")
    ax.legend(ncol=4, loc="upper left", frameon=False)
    fs.caption(fig, "출처: crowd_panel_2024_2025. 7일 중심 이동평균. 9호선 제외(패널 기간 상이).")
    return [fs.save(fig, "panel_daily_total_by_line")]


# ── 3 ──
def fig_direction_validation(inp: Inputs) -> list[Path]:
    cal = inp.calibration
    if cal is None:
        return []
    c = cal[(cal["line"] != "9호선") & (cal["day_type"] == "평일")].dropna(
        subset=["raw_mean", "congestion_pct"]
    )
    fig, axes = plt.subplots(2, 4, figsize=(14, 7), sharex=False, sharey=False)
    for ax, line in zip(axes.ravel(), LINE_ORDER):
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
        "방향 분해 검증 — 재귀식(배차 미보정) vs 실측 30분 스냅샷, 역·방향·30분 셀", y=1.01
    )
    fig.tight_layout()
    fs.caption(
        fig,
        "출처: crowd_congestion_calibration(평일). 양의 상관이 방향 라벨이 맞다는 근거(88: 뒤집었을 때 -0.80).",
    )
    return [fs.save(fig, "direction_validation_scatter")]


# ── 4 ──
def fig_calibration_ratio_heatmap(inp: Inputs) -> list[Path]:
    cal = inp.calibration
    if cal is None:
        return []
    c = cal[(cal["line"] != "9호선") & (cal["day_type"] == "평일")]
    c = c[c["direction"].isin(["하선", "내선"])]
    slots = sorted(c["time_slot"].unique(), key=lambda t: (int(t[:2]) < 4, t))
    fig, axes = plt.subplots(2, 4, figsize=(16, 9))
    for ax, line in zip(axes.ravel(), LINE_ORDER):
        s = c[c["line"] == line]
        mat = s.pivot_table(index="station_no", columns="time_slot", values="ratio").reindex(
            columns=slots
        )
        im = ax.imshow(
            mat.to_numpy(),
            aspect="auto",
            cmap="viridis",
            vmin=0,
            vmax=np.nanpercentile(c["ratio"], 95),
        )
        ax.set_title(f"{line} ({len(mat)}역)", color=fs.line_color(line), fontsize=12)
        ax.set_xticks(range(0, len(slots), 6))
        ax.set_xticklabels(slots[::6], rotation=90, fontsize=8)
        ax.set_yticks([])
        ax.grid(False)
    fig.colorbar(
        im,
        ax=axes.ravel().tolist(),
        fraction=0.015,
        pad=0.01,
        label="배율 = 실측30분 ÷ mean(raw 1시간)",
    )
    fig.suptitle(
        "배율표 — 역 × 30분 (평일, 하선/내선). 배차 보정과 30분 모양을 동시에 담는다", y=0.98
    )
    fs.caption(
        fig, "출처: crowd_congestion_calibration. 색 상한은 95분위. 빈 칸은 배율 없음(결측)."
    )
    return [fs.save(fig, "calibration_ratio_heatmap")]


# ── 5 ──
def fig_half_hour_share_curve(inp: Inputs) -> list[Path]:
    cal = inp.calibration
    if cal is None:
        return []
    sh = half_hour_shares(cal[cal["line"] != "9호선"])
    late = sh[sh["time_slot_30min"].str.endswith(":30")]
    hours = [h for h in SLOT_ORDER if h not in ("~06",)]
    fig, ax = plt.subplots()
    colors = {
        "평일": fs.COLOR_MODEL,
        "토요일": fs.LINE_COLORS["3호선"],
        "일요일": fs.LINE_COLORS["8호선"],
    }
    for dt, color in colors.items():
        g = (
            late[late["day_type"] == dt]
            .groupby("time_slot")["share"]
            .agg(["mean", "std"])
            .reindex(hours)
        )
        x = np.arange(len(hours))
        ax.plot(x, g["mean"] * 100, color=color, lw=2, label=dt)
        ax.fill_between(
            x, (g["mean"] - g["std"]) * 100, (g["mean"] + g["std"]) * 100, color=color, alpha=0.15
        )
    ax.axhline(50, color=fs.PALETTE_NEUTRAL[1], lw=1, ls="--")
    ax.set_xticks(range(len(hours)))
    ax.set_xticklabels(hours, rotation=90)
    ax.set_ylabel("후반 30분(HH:30) 비중 (%)")
    ax.set_title("1시간 안 전반/후반 비중 — 역 평균 ± 1σ. 7시는 후반, 8·19시는 전반이 무겁다")
    ax.legend(frameon=False)
    fs.caption(
        fig,
        "출처: half_hour_shares(crowd_congestion_calibration). 띠는 역 간 표준편차(러시 2.6~3.7%p).",
    )
    return [fs.save(fig, "half_hour_share_curve")]


# ── 6·7 잔차 ──
def _residuals(panel: pd.DataFrame) -> pd.DataFrame:
    """2024 lookup으로 2025 잔차(승차). 그림용 경량 재계산."""
    train = panel[panel["date"] < "2025-01-01"]
    test = panel[panel["date"] >= "2025-01-01"].copy()
    table = (
        train.groupby(["day_type", "station_no", "time_slot"], observed=True)["boarding"]
        .mean()
        .rename("pred")
    )
    test = test.merge(table.reset_index(), on=["day_type", "station_no", "time_slot"], how="left")
    test["resid"] = test["boarding"] - test["pred"]
    return test.dropna(subset=["resid"])


def fig_residual_concentration(inp: Inputs) -> list[Path]:
    panel = inp.panel
    if panel is None:
        return []
    r = _residuals(panel)
    r["sq"] = r["resid"] ** 2
    total = r["sq"].sum()
    by_st = (
        r.groupby(["station_no", "station_name", "line"], observed=True)["sq"].sum().reset_index()
    )
    by_st["share"] = by_st["sq"] / total * 100
    top = by_st.sort_values("share", ascending=False).head(15)[::-1]
    fig, axes = plt.subplots(1, 3, figsize=(16, 6), gridspec_kw={"width_ratios": [1.4, 1, 0.8]})
    axes[0].barh(
        top["station_name"] + " (" + top["line"] + ")",
        top["share"],
        color=[fs.line_color(x) for x in top["line"]],
    )
    axes[0].set_xlabel("전체 제곱오차 비중 (%)")
    axes[0].set_title("역별 잔차 쏠림 상위 15 (승차, 2025)")
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
        "잔차 = 2025 실측 - 2024 lookup(요일유형×역×시간대 평균). 서울역 한 곳이 오차의 약 14%.",
    )
    return [fs.save(fig, "residual_concentration")]


def fig_station_residual_timeseries(inp: Inputs) -> list[Path]:
    panel = inp.panel
    if panel is None:
        return []
    r = _residuals(panel)
    events = inp.events
    fig, axes = plt.subplots(2, 1, figsize=(11, 7), sharex=True)
    for ax, (no, name) in zip(axes, ((150, "서울역"), (218, "종합운동장"))):
        s = r[r["station_no"] == no].groupby("date")["resid"].sum()
        ax.plot(s.index, s.values, color=fs.COLOR_MODEL, lw=0.9)
        ax.axhline(0, color=fs.PALETTE_NEUTRAL[1], lw=0.8)
        if events is not None:
            g = events[
                (events["station_no"] == no)
                & (events["game_count"] > 0)
                & (events["date"] >= "2025-01-01")
            ]["date"]
            for d in g:
                ax.axvline(d, color=fs.COLOR_ACCENT, lw=0.5, alpha=0.5, zorder=0)
        ax.set_title(f"{name} — 2025 일별 승차 잔차 합 (빨간 세로선: 경기일)")
        ax.set_xlim(pd.Timestamp("2025-01-01"), pd.Timestamp("2026-01-01"))
        ax.set_ylabel("잔차 (명/일)")
    fig.tight_layout()
    fs.caption(
        fig,
        "잔차 = 실측 - 2024 lookup. 종합운동장은 경기일 스파이크, 서울역은 이벤트로 설명되지 않는 추세.",
    )
    return [fs.save(fig, "station_residual_timeseries")]


# ── 8 ──
def fig_feature_set_steps(inp: Inputs) -> list[Path]:
    res = inp.compare_results
    if res is None:
        return []
    res = res[res["model"] == "xgboost"]
    order = [k for k in SET_LABELS if k in set(res["feature_set"])]
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
        ax.set_title(f"{title} (베이스라인 lookup 대비, XGBoost)")
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
    return [fs.save(fig, "feature_set_improvement_steps")]


# ── 9 ──
def fig_grade_threshold_sensitivity(inp: Inputs) -> list[Path]:
    cells = inp.grade_cells
    if cells is None:
        return []
    thresholds = {
        "국토부 150/170/190": [150, 170, 190],
        "분포 50/100": [50, 100],
        "분포 50/80/100": [50, 80, 100],
    }
    fig, axes = plt.subplots(1, 2, figsize=(14, 5.5))
    width = 0.25
    for i, (name, ths) in enumerate(thresholds.items()):
        ga = np.searchsorted(ths, cells["actual"], side="right")
        dist = np.bincount(ga, minlength=len(ths) + 1) / len(ga) * 100
        axes[0].bar(
            np.arange(len(dist)) + i * width,
            dist,
            width=width,
            label=name,
            color=[fs.COLOR_BASELINE, fs.COLOR_MODEL, fs.COLOR_ACCENT][i],
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
    axes[0].set_xticks(np.arange(4) + width)
    axes[0].set_xticklabels([f"{i + 1}등급" for i in range(4)])
    axes[0].set_xlabel("등급(1=가장 여유)")
    axes[0].set_ylabel("실측 셀 비율 (%)")
    axes[0].set_title("임계치 후보별 실측 등급 분포 — 국토부 기준은 99.6%가 한 등급")
    axes[0].legend(frameon=False)
    axes[1].set_xticks(range(3))
    axes[1].set_xticklabels(list(thresholds))
    axes[1].set_ylim(85, 100)
    axes[1].set_ylabel("실측 등급 일치율 (%)")
    axes[1].set_title("lookup vs 모델 등급 일치율")
    axes[1].legend(frameon=False)
    fig.tight_layout()
    fs.caption(
        fig, "출처: grade_cells.parquet (grade_sensitivity --save-cells, 2025 평가, 764.6만 셀)."
    )
    return [fs.save(fig, "grade_threshold_sensitivity")]


# ── 10·11 ──
def fig_train_load_gangnam_rush(inp: Inputs) -> list[Path]:
    lbt = inp.load_by_train()
    if lbt is None:
        return []
    day = lbt["date"].min()
    s = lbt[(lbt["station_no"] == 222) & (lbt["direction"] == "내선") & (lbt["date"] == day)]
    s = s[s["time_slot_30min"].isin(["07:30", "08:00", "08:30", "09:00"])].sort_values(
        "arrival_time"
    )
    if s.empty:
        return []
    fig, ax = plt.subplots()
    colors = [fs.COLOR_ACCENT if h else fs.COLOR_MODEL for h in s["headway_long"]]
    ax.bar(range(len(s)), s["congestion_pct_est"], color=colors)
    ax.set_xticks(range(len(s)))
    ax.set_xticklabels([t[:5] for t in s["arrival_time"]], rotation=90, fontsize=8)
    for i, (h, v) in enumerate(zip(s["headway_min"], s["congestion_pct_est"])):
        ax.text(i, v + 1, f"{h:.0f}′", ha="center", fontsize=7, color=fs.PALETTE_NEUTRAL[0])
    for b in ("08:00", "08:30", "09:00"):
        idx = np.where(s["time_slot_30min"].to_numpy() == b)[0]
        if len(idx):
            ax.axvline(idx[0] - 0.5, color=fs.PALETTE_NEUTRAL[2], lw=1)
    ax.set_ylabel("열차별 혼잡도 추정 (%)")
    ax.set_title(
        f"강남 내선 07:30~09:29 열차별 혼잡도 추정 — {pd.Timestamp(day):%Y-%m-%d}, 막대 위 숫자 = 직전 열차 간격(분)"
    )
    fs.caption(
        fig,
        "30분 평균 혼잡도(88 배율 라벨) × 열차 수를 직전 간격 비례로 배분(135). 빨강 = 간격 12분 초과. '열차별 추정'이며 실측 아님.",
    )
    return [fs.save(fig, "train_load_gangnam_rush")]


def fig_headway_distribution(inp: Inputs) -> list[Path]:
    tt = inp.timetable
    if tt is None:
        return []
    t = tt[tt["day_type"] == "평일"].copy()
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
    fig, axes = plt.subplots(2, 4, figsize=(16, 7), sharex=True, sharey=True)
    bins = np.arange(0.5, 30.5, 1)
    for ax, line in zip(axes.ravel(), LINE_ORDER):
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
        ax.axvline(12, color=fs.COLOR_ACCENT, lw=1, ls="--")
        med = s[s["rush"]]["headway"].median()
        ax.set_title(
            f"{line}  러시 중앙값 {med:.0f}분, 12분 초과 {(s['headway'] > 12).mean() * 100:.1f}%",
            fontsize=11,
        )
        ax.legend(frameon=False, fontsize=8)
    for ax in axes[1]:
        ax.set_xlabel("직전 열차 간격 (분)")
    fig.suptitle(
        "호선별 배차 간격 분포 (평일 시각표) — 빨간 점선 = 12분(무작위 도착 가정 상한 플래그)",
        y=1.0,
    )
    fig.tight_layout()
    fs.caption(
        fig,
        "출처: timetable_long (서울교통공사 열차운행시각표 2026-09-01판). 러시 = 07:30~08:59, 18:00~19:29.",
    )
    return [fs.save(fig, "headway_distribution_by_line")]


# ── 12 ──
def fig_line9(inp: Inputs) -> list[Path]:
    try:
        from DATA_ENGINE.eda import report_crowd
    except Exception:  # noqa: BLE001
        return []
    try:
        report_crowd.main()
    except Exception as e:  # noqa: BLE001
        print(f"[12] 9호선 그림 재생성 실패 — {type(e).__name__}: {e}")
        return []
    return [
        fs.FIGURES_DIR / "crowd_line9_weekday_heatmap.png",
        fs.FIGURES_DIR / "crowd_line9_station_clusters.png",
    ]


FIGURES: dict[int, tuple[str, Callable[[Inputs], list[Path]]]] = {
    1: ("panel_heatmap_station_slot", fig_panel_heatmap),
    2: ("panel_daily_total_by_line", fig_daily_total_by_line),
    3: ("direction_validation_scatter", fig_direction_validation),
    4: ("calibration_ratio_heatmap", fig_calibration_ratio_heatmap),
    5: ("half_hour_share_curve", fig_half_hour_share_curve),
    6: ("residual_concentration", fig_residual_concentration),
    7: ("station_residual_timeseries", fig_station_residual_timeseries),
    8: ("feature_set_improvement_steps", fig_feature_set_steps),
    9: ("grade_threshold_sensitivity", fig_grade_threshold_sensitivity),
    10: ("train_load_gangnam_rush", fig_train_load_gangnam_rush),
    11: ("headway_distribution_by_line", fig_headway_distribution),
    12: ("line9", fig_line9),
}


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--only", default=None, help="예: 5,10,11")
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


if __name__ == "__main__":
    main(sys.argv[1:])
