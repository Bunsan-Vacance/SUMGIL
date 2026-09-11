"""136 — 보고서 그림 세트. 합성 소형 입력으로 각 그림 함수가 파일을 만드는지, 스타일 모듈이 동작하는지.

matplotlib은 requirements-ci에 없을 수 있어 importorskip으로 감싼다.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("matplotlib")

from DATA_ENGINE.eda import figstyle as fs
from DATA_ENGINE.eda import report_figures as rf

SLOTS = ["~06", "06-07", "07-08", "08-09", "09-10"]
SLOTS30 = ["05:30", "06:00", "06:30", "07:00", "07:30", "08:00", "08:30", "09:00", "09:30"]


def _panel() -> pd.DataFrame:
    dates = pd.date_range("2024-01-01", "2025-03-31", freq="D")
    rows = []
    rng = np.random.default_rng(0)
    for st, name, line in (
        (150, "서울역", "1호선"),
        (218, "종합운동장", "2호선"),
        (222, "강남", "2호선"),
    ):
        for d in dates:
            dt = "평일" if d.weekday() < 5 else ("토요일" if d.weekday() == 5 else "일요일")
            for s in SLOTS:
                rows.append(
                    (d, st, name, line, s, dt, rng.integers(10, 500), rng.integers(10, 500))
                )
    return pd.DataFrame(
        rows,
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


def _calibration() -> pd.DataFrame:
    rows = []
    for st, line, dirs in ((150, "1호선", ("상선", "하선")), (222, "2호선", ("내선", "외선"))):
        for dr in dirs:
            for dt in ("평일", "토요일", "일요일"):
                for s in SLOTS30:
                    raw = 100.0 + 10 * SLOTS30.index(s)
                    rows.append((st, line, dr, dt, s, raw * 0.3, raw, 0.3))
    return pd.DataFrame(
        rows,
        columns=[
            "station_no",
            "line",
            "direction",
            "day_type",
            "time_slot",
            "congestion_pct",
            "raw_mean",
            "ratio",
        ],
    )


class _FakeInputs(rf.Inputs):
    def __init__(self, tmp_path):
        super().__init__()
        self._cache["panel"] = _panel()
        self._cache["calibration"] = _calibration()
        self._cache["events"] = pd.DataFrame(
            {"date": pd.to_datetime(["2025-03-01"]), "station_no": [218], "game_count": [1]}
        )
        tt = []
        for dr in ("내선", "외선"):
            for i in range(60):
                m = 6 * 60 + 4 * i
                tt.append((222, "2호선", dr, "평일", f"T{i}", f"{m // 60:02d}:{m % 60:02d}:00"))
        self._cache["timetable"] = pd.DataFrame(
            tt, columns=["station_no", "line", "direction", "day_type", "train_id", "pass_time"]
        )
        self._lbt = pd.DataFrame(
            {
                "date": pd.Timestamp("2025-06-02"),
                "station_no": 222,
                "direction": "내선",
                "time_slot_30min": ["07:30", "08:00", "08:30", "09:00"] * 2,
                "arrival_time": [f"0{7 + i // 2}:{(i % 2) * 30 + 5:02d}:00" for i in range(8)],
                "headway_min": [3.0, 4.0, 3.0, 13.0, 4.0, 4.0, 3.0, 3.0],
                "headway_long": [False, False, False, True, False, False, False, False],
                "congestion_pct_est": np.linspace(30, 60, 8),
            }
        )
        self._cache["compare"] = pd.DataFrame(
            {
                "model": ["xgboost"] * 4,
                "target": ["boarding", "alighting"] * 2,
                "feature_set": ["events_station_time_festival"] * 2
                + ["festival_neighbors_resid"] * 2,
                "RMSE_개선율_%": [5.0, 4.0, 22.0, 20.0],
                "MAE_개선율_%": [6.0, 5.0, 25.0, 23.0],
            }
        )
        rng = np.random.default_rng(1)
        a = rng.uniform(0, 200, 500)
        self._cache["grade"] = pd.DataFrame(
            {"actual": a, "lookup": a + rng.normal(0, 10, 500), "model": a + rng.normal(0, 5, 500)}
        )

    def load_by_train(self):
        return self._lbt


@pytest.fixture(autouse=True)
def _out_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(fs, "FIGURES_DIR", tmp_path)
    monkeypatch.setattr(rf.fs, "FIGURES_DIR", tmp_path)
    fs.apply()
    yield tmp_path


def test_apply_sets_style_and_reports_font():
    font = fs.apply()
    import matplotlib.pyplot as plt

    assert plt.rcParams["axes.unicode_minus"] is False
    assert font is None or font in fs.KOREAN_FONT_CANDIDATES


def test_save_writes_png_and_svg(tmp_path):
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots()
    ax.plot([0, 1], [0, 1])
    png = fs.save(fig, "x", out_dir=tmp_path)
    assert png.exists() and (tmp_path / "x.svg").exists()


@pytest.mark.parametrize("n", [k for k in rf.FIGURES if k != 12])
def test_each_figure_produces_files(tmp_path, n):
    inp = _FakeInputs(tmp_path)
    _, fn = rf.FIGURES[n]
    paths = fn(inp)
    assert paths, f"그림 {n} 미생성"
    for p in paths:
        assert p.exists() and p.stat().st_size > 0


def test_missing_input_is_skipped_not_error(tmp_path, monkeypatch):
    monkeypatch.setattr(rf, "COMPARE_RESULTS", tmp_path / "없음.parquet")
    assert rf.fig_feature_set_steps(rf.Inputs()) == []


# ── 141: 선택 인자·인라인 모드 ──
def test_selection_suffix_keeps_default_name_separate(tmp_path):
    inp = _FakeInputs(tmp_path)
    default = rf.fig_direction_validation(inp)[0]
    narrowed = rf.fig_direction_validation(inp, lines=["2호선"], day_type="토요일")[0]
    assert default.name == "direction_validation_scatter.png"
    assert narrowed.name == "direction_validation_scatter__2호선_토요일.png"
    assert default.exists() and narrowed.exists()


def test_name_sanitizes_path_characters():
    assert "/" not in rf._name("g", "분포 50/100", default=False)
    assert rf._name("g", "x", default=True) == "g"


def test_station_selection_and_line_disambiguation(tmp_path):
    inp = _FakeInputs(tmp_path)
    paths = rf.fig_station_residual_timeseries(inp, stations=[150, 222])
    assert paths[0].name == "station_residual_timeseries__150_222_boarding_2025.png"
    assert rf._station_name(inp.panel, 150, with_line=True) == "서울역(1호선)"


def test_inline_mode_returns_figures_without_files(tmp_path, monkeypatch):
    import matplotlib.pyplot as plt

    monkeypatch.setattr(fs, "INLINE", True)
    inp = _FakeInputs(tmp_path)
    out = rf.fig_half_hour_share_curve(inp, stations=[222])
    assert len(out) == 1 and isinstance(out[0], plt.Figure)
    assert not list(tmp_path.glob("half_hour_share_curve*"))
    plt.close("all")


def test_apply_inline_sets_flag_and_reverts(monkeypatch):
    assert fs.apply(inline=True) is None or fs.INLINE is True
    assert fs.INLINE is True
    fs.apply()
    assert fs.INLINE is False
