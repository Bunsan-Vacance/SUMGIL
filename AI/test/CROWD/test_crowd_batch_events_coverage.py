"""200 — 배치 서빙의 다중 이벤트 표 로딩(`load_event_tables`)과 커버리지 판정(`events_available`).

서빙은 2026 이후 날짜를 예측하는데 학습 이벤트 표(`crowd_station_events_2024_2025.parquet`)는
2025까지만 있어, 2026 표를 뒤에 이어 붙이지 않으면 조용히 0으로 채워진다(문제 설명 참고). 이
표들을 합치는 로직과, 대상 날짜가 그 커버리지 안에 있는지를 meta로 노출하는 로직을 검증한다.
"""

from __future__ import annotations

import pandas as pd

from app.CROWD.pipeline.batch_predict import events_available, load_event_tables


def _write(path, rows: list[dict]) -> None:
    pd.DataFrame(rows).to_parquet(path, index=False)


def test_load_event_tables_later_file_overrides_duplicate_key(tmp_path):
    early = tmp_path / "events_early.parquet"
    late = tmp_path / "events_late.parquet"
    _write(
        early,
        [
            {"date": pd.Timestamp("2025-12-31"), "station_no": 150, "game_count": 0},
            {"date": pd.Timestamp("2026-01-01"), "station_no": 150, "game_count": 0},
        ],
    )
    _write(
        late,
        [
            {"date": pd.Timestamp("2026-01-01"), "station_no": 150, "game_count": 3},
            {"date": pd.Timestamp("2026-12-31"), "station_no": 218, "game_count": 1},
        ],
    )
    combined, coverage_end = load_event_tables([early, late])

    assert coverage_end == pd.Timestamp("2026-12-31")
    row = combined[
        (combined["date"] == pd.Timestamp("2026-01-01")) & (combined["station_no"] == 150)
    ]
    assert len(row) == 1
    assert row.iloc[0]["game_count"] == 3  # 뒤 파일(late)의 값이 남아야 한다
    assert len(combined) == 3  # 2025-12-31 · 2026-01-01(1개로 합쳐짐) · 2026-12-31


def test_load_event_tables_skips_missing_path(tmp_path, capsys):
    exists = tmp_path / "events_exists.parquet"
    missing = tmp_path / "events_missing.parquet"
    _write(exists, [{"date": pd.Timestamp("2026-06-01"), "station_no": 150, "game_count": 1}])

    combined, coverage_end = load_event_tables([missing, exists])

    assert coverage_end == pd.Timestamp("2026-06-01")
    assert len(combined) == 1
    assert "[안내]" in capsys.readouterr().out


def test_load_event_tables_empty_list_returns_none():
    assert load_event_tables([]) == (None, None)


def test_load_event_tables_all_missing_returns_none(tmp_path):
    combined, coverage_end = load_event_tables([tmp_path / "nope.parquet"])
    assert combined is None
    assert coverage_end is None


def test_events_available_true_within_coverage():
    coverage_end = pd.Timestamp("2026-12-31")
    assert events_available(pd.Timestamp("2026-09-22"), coverage_end) is True
    assert events_available(pd.Timestamp("2026-12-31"), coverage_end) is True  # 경계 포함


def test_events_available_false_beyond_coverage():
    coverage_end = pd.Timestamp("2026-12-31")
    assert events_available(pd.Timestamp("2027-01-05"), coverage_end) is False


def test_events_available_false_when_no_coverage():
    assert events_available(pd.Timestamp("2026-09-22"), None) is False
