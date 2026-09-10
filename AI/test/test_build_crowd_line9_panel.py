import pandas as pd

from DATA_ENGINE.eda.build_crowd_line9_panel import (
    reshape_to_panel_slots,
    verify_mass_conservation,
)


def _hourly_frame(
    hours: list[str], passengers: list[int], date: str = "2025-01-02"
) -> pd.DataFrame:
    n = len(hours)
    return pd.DataFrame(
        {
            "date": pd.to_datetime([date] * n),
            "station_no": [4126] * n,
            "direction": ["alighting"] * n,
            "time_slot": hours,
            "passengers": passengers,
        }
    )


def test_reshape_moves_late_night_hours_to_previous_day_24_bucket():
    """00-01~04-05는 전날 날짜의 "24~" 버킷으로 합산 이동해야 한다."""
    df = _hourly_frame(["00-01", "01-02", "02-03", "03-04", "04-05"], [4, 0, 0, 0, 0])

    result = reshape_to_panel_slots(df)

    assert len(result) == 1
    row = result.iloc[0]
    assert row["date"] == pd.Timestamp("2025-01-01")
    assert row["time_slot"] == "24~"
    assert row["passengers"] == 4


def test_reshape_renames_05_06_to_tilde_06_same_day():
    df = _hourly_frame(["05-06"], [12])

    result = reshape_to_panel_slots(df)

    assert len(result) == 1
    assert result.iloc[0]["date"] == pd.Timestamp("2025-01-02")
    assert result.iloc[0]["time_slot"] == "~06"


def test_reshape_keeps_daytime_hours_unchanged():
    df = _hourly_frame(["06-07", "12-13", "23-24"], [10, 20, 5])

    result = reshape_to_panel_slots(df).sort_values("time_slot")

    assert list(result["time_slot"]) == ["06-07", "12-13", "23-24"]
    assert (result["date"] == pd.Timestamp("2025-01-02")).all()
    assert list(result["passengers"]) == [10, 20, 5]


def test_reshape_preserves_total_mass_across_the_split():
    """심야 5개 슬롯이 하나로 합쳐지고 날짜가 이동해도 총합은 그대로여야 한다."""
    df = _hourly_frame(
        ["00-01", "01-02", "02-03", "03-04", "04-05", "05-06", "06-07"],
        [4, 0, 0, 0, 1, 12, 93],
    )

    result = reshape_to_panel_slots(df)

    assert result["passengers"].sum() == df["passengers"].sum() == 110


def test_verify_mass_conservation_passes_when_totals_match():
    before = _hourly_frame(["00-01", "05-06"], [4, 12])
    after = reshape_to_panel_slots(before)

    assert verify_mass_conservation(before, after).empty


def test_verify_mass_conservation_flags_a_real_mismatch():
    before = _hourly_frame(["05-06"], [12])
    after = before.copy()
    after["passengers"] = 999  # 인위적으로 틀린 값을 만들어 탐지되는지 확인

    result = verify_mass_conservation(before, after)

    assert len(result) == 1
    assert result.iloc[0]["before"] == 12
    assert result.iloc[0]["after"] == 999
