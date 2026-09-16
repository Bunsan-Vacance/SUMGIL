import pandas as pd

from DATA_ENGINE.eda.parsers_weather import duplicate_datetime_inventory


def test_duplicate_datetime_inventory_flags_overlap_without_dropping():
    df = pd.DataFrame(
        {
            "datetime": pd.to_datetime(
                ["2024-01-01 00:00", "2024-01-01 00:00", "2024-01-01 01:00"]
            ),
            "temp_c": [1.0, 1.2, 2.0],
        }
    )

    result = duplicate_datetime_inventory(df)

    assert len(result) == 2
    assert set(result["temp_c"]) == {1.0, 1.2}


def test_duplicate_datetime_inventory_empty_when_no_overlap():
    df = pd.DataFrame(
        {"datetime": pd.to_datetime(["2024-01-01 00:00", "2024-01-01 01:00"]), "temp_c": [1.0, 2.0]}
    )

    assert duplicate_datetime_inventory(df).empty
