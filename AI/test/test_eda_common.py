from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd

from DATA_ENGINE.collect.common import save_partitioned_parquet


def test_save_partitioned_parquet_layout(tmp_path):
    df = pd.DataFrame({"a": [1, 2]})
    collected_at = datetime(2026, 3, 5, 14, 30, tzinfo=ZoneInfo("Asia/Seoul"))

    out_path = save_partitioned_parquet(df, tmp_path, collected_at)

    assert out_path.parent.parent.name == "dt=2026-03-05"
    assert out_path.parent.name == "hh=14"
    assert out_path.exists()
    assert pd.read_parquet(out_path).equals(df)
