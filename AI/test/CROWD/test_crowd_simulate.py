"""app/CROWD/pipeline/simulate.py — 시뮬레이션 정답 생성기: 재현성·질량·시나리오·모양 편차."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.CROWD.pipeline.simulate import SimConfig, bin5_of, perturb_timetable, simulate


def _timetable(n=12, start_min=8 * 60, headway=4):
    # 08:00부터 4분 간격 12대 — 08:00 슬롯 8대, 08:30 슬롯 4대. 둘 다 러시 슬롯.
    mins = [start_min + headway * i for i in range(n)]
    return pd.DataFrame(
        {
            "station_no": 222,
            "direction": "내선",
            "day_type": "평일",
            "train_id": [f"T{i}" for i in range(n)],
            "arrival_time": [f"{m // 60:02d}:{m % 60:02d}" for m in mins],
        }
    )


def _loads(dates=("2025-06-02", "2025-06-03")):
    rows = []
    for d in dates:
        for slot, load in (("08:00", 7000.0), ("08:30", 5000.0)):
            rows.append(
                {
                    "date": pd.Timestamp(d),
                    "station_no": 222,
                    "line": "2호선",
                    "direction": "내선",
                    "day_type": "평일",
                    "time_slot_30min": slot,
                    "train_capacity": 1600,
                    "onboard_30min_est": load,
                }
            )
    return pd.DataFrame(rows)


def test_deterministic_for_same_seed_and_differs_across_seeds():
    a = simulate(_loads(), _timetable(), SimConfig(), seed=1)
    b = simulate(_loads(), _timetable(), SimConfig(), seed=1)
    c = simulate(_loads(), _timetable(), SimConfig(), seed=2)
    pd.testing.assert_frame_equal(a, b)
    assert not np.allclose(a["onboard_true"], c["onboard_true"])


def test_expected_mode_conserves_slot_mass_exactly():
    out = simulate(_loads(), _timetable(), SimConfig(poisson=False, sigma_shape=0.0), seed=0)
    per_slot = out.groupby(["date", "time_slot_30min"])["onboard_true"].sum()
    assert per_slot[(pd.Timestamp("2025-06-02"), "08:00")] == pytest.approx(7000.0)
    assert per_slot[(pd.Timestamp("2025-06-03"), "08:30")] == pytest.approx(5000.0)
    # 균등 간격·편차 없음 → 첫차(간격 30 기본)만 빼면 슬롯 안 열차 몫이 같다
    s = out[(out["date"] == "2025-06-02") & (out["time_slot_30min"] == "08:30")]
    assert np.allclose(s["share_true"], s["share_true"].iloc[0])


def test_poisson_keeps_mass_within_sampling_noise():
    out = simulate(_loads(), _timetable(), SimConfig(sigma_shape=0.0), seed=3)
    total = out["onboard_true"].sum()
    assert abs(total / 24000.0 - 1) < 0.05  # 24,000명, Poisson 상대 잡음 ≈ 0.6%


def test_shape_deviation_tilts_within_slot_but_keeps_total():
    out = simulate(_loads(), _timetable(), SimConfig(poisson=False, sigma_shape=0.3), seed=5)
    s = out[(out["date"] == "2025-06-02") & (out["time_slot_30min"] == "08:00")]
    assert s["onboard_true"].sum() == pytest.approx(7000.0)
    assert s["shape_mult"].nunique() > 1  # 전반/후반 몫이 달라졌다
    assert (s["shape_mult"] >= 0.2).all()


def test_delay_scenario_moves_trains_and_recomputes_headway():
    rng = np.random.default_rng(0)
    tt = perturb_timetable(_timetable(), SimConfig(scenario="delay", p_delay=1.0), rng)
    assert not tt["delayed"].iloc[0] and tt["delayed"].iloc[1:].all()  # 첫차는 대상 아님
    assert (tt["arr_min_true"].iloc[1:] > tt["arr_min_plan"].iloc[1:]).all()
    assert len(tt) == 12
    # 모든 열차가 같은 간격(4분)의 절반만큼 밀리면 열차 사이 간격은 유지되고, 둘째 열차만 첫차와 6분
    assert tt["headway_true"].iloc[1] == pytest.approx(6.0)
    assert np.allclose(tt["headway_true"].iloc[2:], tt["headway_plan"].iloc[2:])


def test_skip_scenario_drops_trains_and_slot_mass_goes_to_the_rest():
    base = simulate(_loads(), _timetable(), SimConfig(poisson=False, sigma_shape=0.0), seed=0)
    skip = simulate(
        _loads(),
        _timetable(),
        SimConfig(poisson=False, sigma_shape=0.0, scenario="skip", p_skip=0.5),
        seed=0,
    )
    assert len(skip) < len(base)
    assert skip["onboard_true"].sum() == pytest.approx(base["onboard_true"].sum())


def test_invalid_config_raises():
    with pytest.raises(ValueError):
        SimConfig(scenario="storm")
    with pytest.raises(ValueError):
        SimConfig(sigma_shape=-0.1)


def test_bin5_and_tag():
    assert list(bin5_of(pd.Series([8 * 60 + 7, 24 * 60 + 3]))) == ["08:05", "00:00"]
    assert SimConfig().tag() == "none_s0.05_h5-15"
