from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from DATA_ENGINE.collect.common import save_latest_parquet, save_partitioned_parquet


def test_save_partitioned_parquet_layout(tmp_path):
    df = pd.DataFrame({"a": [1, 2]})
    collected_at = datetime(2026, 3, 5, 14, 30, tzinfo=ZoneInfo("Asia/Seoul"))

    out_path = save_partitioned_parquet(df, tmp_path, collected_at)

    assert out_path.parent.parent.name == "dt=2026-03-05"
    assert out_path.parent.name == "hh=14"
    assert out_path.exists()
    assert pd.read_parquet(out_path).equals(df)


def test_save_latest_parquet_creates_parent_and_replaces_existing(tmp_path):
    latest_path = tmp_path / "nested" / "latest.parquet"
    old_df = pd.DataFrame({"a": [1]})
    new_df = pd.DataFrame({"a": [2, 3]})

    save_latest_parquet(old_df, latest_path)
    out_path = save_latest_parquet(new_df, latest_path)

    assert out_path == latest_path
    assert latest_path.exists()
    assert pd.read_parquet(latest_path).equals(new_df)


def test_save_latest_parquet_removes_temp_file_on_failure(tmp_path, monkeypatch):
    latest_path = tmp_path / "latest.parquet"

    def fail_to_parquet(self, path, *args, **kwargs):
        path.write_text("partial", encoding="utf-8")
        raise RuntimeError("boom")

    monkeypatch.setattr(pd.DataFrame, "to_parquet", fail_to_parquet)

    with pytest.raises(RuntimeError, match="boom"):
        save_latest_parquet(pd.DataFrame({"a": [1]}), latest_path)

    assert not latest_path.exists()
    assert not list(tmp_path.glob(".latest.parquet.*.tmp"))
