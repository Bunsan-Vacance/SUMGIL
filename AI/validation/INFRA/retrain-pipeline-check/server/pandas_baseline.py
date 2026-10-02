"""pandas 기준선 — raw 파티션 전부를 `to_long`(수집기와 같은 함수)으로 집계해 롱 parquet으로 쓴다.

Spark 잡의 `--verify-against` 입력이자 처리 시간·메모리 비교의 pandas 쪽 수치다.
서버의 `crowd_recent_ridership_long.parquet`은 수집기가 날마다 merge한 누적본이라 "한 번에 전량 재집계"
비용을 재려면 이 스크립트처럼 다시 돌려야 한다.

사용:
    cd AI && python validation/INFRA/retrain-pipeline-check/server/pandas_baseline.py \
        data/CROWD/raw/ridership_daily <out.parquet>
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pandas as pd

from DATA_ENGINE.collect.subway_ridership_daily import LONG_COLUMNS, to_long


def main() -> int:
    root, out = Path(sys.argv[1]), Path(sys.argv[2])
    t0 = time.perf_counter()
    frames = []
    for part in sorted(root.glob("dt=*")):
        for f in part.glob("*.parquet"):
            frames.append(to_long(pd.read_parquet(f)))
    long = pd.concat(frames, ignore_index=True).sort_values(LONG_COLUMNS[:5]).reset_index(drop=True)
    out.parent.mkdir(parents=True, exist_ok=True)
    long.to_parquet(out, index=False)
    print(
        f"[pandas_baseline] partitions={len(frames)} rows={len(long)} sec={time.perf_counter() - t0:.2f}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
