import pandas as pd
import pytest

from DATA_ENGINE.eda.parsers_holiday import build_holiday_calendar, duplicate_date_inventory


def test_duplicate_date_inventory_flags_overlap():
    df = pd.DataFrame(
        {
            "date": pd.to_datetime(["2024-01-01", "2024-01-01", "2024-01-02"]),
            "is_holiday": [True, True, False],
        }
    )

    result = duplicate_date_inventory(df)

    assert len(result) == 2


def test_build_holiday_calendar_raises_when_multiple_files(tmp_path):
    (tmp_path / "a.csv").write_text(
        "일자,공휴일여부,영어요일명,한국어요일명\n2024-01-01,Y,MON,월\n"
    )
    (tmp_path / "b.csv").write_text(
        "일자,공휴일여부,영어요일명,한국어요일명\n2024-01-01,Y,MON,월\n"
    )

    with pytest.raises(ValueError, match="여러 개"):
        build_holiday_calendar(raw_dir=tmp_path)


def test_build_holiday_calendar_raises_when_no_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        build_holiday_calendar(raw_dir=tmp_path)
