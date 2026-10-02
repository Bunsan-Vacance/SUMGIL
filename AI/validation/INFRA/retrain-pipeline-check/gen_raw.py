"""합성 raw 생성기 — `getStnPsgr` 원문(`dt=YYYY-MM-DD/getStnPsgr.parquet`)과 같은 스키마·규모.

실데이터가 로컬에 없어 만든 **합성 데이터**다(값은 시드 고정 난수). 스키마는
`DATA_ENGINE/collect/subway_ridership_daily.py`의 `RAW_COLUMNS`(값 형식은 전부 문자열),
규모는 그 docstring의 "하루 6.3~6.9만 행"을 따른다: 역·호선 조합 `--stations`개(기본 700) x
`pasngHr` "0"~"23" x 카드구분 2 x 사용자구분 2 = 하루 약 6.7만 행.

기본은 2024-01-01부터 1000일(~2026-09-26)이라 2026년 파티션을 포함한다.

실행:
    cd AI
    python validation/INFRA/retrain-pipeline-check/gen_raw.py --days 1000
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
AI_ROOT = HERE.parents[2]
sys.path.insert(0, str(AI_ROOT))

from DATA_ENGINE.collect.subway_ridership_daily import RAW_COLUMNS  # noqa: E402

SCRATCH_ROOT = Path(
    r"C:\Users\SSAFY\AppData\Local\Temp\claude\C--Users-SSAFY-workspace-SUMGIL"
    r"\2374304a-6890-4029-8e97-88bd84662f9a\scratchpad\retrain-bench"
)
DEFAULT_OUT = SCRATCH_ROOT / "master"
RAW_FILE_NAME = "getStnPsgr.parquet"
OTHER_LINES = [
    "경의중앙선",
    "수인분당선",
    "신분당선",
    "공항철도",
    "경춘선",
    "우이신설선",
    "김포골드라인",
]


def make_stations(n: int, seed: int) -> pd.DataFrame:
    """1~9호선 + 기타 노선에 역을 나눠 배정한다. stnCd·stnNo는 유일."""
    rng = np.random.default_rng(seed)
    lines = [f"{i}호선" for i in range(1, 10)] + OTHER_LINES
    weights = np.array([8, 8, 7, 7, 8, 8, 7, 3, 3] + [2] * len(OTHER_LINES), dtype=float)
    line_idx = rng.choice(len(lines), size=n, p=weights / weights.sum())
    codes = rng.permutation(np.arange(100, 100 + n * 2))[:n]
    return pd.DataFrame(
        {
            "lineNm": [lines[i] for i in line_idx],
            "stnCd": [str(int(c)) for c in codes],
            "stnNo": [f"{int(c):04d}" for c in codes],
            "stnNm": [f"합성역{i:04d}" for i in range(n)],
            "base": rng.integers(20, 400, size=n),
        }
    )


def make_day(stations: pd.DataFrame, day: date, rng: np.random.Generator) -> pd.DataFrame:
    n_st = len(stations)
    hours = np.arange(24)
    cards = [("1", "일반"), ("2", "어린이")]
    users = [("1", "일반"), ("2", "우대")]
    combos = [(c, u) for c in cards for u in users]
    n_rows = n_st * 24 * len(combos)
    st_idx = np.repeat(np.arange(n_st), 24 * len(combos))
    hr = np.tile(np.repeat(hours, len(combos)), n_st)
    combo_idx = np.tile(np.arange(len(combos)), n_st * 24)
    base = stations["base"].to_numpy()[st_idx]
    ride = rng.poisson(base * (1 + (hr % 12)) / 4.0).astype(np.int64)
    gff = rng.poisson(base * (1 + ((hr + 6) % 12)) / 4.0).astype(np.int64)
    ymd = day.strftime("%Y%m%d")
    out = pd.DataFrame(
        {
            "pasngDe": ymd,
            "pasngHr": hr.astype(str),
            "lineNm": stations["lineNm"].to_numpy()[st_idx],
            "stnCd": stations["stnCd"].to_numpy()[st_idx],
            "stnNo": stations["stnNo"].to_numpy()[st_idx],
            "stnNm": stations["stnNm"].to_numpy()[st_idx],
            "trnscdSeCd": [combos[i][0][0] for i in combo_idx],
            "trnscdSeCdNm": [combos[i][0][1] for i in combo_idx],
            "trnscdUserSeCd": [combos[i][1][0] for i in combo_idx],
            "trnscdUserSeCdNm": [combos[i][1][1] for i in combo_idx],
            "rideNope": ride.astype(str),
            "gffNope": gff.astype(str),
            "crtrYmd": ymd,
        }
    )
    assert len(out) == n_rows
    return out[RAW_COLUMNS]


def generate(out_root: Path, days: int, start: date, stations: int, seed: int) -> int:
    st = make_stations(stations, seed)
    written = 0
    for i in range(days):
        d = start + timedelta(days=i)
        path = out_root / f"dt={d.isoformat()}" / RAW_FILE_NAME
        if path.exists():
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        rng = np.random.default_rng(seed * 1_000_003 + d.toordinal())
        make_day(st, d, rng).to_parquet(path, index=False)
        written += 1
    return written


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--out-root", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--days", type=int, default=1000)
    ap.add_argument("--start", type=date.fromisoformat, default=date(2024, 1, 1))
    ap.add_argument("--stations", type=int, default=700)
    ap.add_argument("--seed", type=int, default=20261002)
    a = ap.parse_args(argv)
    n = generate(a.out_root, a.days, a.start, a.stations, a.seed)
    print(f"[gen_raw] {a.out_root}: 새로 쓴 파티션 {n}개 (요청 {a.days}일, 시작 {a.start})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
