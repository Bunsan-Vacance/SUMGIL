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
    SPLITS,
    STAT_FEATURES,
    SequencePanel,
    encode_events,
    fit_event_stats,
    fit_scale,
    load_derived_slim,
    observed_channels,
    parse_splits,
    scenario_seq,
    seq_channels_for,
    splits_with_train_start,
    stat_features_for,
    truncate_seq,
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


# ── 198: 입력 설계 변형(채널 구성 옵션) ──

NEIGHBOR_MAP = pd.DataFrame(
    {
        "station_no": [101, 205, 205, 333],
        "line": ["1호선"] * 4,
        "segment": ["본선"] * 4,
        "side": ["next", "prev", "next", "prev"],
        "neighbor_station_no": [205, 101, 333, 205],
    }
)  # 101 ─ 205 ─ 333 직선. 101은 prev 없음, 333은 next 없음, 아무도 xfer가 없다


def _derived_with_neighbors() -> pd.DataFrame:
    """`nb_{side}_{target}_resid`를 파생 캐시와 같은 규칙(같은 날·같은 슬롯 이웃 잔차)으로 붙인다."""
    from app.CROWD.pipeline.adjacency import attach_neighbor_features

    df = _derived()
    return attach_neighbor_features(df, NEIGHBOR_MAP, ["boarding_resid", "alighting_resid"])


def test_seq_channels_and_stat_features_per_variant():
    assert seq_channels_for("base") == 7 == SEQ_CHANNELS
    assert seq_channels_for("events_hist") == 12
    assert seq_channels_for("neighbor") == 16
    assert stat_features_for(True) == STAT_FEATURES == 9
    assert stat_features_for(False) == 4
    with pytest.raises(ValueError):
        seq_channels_for("weather")


def test_neighbor_variant_channel_count_and_z_uses_neighbor_std():
    derived = _derived_with_neighbors()
    train = derived[derived["date"] <= "2024-03-14"]
    scale = fit_scale(train)
    sp = SequencePanel.build(
        derived,
        scale,
        fit_event_stats(train),
        holidays=NO_HOLIDAYS,
        seq_features="neighbor",
        neighbor_map=NEIGHBOR_MAP,
    )
    s_idx, d_idx = sp.sample_index("2024-03-15", "2024-03-15")
    batch = sp.make_batch(s_idx, d_idx, seq_days=7)
    assert batch["x_seq"].shape == (len(STATIONS), 7, N_SLOTS, 16)
    assert batch["x_stat"].shape == (len(STATIONS), STAT_FEATURES)

    # 205의 prev 이웃은 101 하나 → 101의 잔차를 **101의 std**로 나눈 값이어야 한다
    s205 = int(np.where(sp.station_ids == 205)[0][0])
    s101 = int(np.where(sp.station_ids == 101)[0][0])
    day = pd.Timestamp("2024-03-14")
    d = (day - DATES[0]).days
    slot = SLOT_ORDER.index("09-10")
    raw101 = float(
        derived.loc[
            (derived["station_no"] == 101)
            & (derived["date"] == day)
            & (derived["time_slot"] == "09-10"),
            "boarding_resid",
        ].iloc[0]
    )
    std101 = float(
        scale.loc[
            (scale["station_no"] == 101) & (scale["time_slot"] == "09-10"), "boarding_std"
        ].iloc[0]
    )
    assert sp.nb_z[s205, d, slot, 0] == pytest.approx(raw101 / std101, rel=1e-5)
    # 자기 std로 나눈 값과는 다르다(205의 잔차 규모가 101의 2배)
    assert sp.nb_z[s205, d, slot, 0] != pytest.approx(raw101 / float(sp.std[s205, slot, 0]))
    # 같은 자리 z는 여전히 자기 잔차 / 자기 std
    assert sp.z[s101, d, slot, 0] == pytest.approx(raw101 / std101, rel=1e-5)


def test_neighbor_mask_zero_when_no_neighbor_on_side():
    derived = _derived_with_neighbors()
    train = derived[derived["date"] <= "2024-03-14"]
    sp = SequencePanel.build(
        derived,
        fit_scale(train),
        fit_event_stats(train),
        holidays=NO_HOLIDAYS,
        seq_features="neighbor",
        neighbor_map=NEIGHBOR_MAP,
    )
    d = (pd.Timestamp("2024-03-14") - DATES[0]).days
    s101 = int(np.where(sp.station_ids == 101)[0][0])
    s333 = int(np.where(sp.station_ids == 333)[0][0])
    s205 = int(np.where(sp.station_ids == 205)[0][0])
    # side 순서 prev·next·xfer — 101은 prev 없음, 333은 next 없음, 전원 xfer 없음
    assert sp.nb_mask[s101, d, :, 0].sum() == 0 and sp.nb_mask[s101, d, :, 1].all()
    assert sp.nb_mask[s333, d, :, 1].sum() == 0 and sp.nb_mask[s333, d, :, 0].all()
    assert sp.nb_mask[:, :, :, 2].sum() == 0
    assert np.all(sp.nb_z[s101, d, :, 0:2] == 0)  # 마스크 0 자리의 값은 0
    assert sp.nb_mask[s205, d, :, :2].all()  # 가운데 역은 prev·next 둘 다 있다


def test_events_hist_variant_broadcasts_event_channels_per_history_day():
    derived = _derived()
    train = derived[derived["date"] <= "2024-03-14"]
    sp = SequencePanel.build(
        derived,
        fit_scale(train),
        fit_event_stats(train),
        holidays=NO_HOLIDAYS,
        seq_features="events_hist",
    )
    s_idx, d_idx = sp.sample_index("2024-03-15", "2024-03-15")
    batch = sp.make_batch(s_idx, d_idx, seq_days=7)
    assert batch["x_seq"].shape == (len(STATIONS), 7, N_SLOTS, 12)
    # 이벤트 채널은 하루 안에서 슬롯과 무관하게 같고, 그 날의 정적 이벤트 값과 일치한다
    ev = batch["x_seq"][0, :, :, 7:]
    assert np.allclose(ev, ev[:, :1, :])
    hist_days = d_idx[0] - np.arange(7, 0, -1)
    np.testing.assert_allclose(ev[:, 0, :], sp.events[s_idx[0], hist_days])


def test_static_events_switch_drops_stat_width_to_four():
    derived = _derived()
    train = derived[derived["date"] <= "2024-03-14"]
    sp = SequencePanel.build(
        derived,
        fit_scale(train),
        fit_event_stats(train),
        holidays=NO_HOLIDAYS,
        use_static_events=False,
    )
    s_idx, d_idx = sp.sample_index("2024-03-15", "2024-03-15")
    batch = sp.make_batch(s_idx, d_idx, seq_days=7)
    assert batch["x_stat"].shape == (len(STATIONS), 4)
    assert np.allclose(batch["x_stat"].sum(-1), 1.0)  # 요일유형 one-hot만 남는다
    assert batch["x_seq"].shape[-1] == SEQ_CHANNELS  # 시퀀스 채널은 그대로


def test_truncate_seq_clears_neighbor_channels_but_keeps_calendar():
    derived = _derived_with_neighbors()
    train = derived[derived["date"] <= "2024-03-14"]
    sp = SequencePanel.build(
        derived,
        fit_scale(train),
        fit_event_stats(train),
        holidays=NO_HOLIDAYS,
        seq_features="neighbor",
        neighbor_map=NEIGHBOR_MAP,
    )
    s_idx, d_idx = sp.sample_index("2024-03-15", "2024-03-15")
    x = sp.make_batch(s_idx, d_idx, seq_days=7)["x_seq"]
    out = truncate_seq(x, np.array([0, 7, 3]), "neighbor")
    assert np.all(out[1, :, :, observed_channels("neighbor")] == 0)  # 관측 채널 전부 0
    assert np.allclose(out[1, :, :, 3:7], x[1, :, :, 3:7])  # 요일유형은 남는다
    assert np.all(out[2, :3, :, 7:16] == 0) and np.allclose(out[2, 3:], x[2, 3:])
    np.testing.assert_array_equal(out[0], x[0])  # k=0은 그대로


# ── 198 후속: 이벤트 인코딩(log1p_max) ──


def _derived_with_events() -> pd.DataFrame:
    """희소 이벤트(대부분 0, 하루만 큰 값)를 담은 파생 프레임 — z 폭발이 재현되는 모양."""
    df = _derived()
    big = df["date"] == pd.Timestamp("2024-03-05")
    df.loc[big, "festival_count"] = 4
    df.loc[big, "festival_min_duration_days"] = 9.0
    # 평가 구간(학습 최대를 넘는 날) — 학습은 3/14까지다
    huge = df["date"] == pd.Timestamp("2024-03-18")
    df.loc[huge, "festival_count"] = 30
    df.loc[huge, "festival_min_duration_days"] = 60.0
    return df


def test_event_stats_record_log1p_max_and_encoding():
    derived = _derived_with_events()
    train = derived[derived["date"] <= "2024-03-14"]
    stats = fit_event_stats(train, encoding="log1p_max")
    assert set(stats.columns) == {"feature", "mean", "std", "log1p_max", "encoding"}
    assert (stats["encoding"] == "log1p_max").all()
    row = stats.set_index("feature").loc["festival_count"]
    assert float(row["log1p_max"]) == pytest.approx(np.log1p(4.0))
    # 학습 구간에 한 번도 없던 열은 나눗셈을 1.0으로 막는다(0 나눗셈 금지)
    assert float(stats.set_index("feature").loc["festival_long_count", "log1p_max"]) == 1.0
    with pytest.raises(ValueError):
        fit_event_stats(train, encoding="minmax")


def test_log1p_max_encoding_bounds_train_range_and_compresses_unseen_peaks():
    derived = _derived_with_events()
    train = derived[derived["date"] <= "2024-03-14"]
    stats = fit_event_stats(train, encoding="log1p_max")
    cols = list(EVENT_STATIC_COLS)
    raw_train = train.drop_duplicates(["date", "station_no"])[cols].fillna(0.0).to_numpy()
    enc = encode_events(raw_train, stats, "log1p_max")
    assert enc.min() >= 0.0 and enc.max() <= 1.0 + 1e-6  # 학습 구간은 0~1

    # 학습 최대를 훨씬 넘는 값도 로그로 눌린다 — 같은 값의 z-점수와 비교
    raw_eval = np.zeros((1, len(cols)), dtype="float32")
    raw_eval[0, cols.index("festival_count")] = 30.0
    raw_eval[0, cols.index("festival_min_duration_days")] = 60.0
    fixed = encode_events(raw_eval, stats, "log1p_max")
    z = encode_events(raw_eval, stats, "zscore")
    assert fixed.max() < 3.0 < z.max()  # z는 희소열 std가 작아 크게 튄다
    with pytest.raises(ValueError):  # log1p_max 열이 없는 옛 스케일 표로는 복원 불가
        encode_events(raw_eval, stats.drop(columns=["log1p_max"]), "log1p_max")


def test_panel_static_events_follow_event_encoding():
    derived = _derived_with_events()
    train = derived[derived["date"] <= "2024-03-14"]
    scale = fit_scale(train)
    kw = {"holidays": NO_HOLIDAYS, "use_static_events": True}
    sp_fixed = SequencePanel.build(
        derived,
        scale,
        fit_event_stats(train, encoding="log1p_max"),
        event_encoding="log1p_max",
        **kw,
    )
    sp_z = SequencePanel.build(derived, scale, fit_event_stats(train), **kw)
    assert sp_fixed.event_encoding == "log1p_max" and sp_z.event_encoding == "zscore"

    s_idx, d_idx = sp_fixed.sample_index("2024-03-05", "2024-03-05")
    ev_fixed = sp_fixed.make_batch(s_idx, d_idx, seq_days=7)["x_stat"][:, len(DAY_TYPES) :]
    ev_z = sp_z.make_batch(s_idx, d_idx, seq_days=7)["x_stat"][:, len(DAY_TYPES) :]
    j = EVENT_STATIC_COLS.index("festival_count")
    assert ev_fixed[0, j] == pytest.approx(1.0, rel=1e-5)  # 그 날이 학습 최대 = 1.0
    assert np.all((ev_fixed >= 0.0) & (ev_fixed <= 1.0 + 1e-6))
    assert ev_z[0, j] > 3.0  # 같은 자리의 z-점수는 희소열이라 크게 튄다
    with pytest.raises(ValueError):
        SequencePanel.build(derived, scale, fit_event_stats(train), event_encoding="minmax", **kw)


def test_scenario_seq_keeps_only_named_lag_across_all_observed_channels():
    derived = _derived_with_neighbors()
    train = derived[derived["date"] <= "2024-03-14"]
    sp = SequencePanel.build(
        derived,
        fit_scale(train),
        fit_event_stats(train),
        holidays=NO_HOLIDAYS,
        seq_features="neighbor",
        neighbor_map=NEIGHBOR_MAP,
    )
    s_idx, d_idx = sp.sample_index("2024-03-15", "2024-03-15")
    x = sp.make_batch(s_idx, d_idx, seq_days=7)["x_seq"]
    out = scenario_seq(x, "d1_only", "neighbor")
    obs = observed_channels("neighbor")
    assert np.all(out[:, :-1, :, obs] == 0)  # D−1 자리만 남는다
    np.testing.assert_array_equal(out[:, -1, :, obs], x[:, -1, :, obs])
    assert np.all(scenario_seq(x, "no_lag", "neighbor")[..., obs] == 0)


# ── 145 후속: 학습 창 확장(`splits_with_train_start`) ──


def test_splits_with_train_start_moves_train_only_and_does_not_mutate_base():
    moved = splits_with_train_start("2023-01-01")
    assert moved["train"] == ("2023-01-01", SPLITS["train"][1])
    assert moved["valid"] == SPLITS["valid"] and moved["eval"] == SPLITS["eval"]
    # 원본 SPLITS는 그대로다(같은 dict를 돌려주지 않는다)
    assert SPLITS["train"] == ("2024-01-01", "2024-10-31")
    with pytest.raises(ValueError):
        splits_with_train_start("2024-11-15")  # 학습 종료일(2024-10-31)보다 뒤


def test_split_index_default_matches_explicit_splits_and_moves_with_override(panel):
    derived, scale, sp = panel
    stats = fit_event_stats(derived[derived["date"] <= "2024-03-14"])
    sp_explicit = SequencePanel.build(derived, scale, stats, holidays=NO_HOLIDAYS, splits=SPLITS)
    _, d_idx = sp.split_index("train")
    _, d_idx2 = sp_explicit.split_index("train")
    np.testing.assert_array_equal(np.sort(d_idx), np.sort(d_idx2))
    # 기본 SPLITS는 패널 전체(2024-03)를 덮으므로 학습 표본의 최소 날짜는 패널 시작일이다
    assert sp.dates[d_idx.min()] == DATES[0]

    moved_splits = splits_with_train_start("2024-03-08")
    sp_moved = SequencePanel.build(derived, scale, stats, holidays=NO_HOLIDAYS, splits=moved_splits)
    _, d_idx_moved = sp_moved.split_index("train")
    assert sp_moved.dates[d_idx_moved.min()] == pd.Timestamp("2024-03-08")
    # 검증·평가는 이 패널 범위(3월) 밖이라 기본·이동 둘 다 빈 표본으로 그대로다
    for name in ("valid", "eval"):
        assert len(sp.split_index(name)[0]) == 0
        assert len(sp_moved.split_index(name)[0]) == 0


def test_load_derived_slim_requires_cache_path_when_panel_path_given(tmp_path):
    with pytest.raises(ValueError):
        load_derived_slim(panel_path=tmp_path / "존재하지_않는_패널.parquet")


# ── 200 B부: `--splits` 전체 재정의(`parse_splits`) ──

VALID_SPLITS_JSON = (
    '{"train": ["2024-01-01", "2025-10-31"], "valid": ["2025-11-01", "2025-12-31"],'
    ' "eval": ["2026-01-01", "2026-12-31"]}'
)


def test_parse_splits_valid_json_returns_three_tuples():
    parsed = parse_splits(VALID_SPLITS_JSON)
    assert parsed == {
        "train": ("2024-01-01", "2025-10-31"),
        "valid": ("2025-11-01", "2025-12-31"),
        "eval": ("2026-01-01", "2026-12-31"),
    }


def test_parse_splits_allows_single_day_block():
    parsed = parse_splits(
        '{"train": ["2024-01-01", "2024-01-01"], "valid": ["2024-01-02", "2024-01-02"],'
        ' "eval": ["2024-01-03", "2024-01-03"]}'
    )
    assert parsed["train"] == ("2024-01-01", "2024-01-01")


def test_parse_splits_rejects_malformed_json():
    with pytest.raises(ValueError):
        parse_splits("{이건 JSON이 아니다")


def test_parse_splits_rejects_non_object_json():
    with pytest.raises(ValueError):
        parse_splits('["train", "valid", "eval"]')


def test_parse_splits_rejects_missing_key():
    with pytest.raises(ValueError, match="train.*valid.*eval|키"):
        parse_splits(
            '{"train": ["2024-01-01", "2024-10-31"], "valid": ["2024-11-01", "2024-12-31"]}'
        )


def test_parse_splits_rejects_extra_key():
    with pytest.raises(ValueError):
        parse_splits(
            '{"train": ["2024-01-01", "2024-10-31"], "valid": ["2024-11-01", "2024-12-31"],'
            ' "eval": ["2025-01-01", "2025-12-31"], "extra": ["2026-01-01", "2026-01-02"]}'
        )


def test_parse_splits_rejects_non_two_element_value():
    with pytest.raises(ValueError):
        parse_splits(
            '{"train": ["2024-01-01"], "valid": ["2024-11-01", "2024-12-31"],'
            ' "eval": ["2025-01-01", "2025-12-31"]}'
        )


def test_parse_splits_rejects_unparseable_date():
    with pytest.raises(ValueError):
        parse_splits(
            '{"train": ["안녕", "2024-10-31"], "valid": ["2024-11-01", "2024-12-31"],'
            ' "eval": ["2025-01-01", "2025-12-31"]}'
        )


def test_parse_splits_rejects_reversed_block():
    with pytest.raises(ValueError):
        parse_splits(
            '{"train": ["2024-10-31", "2024-01-01"], "valid": ["2024-11-01", "2024-12-31"],'
            ' "eval": ["2025-01-01", "2025-12-31"]}'
        )


def test_parse_splits_rejects_overlapping_train_and_valid():
    with pytest.raises(ValueError):
        parse_splits(
            '{"train": ["2024-01-01", "2024-11-15"], "valid": ["2024-11-01", "2024-12-31"],'
            ' "eval": ["2025-01-01", "2025-12-31"]}'
        )


def test_parse_splits_rejects_overlapping_valid_and_eval():
    with pytest.raises(ValueError):
        parse_splits(
            '{"train": ["2024-01-01", "2024-10-31"], "valid": ["2024-11-01", "2024-12-31"],'
            ' "eval": ["2024-12-15", "2025-12-31"]}'
        )


def test_parse_splits_rejects_touching_boundaries_without_gap():
    # train[1] < valid[0]은 엄격한 부등호다 — 같은 날은 허용하지 않는다
    with pytest.raises(ValueError):
        parse_splits(
            '{"train": ["2024-01-01", "2024-11-01"], "valid": ["2024-11-01", "2024-12-31"],'
            ' "eval": ["2025-01-01", "2025-12-31"]}'
        )
