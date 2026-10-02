from __future__ import annotations

import json

import pandas as pd
import pytest

pytest.importorskip("pyspark")

from DATA_ENGINE.collect.subway_ridership_daily import (  # noqa: E402
    RAW_COLUMNS,
    to_long,
)
from DATA_ENGINE.spark.jobs.crowd_panel_rebuild import (  # noqa: E402
    KEY_COLS,
    aggregate_long_spark,
    main,
    partition_files,
    to_pandas_long,
)
from DATA_ENGINE.spark.metrics import compare_frames  # noqa: E402
from DATA_ENGINE.spark.session import build_spark_session  # noqa: E402


@pytest.fixture(scope="module")
def spark():
    try:
        session = build_spark_session("test-crowd-panel", cores="1", driver_memory="1g")
    except Exception as exc:  # Java 부재 등 세션 생성 실패
        pytest.skip(f"Spark 세션 생성 실패: {exc}")
    yield session
    session.stop()


def _raw_day(day: str, scale: int) -> pd.DataFrame:
    """역 2개 x 시간대 6개 x 카드구분 2 x 사용자구분 2. 00·03시(`24~`), 04·05시(`~06`) 포함."""
    rows = []
    for stn_cd, stn_nm, line in [("150", "서울역", "1호선"), ("151", "종각", "1호선")]:
        for hour in [0, 3, 4, 5, 8, 23]:
            for card in ["1", "2"]:
                for user in ["1", "2"]:
                    n = scale + hour + int(stn_cd) % 7 + int(card) * 3 + int(user)
                    rows.append(
                        {
                            "pasngDe": day,
                            "pasngHr": str(hour),
                            "lineNm": line,
                            "stnCd": stn_cd,
                            "stnNo": stn_cd,
                            "stnNm": stn_nm,
                            "trnscdSeCd": card,
                            "trnscdSeCdNm": f"card{card}",
                            "trnscdUserSeCd": user,
                            "trnscdUserSeCdNm": f"user{user}",
                            "rideNope": str(n),
                            "gffNope": str(n * 2 + 1),
                            "crtrYmd": day,
                        }
                    )
    return pd.DataFrame(rows, columns=RAW_COLUMNS)


def _write_raw(root, days: dict[str, int]) -> pd.DataFrame:
    """`days`: {YYYYMMDD: scale}. dt=<ISO> 파티션으로 쓰고 전체 원문을 돌려준다."""
    frames = []
    for day, scale in days.items():
        raw = _raw_day(day, scale)
        d = f"{day[:4]}-{day[4:6]}-{day[6:]}"
        part = root / f"dt={d}"
        part.mkdir(parents=True)
        raw.to_parquet(part / "getStnPsgr.parquet", index=False)
        frames.append(raw)
    return pd.concat(frames, ignore_index=True)


def _cli(raw_root, out_root, *extra) -> int:
    return main(
        [
            "--input-root",
            str(raw_root),
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


def test_spark_long_matches_pandas_to_long(spark, tmp_path):
    raw_root = tmp_path / "raw"
    raw = _write_raw(raw_root, {"20260101": 10, "20260102": 20, "20260103": 30})

    expected = to_long(raw)
    actual = to_pandas_long(aggregate_long_spark(spark, partition_files(raw_root, [2026])))

    # 슬롯 매핑 확인: 00~03시는 24~, 04~05시는 ~06
    assert {"24~", "~06", "08-09", "23-24"} <= set(actual["time_slot"])
    res = compare_frames(expected, actual, key_cols=KEY_COLS, value_cols=["passengers"])
    assert res["rows_match"]
    assert res["rows_pandas"] == res["rows_spark"] == len(expected)
    assert res["max_abs_err"] == 0.0


def test_base_panel_union_prefers_new_and_has_no_duplicates(spark, tmp_path):
    raw_root, out_root = tmp_path / "raw", tmp_path / "out"
    raw = _write_raw(raw_root, {"20260101": 10, "20260102": 20})

    # 와이드 기존 패널: 2025-12-31 한 행 + 겹치는 2026-01-01 (옛 값 -1)
    base = pd.DataFrame(
        {
            "date": pd.to_datetime(["2025-12-31", "2026-01-01"]),
            "line": "1호선",
            "station_no": [150, 150],
            "station_name": "서울역",
            "time_slot": "08-09",
            "boarding": [5.0, -1.0],
            "alighting": [6.0, -1.0],
            "is_holiday": [False, True],  # 패널 파생 컬럼은 무시돼야 한다
        }
    )
    base_path = tmp_path / "base.parquet"
    base.to_parquet(base_path, index=False)

    assert _cli(raw_root, out_root, "--base-panel", str(base_path)) == 0

    panel = pd.read_parquet(out_root / "panel_test.parquet")
    assert not panel.duplicated(KEY_COLS).any()
    assert pd.api.types.is_datetime64_any_dtype(panel["date"])
    assert (panel["date"] == pd.Timestamp("2025-12-31")).sum() == 2  # boarding·alighting
    base_rows = panel[panel["date"] == pd.Timestamp("2025-12-31")]
    assert base_rows["collected_at"].isna().all()  # base 행은 수집 시각 없음
    assert (base_rows["source"] == "base_panel").all()
    assert (panel["passengers"] != -1.0).all()  # 겹친 날짜는 새 집계

    expected = to_long(raw)
    day1 = panel[panel["date"] == pd.Timestamp("2026-01-01")]
    res = compare_frames(
        expected[expected["date"] == pd.Timestamp("2026-01-01")],
        day1,
        key_cols=KEY_COLS,
        value_cols=["passengers"],
    )
    assert res["rows_match"] and res["max_abs_err"] == 0.0


def test_missing_days_and_verify_recorded_in_meta(spark, tmp_path):
    raw_root, out_root = tmp_path / "raw", tmp_path / "out"
    raw = _write_raw(raw_root, {"20260101": 10, "20260103": 30})  # 01-02 파일 없음
    ref = to_long(raw)
    ref_path = tmp_path / "ref.parquet"
    ref.to_parquet(ref_path, index=False)

    assert _cli(raw_root, out_root, "--verify-against", str(ref_path)) == 0
    meta = json.loads((out_root / "meta.json").read_text(encoding="utf-8"))
    assert meta["missing_days"] == ["2026-01-02"]
    assert meta["input_partitions"] == 2
    assert meta["verify"]["passed"] is True
    assert meta["verify"]["rows_match"] is True

    # 기준 값이 어긋나면 exit 1, 결과는 meta에 남는다
    bad = ref.copy()
    bad.loc[0, "passengers"] += 5
    bad_path = tmp_path / "bad.parquet"
    bad.to_parquet(bad_path, index=False)
    assert _cli(raw_root, out_root, "--verify-against", str(bad_path)) == 1
    meta = json.loads((out_root / "meta.json").read_text(encoding="utf-8"))
    assert meta["verify"]["passed"] is False
    assert meta["verify"]["max_abs_err"] == 5.0


def test_long_format_base_panel_is_unioned(spark, tmp_path):
    raw_root, out_root = tmp_path / "raw", tmp_path / "out"
    _write_raw(raw_root, {"20260101": 10})

    # 롱 포맷 기존 패널(direction·passengers 컬럼): 2025-12-31 한 쌍 + 겹치는 2026-01-01
    base = pd.DataFrame(
        {
            "date": pd.to_datetime(["2025-12-31", "2025-12-31", "2026-01-01"]),
            "line": "1호선",
            "station_no": [150, 150, 150],
            "station_name": "서울역",
            "direction": ["boarding", "alighting", "boarding"],
            "passengers": [5.0, 6.0, -1.0],
            "time_slot": "08-09",
        }
    )
    base_path = tmp_path / "base_long.parquet"
    base.to_parquet(base_path, index=False)

    assert _cli(raw_root, out_root, "--base-panel", str(base_path)) == 0

    panel = pd.read_parquet(out_root / "panel_test.parquet")
    assert not panel.duplicated(KEY_COLS).any()
    old = panel[panel["date"] == pd.Timestamp("2025-12-31")]
    assert sorted(old["direction"]) == ["alighting", "boarding"]
    assert sorted(old["passengers"]) == [5.0, 6.0]
    assert (panel["passengers"] != -1.0).all()  # 겹친 날짜는 새 집계
    assert list(out_root.glob("panel_test*.parquet")) == [out_root / "panel_test.parquet"]
    assert not list(out_root.glob(".*tmp"))  # 임시 파일 정리
