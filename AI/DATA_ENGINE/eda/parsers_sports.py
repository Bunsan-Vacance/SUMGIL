"""KBO·K리그·KBO 관중수 백필 산출물(JSON, `collect/{kbo,kleague}_schedule_backfill.py`·
`collect/kbo_crowd_backfill.py`가 이미 레코드 단위로 파싱해 저장한 것)
→ data/EXTERNAL/events/interim/*.parquet로 합친다.

원본 백필 스크립트가 이미 정규화까지 끝낸 레코드를 저장하므로 여기서는 JSON 파일을 그러모아
하나로 합치는 것 말고는 할 일이 없다 — 필드 의미·결측 처리는 각 백필 스크립트 docstring
참고(KBO 일정에는 관중수 없음·취소 경기는 점수 None, KBO 관중수는 잠실·고척·문학·수원
4구장뿐 등).

실행:
    cd AI
    python -m DATA_ENGINE.eda.parsers_sports
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

AI_ROOT = Path(__file__).resolve().parents[2]
EVENTS_DIR = AI_ROOT / "data" / "EXTERNAL" / "events"


def _load_monthly_json_dir(raw_dir: Path, glob_pattern: str) -> pd.DataFrame:
    json_paths = sorted(p for p in raw_dir.glob(glob_pattern) if not p.name.startswith("_"))
    if not json_paths:
        raise FileNotFoundError(f"{raw_dir} 에서 {glob_pattern} 백필 산출물을 찾지 못했습니다.")

    records = []
    for path in json_paths:
        records.extend(json.loads(path.read_text(encoding="utf-8")))
    return pd.DataFrame(records)


def build_kbo_games() -> pd.DataFrame:
    return _load_monthly_json_dir(EVENTS_DIR / "raw" / "kbo", "kbo_*.json")


def build_kleague_games() -> pd.DataFrame:
    return _load_monthly_json_dir(EVENTS_DIR / "raw" / "kleague", "kleague_*.json")


def build_kbo_crowd() -> pd.DataFrame:
    return _load_monthly_json_dir(EVENTS_DIR / "raw" / "kbo_crowd", "kbo_crowd_*.json")


def save_interim(df: pd.DataFrame, filename: str) -> Path:
    interim_dir = EVENTS_DIR / "interim"
    interim_dir.mkdir(parents=True, exist_ok=True)
    out_path = interim_dir / filename
    df.to_parquet(out_path, index=False)
    return out_path


def main() -> None:
    kbo = build_kbo_games()
    kbo_path = save_interim(kbo, "kbo_games.parquet")
    kbo_cancelled = int((kbo["status"] != "-").sum())
    print(f"저장 완료: {kbo_path} ({len(kbo):,}경기, 취소/특이상태 {kbo_cancelled}건)")

    kleague = build_kleague_games()
    kleague_path = save_interim(kleague, "kleague_games.parquet")
    print(f"저장 완료: {kleague_path} ({len(kleague):,}경기)")

    kbo_crowd = build_kbo_crowd()
    kbo_crowd_path = save_interim(kbo_crowd, "kbo_crowd.parquet")
    print(
        f"저장 완료: {kbo_crowd_path} ({len(kbo_crowd):,}경기, "
        f"구장 {sorted(kbo_crowd['stadium'].unique())})"
    )


if __name__ == "__main__":
    main()
