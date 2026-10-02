"""crowd_data_quality 잡 합성 테스트 — 기준 표 손계산 일치와 DQ1·DQ4·DQ6 경보 경로를 검증한다."""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("pyspark")

from DATA_ENGINE.collect.subway_ridership_daily import RAW_COLUMNS  # noqa: E402
from DATA_ENGINE.spark.jobs.crowd_data_quality import (  # noqa: E402
    BASELINE_FILE,
    BASELINE_META,
    DQ_THRESHOLDS,
    js_distance,
    main,
)
from DATA_ENGINE.spark.session import build_spark_session  # noqa: E402

STATIONS = [(150, "서울역", "1호선"), (151, "종각", "1호선"), (152, "강남", "2호선")]
# 슬롯 4개: 00·03시 -> "24~", 04·05시 -> "~06", 08시 -> "08-09", 23시 -> "23-24"
SLOT_HOURS = {"24~": [0, 3], "~06": [4, 5], "08-09": [8], "23-24": [23]}
ZERO_CELL = (151, "~06")  # 0이 섞이는 셀(zero_ratio 기준 확인용)
OFFSETS = np.array([-3, -2, -1, -1, 0, 0, 1, 1, 2, 3], dtype="float64")  # 평균 0, 표준편차 약 1.7
ALIGHT_FACTOR = 1.5


@pytest.fixture(scope="module", autouse=True)
def _spark_available():
    """Java 부재 등으로 세션을 못 만들면 스킵. 잡이 자기 세션을 만들므로 확인 뒤 바로 닫는다."""
    try:
        session = build_spark_session("test-dq-probe", cores="1", driver_memory="1g")
    except Exception as exc:
        pytest.skip(f"Spark 세션 생성 실패: {exc}")
    session.stop()


def _base_dates() -> dict[str, list[str]]:
    """요일유형별 10일: 2024-06 평일 17~28일, 토 06-01 시작 주간, 일 06-02 시작 주간(공휴일 없음)."""
    weekdays = [d for d in pd.date_range("2024-06-17", "2024-06-28") if d.dayofweek < 5]
    sats = list(pd.date_range("2024-06-01", periods=10, freq="7D"))
    suns = list(pd.date_range("2024-06-02", periods=10, freq="7D"))
    return {"평일": weekdays, "토요일": sats, "일요일": suns}


def _base_panel() -> pd.DataFrame:
    rows = []
    for dts in _base_dates().values():
        for stn_no, name, line in STATIONS:
            for slot in SLOT_HOURS:
                rng = np.random.default_rng(stn_no * 31 + len(slot))
                offs = rng.permutation(OFFSETS)
                vals = 100.0 + offs
                if (stn_no, slot) == ZERO_CELL:
                    vals[:2] = 0.0  # 10일 중 2일은 0
                for d, v in zip(dts, vals, strict=True):
                    rows.append(
                        {
                            "date": d,
                            "line": line,
                            "station_no": stn_no,
                            "station_name": name,
                            "time_slot": slot,
                            "boarding": float(v),
                            "alighting": float(v) * ALIGHT_FACTOR,
                        }
                    )
    return pd.DataFrame(rows)


def _raw_day(
    day: str, overrides: dict | None = None, skip_station: int | None = None
) -> pd.DataFrame:
    """정상 값(기준 평균 + 1)의 raw 하루치. 슬롯 값은 해당 시간·카드구분 4행에 균등 분배한다.

    `overrides`: {(station_no, slot): 승차 값}, `skip_station`: 통째로 뺄 역.
    """
    overrides = overrides or {}
    rows = []
    for stn_no, name, line in STATIONS:
        if stn_no == skip_station:
            continue
        for slot, hours in SLOT_HOURS.items():
            board = overrides.get((stn_no, slot), 101.0)
            for hour in hours:
                for card in ["1", "2"]:
                    for user in ["1", "2"]:
                        per = len(hours) * 4
                        rows.append(
                            {
                                "pasngDe": day,
                                "pasngHr": str(hour),
                                "lineNm": line,
                                "stnCd": str(stn_no),
                                "stnNo": str(stn_no),
                                "stnNm": name,
                                "trnscdSeCd": card,
                                "trnscdSeCdNm": f"card{card}",
                                "trnscdUserSeCd": user,
                                "trnscdUserSeCdNm": f"user{user}",
                                "rideNope": str(board / per),
                                "gffNope": str(board * ALIGHT_FACTOR / per),
                                "crtrYmd": day,
                            }
                        )
    return pd.DataFrame(rows, columns=RAW_COLUMNS)


def _write_day(root, day: str, raw: pd.DataFrame, lag_days: int = 1) -> None:
    d = f"{day[:4]}-{day[4:6]}-{day[6:]}"
    part = root / f"dt={d}"
    part.mkdir(parents=True)
    path = part / "getStnPsgr.parquet"
    raw.to_parquet(path, index=False)
    mtime = (datetime.strptime(d, "%Y-%m-%d") + timedelta(days=lag_days, hours=12)).timestamp()
    os.utime(path, (mtime, mtime))


@pytest.fixture(scope="module")
def baseline(tmp_path_factory):
    root = tmp_path_factory.mktemp("dq_base")
    panel = _base_panel()
    panel_path = root / "panel_synth.parquet"
    panel.to_parquet(panel_path, index=False)
    bdir = root / "baseline"
    rc = main(
        [
            "--rebuild-baseline",
            "--base-panel",
            str(panel_path),
            "--baseline-dir",
            str(bdir),
            "--cores",
            "1",
            "--driver-memory",
            "1g",
        ]
    )
    assert rc == 0
    return {"dir": bdir, "panel": panel, "panel_path": panel_path}


def _run_day(
    tmp_path, baseline_dir, raw: pd.DataFrame, *extra, lag_days: int = 1
) -> tuple[int, dict]:
    raw_root, out_root = tmp_path / "raw", tmp_path / "out"
    _write_day(raw_root, "20260310", raw, lag_days)  # 2026-03-10 화요일, 공휴일 아님
    rc = main(
        [
            "--input-root",
            str(raw_root),
            "--baseline-dir",
            str(baseline_dir),
            "--out-root",
            str(out_root),
            "--run",
            "test",
            "--cores",
            "1",
            "--driver-memory",
            "1g",
            *extra,
        ]
    )
    part = out_root / "dt=2026-03-10" / "part.json"
    return rc, (json.loads(part.read_text(encoding="utf-8")) if part.exists() else {})


def test_rebuild_baseline_matches_hand_calculation(baseline):
    table = pd.read_parquet(baseline["dir"] / BASELINE_FILE)
    meta = json.loads((baseline["dir"] / BASELINE_META).read_text(encoding="utf-8"))
    panel = baseline["panel"]

    assert len(table) == 3 * len(STATIONS) * len(SLOT_HOURS) * 2  # 요일유형 x 역 x 슬롯 x 방향
    assert list(table.columns) == [
        "day_type",
        "line",
        "station_no",
        "station_name",
        "time_slot",
        "direction",
        "mean",
        "std",
        "zero_ratio",
        "n",
    ]
    assert meta["expected_stations"] == [150, 151, 152]
    assert meta["version"] == f"panel_synth@{len(panel)}"
    assert sorted(meta["day_types"]) == ["일요일", "토요일", "평일"]
    for shares in meta["slot_share"].values():
        assert sum(shares.values()) == pytest.approx(1.0, abs=1e-9)

    dow = panel["date"].dt.dayofweek
    sub = panel[(dow < 5) & (panel["station_no"] == 150) & (panel["time_slot"] == "08-09")]
    cell = table[
        (table["day_type"] == "평일")
        & (table["station_no"] == 150)
        & (table["time_slot"] == "08-09")
        & (table["direction"] == "boarding")
    ].iloc[0]
    assert cell["mean"] == pytest.approx(sub["boarding"].mean(), abs=1e-6)
    assert cell["std"] == pytest.approx(sub["boarding"].std(ddof=1), abs=1e-6)
    assert cell["n"] == len(sub) == 10

    zsub = panel[(dow == 5) & (panel["station_no"] == 151) & (panel["time_slot"] == "~06")]
    zcell = table[
        (table["day_type"] == "토요일")
        & (table["station_no"] == 151)
        & (table["time_slot"] == "~06")
        & (table["direction"] == "alighting")
    ].iloc[0]
    assert zcell["zero_ratio"] == pytest.approx((zsub["alighting"] == 0).mean(), abs=1e-9)
    assert zcell["zero_ratio"] == pytest.approx(0.2)
    assert zcell["mean"] == pytest.approx(zsub["alighting"].mean(), abs=1e-6)

    # 호선 일 총량 평균·표준편차(승차 합)
    wk = (
        panel[dow < 5]
        .groupby(["date", "line"])["boarding"]
        .sum()
        .groupby("line")
        .agg(["mean", "std"])
    )
    got = meta["line_totals"]["평일"]["1호선"]
    assert got["mean"] == pytest.approx(wk.loc["1호선", "mean"], abs=1e-6)
    assert got["std"] == pytest.approx(wk.loc["1호선", "std"], abs=1e-6)


def test_js_distance_basic():
    assert js_distance({"a": 1, "b": 1}, {"a": 2, "b": 2}) == pytest.approx(0.0, abs=1e-12)
    assert js_distance({"a": 1}, {"b": 1}) == pytest.approx(1.0, abs=1e-12)
    assert js_distance({}, {"a": 1}) is None


def test_normal_day_has_no_alerts(baseline, tmp_path):
    rc, part = _run_day(tmp_path, baseline["dir"], _raw_day("20260310"))
    assert rc == 0
    assert part["outlier_count"] == 0
    assert part["alerts"] == []
    assert part["rows"] == len(STATIONS) * len(SLOT_HOURS) * 2
    assert part["stations"] == 3 and part["expected_stations"] == 3
    assert part["missing_stations"] == []
    assert part["schema_ok"] is True
    assert part["day_type"] == "평일"
    assert part["collect_lag_days"] == 1
    assert part["synthetic"] is False
    assert part["baseline_version"] == f"panel_synth@{len(baseline['panel'])}"
    assert part["slot_js"] < DQ_THRESHOLDS["slot_js"]
    assert part["zero_ratio"] == 0.0 and part["zero_ratio_baseline"] > 0

    run_meta = json.loads((tmp_path / "out" / "run_meta.json").read_text(encoding="utf-8"))
    assert run_meta["job"] == "crowd_data_quality"
    assert run_meta["rows_in"] == part["rows"]
    assert run_meta["dates"] == ["2026-03-10"]
    assert run_meta["rc"] == 0 and run_meta["spark"]["cores"] == "1"
    assert not list((tmp_path / "out").rglob(".*tmp"))  # 임시 파일 정리


def test_injected_outlier_is_top_and_alerts_dq4(baseline, tmp_path):
    raw = _raw_day("20260310", overrides={(150, "08-09"): 1000.0})  # 기준 약 100의 10배
    rc, part = _run_day(tmp_path, baseline["dir"], raw, "--mark-synthetic")
    assert rc == 0
    assert part["outlier_count"] >= 1
    top = part["outliers_top"][0]
    assert (top["station_no"], top["time_slot"], top["direction"]) == (150, "08-09", "boarding")
    assert top["value"] == pytest.approx(1000.0)
    assert top["z"] > DQ_THRESHOLDS["outlier_z"]
    assert "DQ4" in part["alerts"]
    assert part["synthetic"] is True


def test_missing_station_alerts_dq1(baseline, tmp_path):
    rc, part = _run_day(tmp_path, baseline["dir"], _raw_day("20260310", skip_station=152))
    assert rc == 0
    assert part["missing_stations"] == [152]
    assert part["stations"] == 2
    assert "DQ1" in part["alerts"]


def test_schema_change_alerts_dq6(baseline, tmp_path):
    raw = _raw_day("20260310")
    raw["rideNope"] = raw["rideNope"].astype(float)  # 타입 변경(문자열 -> 실수)
    raw["newColumn"] = "x"  # 컬럼 추가
    rc, part = _run_day(tmp_path, baseline["dir"], raw)
    assert rc == 0
    assert part["schema_ok"] is False
    assert "extra:newColumn" in part["schema_diff"]
    assert any(d.startswith("type:rideNope") for d in part["schema_diff"])
    assert "DQ6" in part["alerts"]


def test_exit_2_without_baseline(tmp_path):
    raw_root = tmp_path / "raw"
    _write_day(raw_root, "20260310", _raw_day("20260310"))
    rc = main(
        [
            "--input-root",
            str(raw_root),
            "--baseline-dir",
            str(tmp_path / "no_baseline"),
            "--out-root",
            str(tmp_path / "out"),
            "--cores",
            "1",
            "--driver-memory",
            "1g",
        ]
    )
    assert rc == 2
    assert not (tmp_path / "out").exists()


def test_level_adjust_records_z_adjusted(baseline, tmp_path):
    rc, part = _run_day(tmp_path, baseline["dir"], _raw_day("20260310"), "--level-adjust")
    assert rc == 0
    for row in part["line_totals"]:
        assert "z_adjusted" in row
        # 하루짜리 입력이면 중앙값 비율이 그날 비율이라 보정 후 총량은 기준 평균과 같다 -> z_adjusted 0
        assert row["z_adjusted"] == pytest.approx(0.0, abs=1e-9)
        assert row["level_ratio"] == pytest.approx(row["total"] / row["baseline_mean"])


def test_lag_alert_dq7(baseline, tmp_path):
    rc, part = _run_day(tmp_path, baseline["dir"], _raw_day("20260310"), lag_days=5)
    assert rc == 0
    assert part["collect_lag_days"] == 5
    assert "DQ7" in part["alerts"]
