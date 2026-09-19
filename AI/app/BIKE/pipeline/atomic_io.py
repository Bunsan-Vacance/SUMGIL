"""로컬 parquet 파일을 원자적으로 교체하는 작은 유틸.

`DATA_ENGINE.collect.common.save_latest_parquet()`와 동일한 패턴(tmp 파일 작성 후
`os.replace()`)이지만, `app/`은 `DATA_ENGINE/`을 import하지 않는다는 단방향 규칙
(`AI/CLAUDE.md`)이 있어 여기 별도로 작게 둔다.
"""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd


def atomic_write_parquet(df: pd.DataFrame, path: Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        df.to_parquet(tmp_path, index=False)
        os.replace(tmp_path, path)
    finally:
        if tmp_path.exists():
            tmp_path.unlink()
    return path
