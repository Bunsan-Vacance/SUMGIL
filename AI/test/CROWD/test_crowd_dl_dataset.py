"""app/CROWD/pipeline/dl/dataset.py — 잔차 시퀀스 데이터셋(numpy·pandas만, CI에서 돈다)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.CROWD.pipeline.dl.dataset import (
    DAY_TYPES,
    EVENT_STATIC_COLS,
    N_SLOTS,
    SEQ_CHANNELS,
    STAT_FEATURES,
    SequencePanel,
    fit_event_stats,
    fit_scale,
)
from app.CROWD.pipeline.features import SLOT_ORDER
from app.CROWD.pipeline.masking import truncate_history

STATIONS = [101, 205, 333]
DATES = pd.date_range("2024-03-01", "2024-03-20", freq="D")
MISSING_DAY = pd.Timestamp("2024-03-10")  # 패널에 통째로 없는 날
NO_HOLIDAYS = pd.DataFrame({"date": pd.to_datetime([]), "is_holiday": pd.Series([], dtype=bool)})


def _derived() -> pd.DataFrame:
    rng = np.random.default_rng(0)
    rows = []
    for s_i, s in enumerate(STATIONS):
        scale = 10.0 * (s_i + 1)  # 역마다 잔차 규모가 다르다
        for d in DATES:
            if d == MISSING_DAY:
                continue
            dow = d.dayofweek
            day_type = "평일" if dow < 5 else ("토요일" if dow == 5 else "일요일")
            for k, slot in enumerate(SLOT_ORDER):
                rows.append(
                    {
                        "date": d,
                        "station_no": s,
                        "time_slot": slot,
                        "day_type": day_type,
                        "boarding_resid": rng.normal(0, scale),
                        "alighting_resid": rng.normal(0, scale * 2),
                        "game_count": int(d.day % 7 == 0),
                        "festival_count": 0,
                        "festival_short_count": 0,
                        "festival_long_count": 0,
                        "festival_min_duration_days": np.nan,
                    }
                )
    df = pd.DataFrame(rows)
    # 한 역의 한 슬롯을 lookup 실패(NaN)로 — 그 셀만 마스크 0이어야 한다
    df.loc[
        (df["station_no"] == 205) & (df["date"] == DATES[3]) & (df["time_slot"] == "07-08"),
        "boarding_resid",
    ] = np.nan
    return df


@pytest.fixture(scope="module")
def panel():
    derived = _derived()
    train = derived[derived["date"] <= "2024-03-14"]
    scale = fit_scale(train)
    stats = fit_event_stats(train)
    return derived, scale, SequencePanel.build(derived, scale, stats, holidays=NO_HOLIDAYS)


def test_scale_table_per_station_slot_with_floor():
    derived = _derived()
    scale = fit_scale(derived, min_std=1.0)
    assert len(scale) == len(STATIONS) * N_SLOTS
    assert set(scale.columns) == {"station_no", "time_slot", "boarding_std", "alighting_std"}
    # 규모가 큰 역의 std가 더 크고, 하차(×2)가 승차보다 크다
    by = scale.groupby("station_no")[["boarding_std", "alighting_std"]].mean()
    assert by.loc[333, "boarding_std"] > by.loc[101, "boarding_std"]
    assert (scale["alighting_std"] > scale["boarding_std"]).mean() > 0.9
    assert (scale[["boarding_std", "alighting_std"]] >= 1.0).all().all()


def test_dense_shapes_and_missing_day_mask(panel):
    _, _, sp = panel
    S, D = len(STATIONS), len(DATES)
    assert sp.z.shape == (S, D, N_SLOTS, 2) and sp.mask.shape == (S, D, N_SLOTS)
    assert sp.events.shape == (S, D, len(EVENT_STATIC_COLS)) and sp.std.shape == (S, N_SLOTS, 2)
    d_missing = (MISSING_DAY - DATES[0]).days
    assert sp.mask[:, d_missing].sum() == 0 and np.all(sp.z[:, d_missing] == 0)
    # lookup 실패 셀 하나만 마스크 0
    s205 = int(np.where(sp.station_ids == 205)[0][0])
    slot = SLOT_ORDER.index("07-08")
    assert sp.mask[s205, 3, slot] == 0 and sp.mask[s205, 3].sum() == N_SLOTS - 1
    # 빠진 날의 요일유형은 달력으로 채워졌다(2024-03-10은 일요일)
    assert DAY_TYPES[sp.day_type[d_missing]] == "일요일"


def test_z_is_resid_over_std_and_inverse_recovers(panel):
    derived, scale, sp = panel
    row = derived[
        (derived["station_no"] == 333)
        & (derived["date"] == DATES[5])
        & (derived["time_slot"] == "08-09")
    ]
    s = int(np.where(sp.station_ids == 333)[0][0])
    slot = SLOT_ORDER.index("08-09")
    std = scale[(scale["station_no"] == 333) & (scale["time_slot"] == "08-09")]
    expect_z = float(row["boarding_resid"].iloc[0]) / float(std["boarding_std"].iloc[0])
    assert sp.z[s, 5, slot, 0] == pytest.approx(expect_z, rel=1e-5)
    back = sp.inverse(sp.z[[s], 5], np.array([s]))
    assert back[0, slot, 0] == pytest.approx(float(row["boarding_resid"].iloc[0]), rel=1e-4)


def test_make_batch_window_alignment_and_shapes(panel):
    _, _, sp = panel
    N = 7
    s_idx, d_idx = sp.sample_index("2024-03-12", "2024-03-12")
    assert len(s_idx) == len(STATIONS)
    batch = sp.make_batch(s_idx, d_idx, seq_days=N)
    B = len(s_idx)
    assert batch["x_seq"].shape == (B, N, N_SLOTS, SEQ_CHANNELS)
    assert batch["x_stat"].shape == (B, STAT_FEATURES)
    assert batch["y"].shape == (B, N_SLOTS, 2) and batch["y_mask"].shape == (B, N_SLOTS)
    # 마지막 자리 = D−1(3/11), 인덱스 N−3 = D−3(3/9), 인덱스 N−2 = D−2 = 3/10(빠진 날 → 마스크 0)
    d_target = d_idx[0]
    np.testing.assert_array_equal(batch["x_seq"][0, -1, :, :2], sp.z[s_idx[0], d_target - 1])
    assert batch["x_seq"][0, -1, :, 2].all()
    assert batch["x_seq"][0, -2, :, 2].sum() == 0 and np.all(batch["x_seq"][0, -2, :, :2] == 0)
    # 요일유형 채널은 하루 안에서 동일하고 one-hot 합이 1
    assert np.allclose(batch["x_seq"][..., 3:].sum(-1), 1.0)
    # 대상일 정적: 요일유형 one-hot(3/12 화요일 = 평일) + 이벤트 5
    assert batch["x_stat"][0, DAY_TYPES.index("평일")] == 1.0


def test_window_before_panel_start_is_masked(panel):
    _, _, sp = panel
    s_idx, d_idx = sp.sample_index("2024-03-03", "2024-03-03")  # 앞에 2일밖에 없다
    batch = sp.make_batch(s_idx, d_idx, seq_days=7)
    m = batch["x_seq"][0, :, :, 2]
    assert m[:5].sum() == 0 and m[5:].all()
    assert np.all(batch["x_seq"][0, :5, :, :2] == 0)


def test_truncation_composes_with_batch(panel):
    _, _, sp = panel
    s_idx, d_idx = sp.sample_index("2024-03-15", "2024-03-15")
    batch = sp.make_batch(s_idx, d_idx, seq_days=7)
    x = batch["x_seq"]
    v, m = truncate_history(x[..., :2], x[..., 2], k=np.array([0, 7, 3]), axis=1)
    assert m[1].sum() == 0 and np.all(v[1] == 0)  # 이력 전부 없음
    assert m[2, :3].sum() == 0 and np.array_equal(m[2, 3:], x[2, 3:, :, 2])
    # k=0은 원래 마스크 그대로(창 안의 3/10 결측은 절단과 무관하게 0으로 남는다)
    np.testing.assert_array_equal(m[0], x[0, :, :, 2])
    np.testing.assert_array_equal(v[0], x[0, :, :, :2])


def test_split_index_and_to_frame(panel):
    _, _, sp = panel
    s_idx, d_idx = sp.sample_index("2024-03-01", "2024-03-14")
    assert len(s_idx) == len(STATIONS) * 13  # 14일 중 3/10 빠짐
    pred = np.zeros((2, N_SLOTS, 2), dtype="float32")
    pred[0, 0, 1] = 5.0
    frame = sp.to_frame(s_idx[:2], d_idx[:2], pred)
    assert len(frame) == 2 * N_SLOTS
    assert list(frame.columns) == [
        "station_no",
        "date",
        "time_slot",
        "boarding_resid_pred",
        "alighting_resid_pred",
    ]
    assert frame.iloc[0]["alighting_resid_pred"] == 5.0 and frame.iloc[0]["time_slot"] == "~06"


def test_build_with_fixed_station_order_and_scale_roundtrip(panel, tmp_path):
    derived, scale, sp = panel
    order = [333, 101, 205]
    sp2 = SequencePanel.build(
        derived, scale, fit_event_stats(derived), holidays=NO_HOLIDAYS, station_ids=order
    )
    assert list(sp2.station_ids) == order
    np.testing.assert_array_equal(sp2.z[1], sp.z[list(sp.station_ids).index(101)])
    path = sp2.save_scale(tmp_path)
    saved = pd.read_parquet(path)
    assert len(saved) == 3 * N_SLOTS and saved["station_no"].iloc[0] == 333
