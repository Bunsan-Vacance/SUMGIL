"""DL 예측기(144) — 합성 패널로 1에폭 학습 → 저장 → **CPU 로드** → predict.

EC2 배치에는 GPU가 없으므로 학습(GPU)에서 나온 state_dict를 CPU로 읽는 경로가 프로덕션 경로다.
그래서 이 테스트는 장치를 `cpu`로 고정하고, 파라미터가 실제로 CPU에 올라왔는지까지 본다.

torch는 `requirements-ci.txt`에 없다 — 파일 최상단에서 `importorskip`으로 감싼다(`AI/CLAUDE.md`).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

torch = pytest.importorskip("torch")

from app.CROWD.pipeline.dl.dataset import (  # noqa: E402
    EVENT_STATIC_COLS,
    RESID_COLS,
    SequencePanel,
    fit_event_stats,
    fit_scale,
)
from app.CROWD.pipeline.dl.train_dl import save_artifact, train_one  # noqa: E402
from app.CROWD.pipeline.features import SLOT_ORDER  # noqa: E402
from app.CROWD.pipeline.lookup import TARGETS, DayTypeLookupBaseline  # noqa: E402
from app.CROWD.pipeline.predictor import OUTPUT_KEYS, build_predictor  # noqa: E402

STATIONS = [101, 205, 333, 404]
DATES = pd.date_range("2024-01-01", "2024-03-31", freq="D")
TARGET_DATE = pd.Timestamp("2024-04-01")
VALID_FROM = pd.Timestamp("2024-03-20")
# 이 조합만 lookup 학습에서 빼 "조회 실패 → NaN 유지"를 재현한다.
NO_LOOKUP_STATION, NO_LOOKUP_SLOT = 404, "07-08"


def _panel(dates: pd.DatetimeIndex) -> pd.DataFrame:
    rng = np.random.default_rng(7)
    rows = []
    for s_i, s in enumerate(STATIONS):
        base = 100.0 * (s_i + 1)
        for d in dates:
            dow = d.dayofweek
            day_type = "평일" if dow < 5 else ("토요일" if dow == 5 else "일요일")
            for k, slot in enumerate(SLOT_ORDER):
                shape = 1.0 + np.sin(k / 3.0)
                rows.append(
                    {
                        "date": d,
                        "station_no": s,
                        "time_slot": slot,
                        "day_type": day_type,
                        "boarding": base * shape + rng.normal(0, 10),
                        "alighting": base * shape * 0.9 + rng.normal(0, 10),
                        "game_count": 0,
                        "festival_count": 0,
                        "festival_short_count": 0,
                        "festival_long_count": 0,
                        "festival_min_duration_days": np.nan,
                    }
                )
    return pd.DataFrame(rows)


def _derived(panel: pd.DataFrame, lookup: DayTypeLookupBaseline) -> pd.DataFrame:
    out = panel[["date", "station_no", "time_slot", "day_type", *EVENT_STATIC_COLS]].copy()
    resid = lookup.residuals(panel)
    for c in RESID_COLS:
        out[c] = resid[c].to_numpy()
    return out


@pytest.fixture(scope="module")
def artifact(tmp_path_factory):
    """합성 패널로 1에폭 학습해 아티팩트를 만든다(GPU 없이 cpu 고정)."""
    panel = _panel(DATES)
    fit_rows = ~(
        (panel["station_no"] == NO_LOOKUP_STATION) & (panel["time_slot"] == NO_LOOKUP_SLOT)
    )
    lookup = DayTypeLookupBaseline().fit(panel[fit_rows])
    derived = _derived(panel, lookup)
    train_d = derived[derived["date"] < VALID_FROM]
    scale, stats = fit_scale(train_d), fit_event_stats(train_d)
    sp = SequencePanel.build(derived, scale, stats)

    idx_train = sp.sample_index(DATES[0], VALID_FROM - pd.Timedelta(days=1))
    idx_valid = sp.sample_index(VALID_FROM, DATES[-1])
    model, history, best_epoch = train_one(
        sp,
        idx_train,
        idx_valid,
        model_kind="gru",
        seq_days=14,
        hidden=8,
        epochs=1,
        patience=1,
        seed=0,
        device="cpu",
        batch_size=64,
        lr=1e-3,
        p_full=0.0,
        truncation=True,
        quiet=True,
    )
    meta = {
        "model_kind": "dl",
        "model": "gru",
        "seq_days": 14,
        "hidden": 8,
        "emb_dim": 16,
        "mlp_hidden": 128,
        "targets": TARGETS,
        "lookup_keys": lookup.keys,
        "station_ids": [int(s) for s in sp.station_ids],
        "best_epoch": best_epoch,
        "device": "cpu",
    }
    out = tmp_path_factory.mktemp("models") / "dl_gru_s14_test"
    save_artifact(out, model, sp, lookup, stats, meta, history)
    return out, panel


def _window(panel: pd.DataFrame, history_days: int) -> pd.DataFrame:
    """직전 `history_days`일 실측 + 대상 날짜 골격(승하차 NaN) — 배치가 넘기는 모양."""
    hist = panel[panel["date"] >= TARGET_DATE - pd.Timedelta(days=history_days)]
    target = _panel(pd.DatetimeIndex([TARGET_DATE]))
    target[TARGETS] = np.nan
    return pd.concat([hist, target], ignore_index=True)


def test_artifact_files_and_predictor_metadata(artifact):
    art, _ = artifact
    for name in ("model.pt", "scale.parquet", "lookup.parquet", "event_stats.parquet"):
        assert (art / name).exists(), name
    predictor = build_predictor("dl", artifact_dir=art)
    assert predictor.kind == "dl" and predictor.version.startswith("dl:")
    assert predictor.required_history_days == 14  # 배치가 창을 14일로 넓히는 근거


def test_loaded_on_cpu_with_map_location(artifact):
    """GPU에서 저장된 state_dict라도 `map_location="cpu"`로 읽힌다 — EC2 배치 경로."""
    art, _ = artifact
    predictor = build_predictor("dl", artifact_dir=art)
    params = list(predictor._inner.model.parameters())
    assert params and all(p.device.type == "cpu" for p in params)
    assert torch.load(art / "model.pt", map_location="cpu")


def test_predict_shape_columns_and_nan_rules(artifact):
    art, panel = artifact
    predictor = build_predictor("dl", artifact_dir=art)
    window = _window(panel, history_days=14)
    out = predictor.predict(window, segments=[])

    assert len(out) == len(window)
    # LightGBM 예측기와 같은 컬럼(OUTPUT_KEYS + *_pred + *_lookup)
    assert set(out.columns) == {
        *OUTPUT_KEYS,
        *[f"{t}_{suffix}" for t in TARGETS for suffix in ("lookup", "pred")],
    }

    target = out[out["date"] == TARGET_DATE]
    assert len(target) == len(STATIONS) * len(SLOT_ORDER)
    no_lookup = target[
        (target["station_no"] == NO_LOOKUP_STATION) & (target["time_slot"] == NO_LOOKUP_SLOT)
    ]
    # lookup 조회 실패 행은 채우지 않는다(원칙 8)
    assert no_lookup["boarding_lookup"].isna().all() and no_lookup["boarding_pred"].isna().all()
    ok = target.drop(no_lookup.index)
    assert ok[[f"{t}_pred" for t in TARGETS]].notna().all().all()
    # 잔차 모델이므로 lookup과 같지 않다(0 잔차로 퇴화하지 않았다)
    assert (ok["boarding_pred"] != ok["boarding_lookup"]).mean() > 0.9


def test_seven_day_window_still_works(artifact):
    """배치 기본 창(7일)만 와도 앞쪽 7일이 마스크 0으로 채워져 예측이 나온다."""
    art, panel = artifact
    predictor = build_predictor("dl", artifact_dir=art)
    out7 = predictor.predict(_window(panel, history_days=7), segments=[])
    t7 = out7[(out7["date"] == TARGET_DATE) & (out7["station_no"] == 101)]
    assert len(t7) == len(SLOT_ORDER) and t7["boarding_pred"].notna().all()

    out14 = predictor.predict(_window(panel, history_days=14), segments=[])
    t14 = out14[(out14["date"] == TARGET_DATE) & (out14["station_no"] == 101)]
    # 이력이 다르면 값도 달라야 한다 — 시퀀스를 실제로 보고 있다는 뜻
    assert not np.allclose(t7["boarding_pred"].to_numpy(), t14["boarding_pred"].to_numpy())


def test_scenario_switch_masks_history(artifact):
    """`scenario`는 이력에서 지정한 시차만 남긴다 — 144 평가가 서빙과 같은 코드로 4시나리오를 잰다."""
    art, panel = artifact
    predictor = build_predictor("dl", artifact_dir=art)
    window = _window(panel, history_days=14)
    full = predictor.predict(window, segments=[])
    predictor.scenario = "no_lag"
    no_lag = predictor.predict(window, segments=[])
    predictor.scenario = None
    assert predictor.scenario is None
    sel = (full["date"] == TARGET_DATE) & full["boarding_pred"].notna()
    assert not np.allclose(full.loc[sel, "boarding_pred"], no_lag.loc[sel, "boarding_pred"])


# ── 198: `neighbor` 입력 안의 채널 복원(서빙 경로) ──

STATION_NAMES = {101: "가역", 205: "나역", 333: "다역", 404: "가역"}  # 404는 101과 환승 노드
SEGMENTS = [{"line": "1호선", "segment": "본선", "stations": STATIONS}]


def _panel_with_names(dates: pd.DatetimeIndex) -> pd.DataFrame:
    out = _panel(dates)
    out["station_name"] = out["station_no"].map(STATION_NAMES)
    out["line"] = "1호선"
    return out


def _neighbor_map() -> pd.DataFrame:
    from app.CROWD.pipeline.adjacency import build_neighbor_map, build_transfer_map

    nodes = pd.DataFrame(
        {
            "station_no": STATIONS,
            "station_name": [STATION_NAMES[s] for s in STATIONS],
            "line": "1호선",
        }
    )
    return pd.concat([build_neighbor_map(SEGMENTS), build_transfer_map(nodes)], ignore_index=True)


@pytest.fixture(scope="module")
def neighbor_artifact(tmp_path_factory):
    """`seq_features="neighbor"` 아티팩트 — 16채널을 meta로 복원하는지 보려고 1에폭만 학습한다."""
    from app.CROWD.pipeline.adjacency import attach_neighbor_features
    from app.CROWD.pipeline.dl.dataset import seq_channels_for, stat_features_for

    panel = _panel_with_names(DATES)
    lookup = DayTypeLookupBaseline().fit(panel)
    derived = attach_neighbor_features(_derived(panel, lookup), _neighbor_map(), RESID_COLS)
    train_d = derived[derived["date"] < VALID_FROM]
    scale, stats = fit_scale(train_d), fit_event_stats(train_d)
    sp = SequencePanel.build(
        derived, scale, stats, seq_features="neighbor", neighbor_map=_neighbor_map()
    )
    model, history, best_epoch = train_one(
        sp,
        sp.sample_index(DATES[0], VALID_FROM - pd.Timedelta(days=1)),
        sp.sample_index(VALID_FROM, DATES[-1]),
        model_kind="gru",
        seq_days=14,
        hidden=8,
        epochs=1,
        patience=1,
        seed=0,
        device="cpu",
        batch_size=64,
        lr=1e-3,
        p_full=0.0,
        truncation=True,
        quiet=True,
    )
    meta = {
        "model_kind": "dl",
        "model": "gru",
        "seq_days": 14,
        "hidden": 8,
        "emb_dim": 16,
        "mlp_hidden": 128,
        "channels": seq_channels_for("neighbor"),
        "seq_features": "neighbor",
        "use_static_events": True,
        "stat_features": stat_features_for(True),
        "targets": TARGETS,
        "lookup_keys": lookup.keys,
        "station_ids": [int(s) for s in sp.station_ids],
        "best_epoch": best_epoch,
        "device": "cpu",
    }
    out = tmp_path_factory.mktemp("models") / "dl_gru_s14_neighbor_s0_test"
    save_artifact(out, model, sp, lookup, stats, meta, history)
    return out, panel


def test_neighbor_artifact_restores_16_channels_from_meta(neighbor_artifact):
    art, _ = neighbor_artifact
    predictor = build_predictor("dl", artifact_dir=art)
    inner = predictor._inner
    assert inner.seq_features == "neighbor" and inner.use_static_events
    assert inner.model.rnn.input_size == len(SLOT_ORDER) * 16


def test_neighbor_predictor_needs_segments_and_uses_them(neighbor_artifact):
    """이웃 표는 `predict(segments=…)`로만 만들 수 있다 — 빈 목록이면 명확한 오류."""
    art, panel = neighbor_artifact
    predictor = build_predictor("dl", artifact_dir=art)
    window = _window(panel, history_days=14)
    window["station_name"] = window["station_no"].map(STATION_NAMES)
    window["line"] = "1호선"

    out = predictor.predict(window, segments=SEGMENTS)
    target = out[out["date"] == TARGET_DATE]
    assert len(target) == len(STATIONS) * len(SLOT_ORDER)
    assert target[[f"{t}_pred" for t in TARGETS]].notna().all().all()
    assert (target["boarding_pred"] != target["boarding_lookup"]).mean() > 0.9

    # 이웃 표가 아예 없으면(세그먼트 없음 + 역명 없음) 조용히 0으로 채우지 않고 막는다
    bare = window.drop(columns=["station_name", "line"])
    with pytest.raises(ValueError, match="이웃 표"):
        predictor.predict(bare, segments=[])


def test_seven_day_window_works_for_neighbor_artifact(neighbor_artifact):
    """짧은 창(7일)에서도 이웃 채널이 같은 규칙으로 만들어진다 — 배치 기본 창."""
    art, panel = neighbor_artifact
    predictor = build_predictor("dl", artifact_dir=art)
    w7 = _window(panel, history_days=7)
    w7["station_name"] = w7["station_no"].map(STATION_NAMES)
    w7["line"] = "1호선"
    out = predictor.predict(w7, segments=SEGMENTS)
    t7 = out[(out["date"] == TARGET_DATE) & (out["station_no"] == 205)]
    assert len(t7) == len(SLOT_ORDER) and t7["boarding_pred"].notna().all()


# ── 198: 정적 이벤트 없는 채택 구성(train_dl 기본값) ──


@pytest.fixture(scope="module")
def no_events_artifact(tmp_path_factory):
    """`use_static_events=False` 아티팩트 — 정적 폭 4를 meta로 복원하는지 본다."""
    from app.CROWD.pipeline.dl.dataset import stat_features_for

    panel = _panel(DATES)
    lookup = DayTypeLookupBaseline().fit(panel)
    derived = _derived(panel, lookup)
    train_d = derived[derived["date"] < VALID_FROM]
    scale, stats = fit_scale(train_d), fit_event_stats(train_d)
    sp = SequencePanel.build(derived, scale, stats, use_static_events=False)
    model, history, best_epoch = train_one(
        sp,
        sp.sample_index(DATES[0], VALID_FROM - pd.Timedelta(days=1)),
        sp.sample_index(VALID_FROM, DATES[-1]),
        model_kind="gru",
        seq_days=14,
        hidden=8,
        epochs=1,
        patience=1,
        seed=0,
        device="cpu",
        batch_size=64,
        lr=1e-3,
        p_full=0.0,
        truncation=True,
        quiet=True,
    )
    meta = {
        "model_kind": "dl",
        "model": "gru",
        "seq_days": 14,
        "hidden": 8,
        "emb_dim": 16,
        "mlp_hidden": 128,
        "channels": 7,
        "seq_features": "base",
        "use_static_events": False,
        "stat_features": stat_features_for(False),
        "targets": TARGETS,
        "lookup_keys": lookup.keys,
        "station_ids": [int(s) for s in sp.station_ids],
        "best_epoch": best_epoch,
        "device": "cpu",
    }
    out = tmp_path_factory.mktemp("models") / "dl_gru_s14_noev_s0_test"
    save_artifact(out, model, sp, lookup, stats, meta, history)
    return out, panel


def test_no_static_events_artifact_restores_stat_width_four(no_events_artifact):
    art, panel = no_events_artifact
    predictor = build_predictor("dl", artifact_dir=art)
    inner = predictor._inner
    assert inner.use_static_events is False
    # head 입력 = hidden 8 + emb 16 + 정적 4
    assert inner.model.head[0].in_features == 8 + 16 + 4

    out = predictor.predict(_window(panel, history_days=14), segments=[])
    target = out[out["date"] == TARGET_DATE]
    assert target[[f"{t}_pred" for t in TARGETS]].notna().all().all()
