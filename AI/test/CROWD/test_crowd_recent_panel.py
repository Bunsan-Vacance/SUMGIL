"""143 — D−1 수집 롱 포맷을 패널 뒤에 이어붙이는 확장과, 이력이 없을 때 배치 예측의 lookup 대체."""

from __future__ import annotations

import numpy as np
import pandas as pd

from app.CROWD.pipeline.batch_predict import predict_day
from app.CROWD.pipeline.dataset import extend_panel_with_recent, load_recent_long
from app.CROWD.pipeline.features import SLOT_ORDER
from app.CROWD.pipeline.predictor import build_predictor

STATIONS = [(150, "서울역", "1호선"), (151, "시청", "1호선")]
HOLIDAYS = pd.DataFrame({"date": pd.to_datetime([]), "is_holiday": pd.Series([], dtype=bool)})


def _panel(start="2025-12-20", end="2025-12-31") -> pd.DataFrame:
    rows = []
    for d in pd.date_range(start, end):
        for no, name, line in STATIONS:
            for i, slot in enumerate(SLOT_ORDER):
                rows.append(
                    {
                        "date": d,
                        "station_no": no,
                        "station_name": name,
                        "line": line,
                        "lat": 37.5,
                        "lon": 127.0,
                        "time_slot": slot,
                        "boarding": 100.0 + i,
                        "alighting": 90.0 + i,
                        "temp_c": 5.0,
                        "game_count": 0,
                    }
                )
    panel = pd.DataFrame(rows)
    panel["dow"] = panel["date"].dt.dayofweek
    panel["weekday_ko"] = "월"
    panel["is_holiday"] = False
    panel["is_weekend"] = panel["dow"] >= 5
    panel["day_type"] = np.where(panel["dow"] >= 5, "토요일", "평일")
    return panel


def _recent(dates=("2025-12-31", "2026-01-01", "2026-01-02"), extra_station=True) -> pd.DataFrame:
    rows = []
    for d in pd.to_datetime(list(dates)):
        stations = list(STATIONS) + ([(2565, "하남시청", "5호선")] if extra_station else [])
        for no, name, line in stations:
            for slot in SLOT_ORDER:
                for direction, v in (("boarding", 200.0), ("alighting", 180.0)):
                    rows.append(
                        {
                            "date": d,
                            "line": line,
                            "station_no": no,
                            "station_name": name,
                            "direction": direction,
                            "passengers": v,
                            "time_slot": slot,
                            "source": "getStnPsgr",
                        }
                    )
    return pd.DataFrame(rows)


def test_extend_appends_only_new_dates_and_panel_stations():
    panel = _panel()
    out, dates = extend_panel_with_recent(panel, _recent(), holidays=HOLIDAYS)
    assert dates == ["2026-01-01", "2026-01-02"]  # 패널 마지막 날(12-31)은 다시 넣지 않는다
    added = out[out["date"] > "2025-12-31"]
    assert set(added["station_no"]) == {150, 151}  # 하남시청(패널 밖) 제외
    assert len(added) == 2 * 2 * len(SLOT_ORDER)
    assert list(out.columns) == list(panel.columns)
    row = added[(added["station_no"] == 150) & (added["time_slot"] == "07-08")].iloc[0]
    assert row["boarding"] == 200.0 and row["alighting"] == 180.0
    assert row["station_name"] == "서울역" and row["lat"] == 37.5  # 역 메타는 패널 것
    assert pd.isna(row["temp_c"]) and row["game_count"] == 0  # 기상 NaN, 이벤트 개수는 0
    assert set(added["day_type"]) <= {"평일", "토요일", "일요일", "휴일"}
    assert out["station_no"].dtype == "int64"


def test_extend_with_events_table_fills_counts():
    panel = _panel()
    events = pd.DataFrame(
        {"date": pd.to_datetime(["2026-01-02"]), "station_no": [150], "game_count": [1]}
    )
    out, _ = extend_panel_with_recent(panel, _recent(), holidays=HOLIDAYS, events=events)
    added = out[out["date"] == "2026-01-02"]
    assert added.loc[added["station_no"] == 150, "game_count"].eq(1).all()
    assert added.loc[added["station_no"] == 151, "game_count"].eq(0).all()


def test_extend_noop_when_nothing_newer():
    panel = _panel()
    out, dates = extend_panel_with_recent(panel, _recent(dates=("2025-12-30",)), holidays=HOLIDAYS)
    assert dates == [] and len(out) == len(panel)


def test_load_recent_long_missing_returns_none(tmp_path):
    assert load_recent_long(tmp_path / "nope.parquet") is None
    _recent().to_parquet(tmp_path / "r.parquet", index=False)
    df = load_recent_long(tmp_path / "r.parquet")
    assert df is not None and str(df["date"].dtype).startswith("datetime64")


def test_predict_day_reports_availability_from_recent_history():
    """143 확장이 이력 창(lag 가용성)에 미치는 영향 — 라우팅 자체는 `test_crowd_routing.py`가 본다.

    여기서는 `override_kind`로 라우팅을 건너뛰고 lookup 하나로 고정해, `extend_panel_with_recent`가
    실제로 `predict_day`가 보는 이력을 늘리는지만 확인한다(197: 옛 "이력 전무 → lookup 강제 대체"
    fallback은 없어졌고, 지금은 `no_lag`도 라우팅이 정한 예측기를 쓴다 — `meta.predictor_fallback`은
    키만 남고 항상 `None`이다).
    """
    panel = _panel()
    lookup = build_predictor("lookup", train_panel=panel)

    def factory(kind: str):
        assert kind == "lookup"
        return lookup

    # 이력 없음(패널 끝 12-31, 대상 01-10) → avail은 no_lag, override로 lookup 고정
    _, meta = predict_day(
        factory, panel, pd.Timestamp("2026-01-10"), [], HOLIDAYS, None, override_kind="lookup"
    )
    assert meta["history_days_present"] == 0
    assert meta["availability"] == "no_lag"
    assert meta["predictor"] == "lookup" and meta["predictor_fallback"] is None
    assert meta["predictor_override"] is True and meta["routing_rule"] is None

    # 최근 실측을 이어붙이면 이력이 생기고 lag1d_available(1주 전은 아직 없어 d1_only)
    ext, _ = extend_panel_with_recent(
        panel, _recent(dates=("2026-01-08", "2026-01-09")), holidays=HOLIDAYS
    )
    pred, meta = predict_day(
        factory, ext, pd.Timestamp("2026-01-10"), [], HOLIDAYS, None, override_kind="lookup"
    )
    assert meta["history_days_present"] == 2 and meta["lag1d_available"] is True
    assert meta["availability"] == "d1_only"
    assert meta["predictor_fallback"] is None and meta["history_dates"] == [
        "2026-01-08",
        "2026-01-09",
    ]
    assert len(pred) == 2 * len(SLOT_ORDER) and pred["boarding_pred"].notna().all()
