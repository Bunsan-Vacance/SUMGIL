"""K리그 일정(`kleague_games.parquet`, 전국 대상)을 서울/경기/인천 수도권 구장 기준으로
발췌해 data/EXTERNAL/events/processed/kleague_games_seoul_metro.parquet를 만든다.

KBO(`join_kbo_attendance.py`)와 같은 논리 — "어느 팀이 홈/원정이냐"가 아니라 "경기가
물리적으로 어디서 열리느냐"(구장) 기준으로 거른다. K리그는 관중수가 일정 응답에 이미
포함돼 있어(`audienceQty` → `attendance`) KBO처럼 별도 관중수 스크래핑·조인이 필요 없다.

대상 구장 7곳(2026-09-09 사용자 확인): 서울 월드컵(FC서울), 목동 종합(서울이랜드),
수원 월드컵(수원삼성), 수원 종합(수원FC), 안양 종합(안양FC), 부천 종합(부천FC1995),
인천 전용(인천유나이티드). K리그1·K리그2 구단 모두 포함.

실행:
    cd AI
    python -m DATA_ENGINE.eda.filter_kleague_seoul_metro
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from DATA_ENGINE.eda.parsers_sports import build_kleague_games

AI_ROOT = Path(__file__).resolve().parents[2]
PROCESSED_DIR = AI_ROOT / "data" / "EXTERNAL" / "events" / "processed"

SEOUL_METRO_STADIUMS = {
    "서울 월드컵",
    "목동 종합",
    "수원 월드컵",
    "수원 종합",
    "안양 종합",
    "부천 종합",
    "인천 전용",
}


def filter_seoul_metro_games(games: pd.DataFrame) -> pd.DataFrame:
    return games[games["stadium"].isin(SEOUL_METRO_STADIUMS)].reset_index(drop=True)


def save_processed(df: pd.DataFrame) -> Path:
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    out_path = PROCESSED_DIR / "kleague_games_seoul_metro.parquet"
    df.to_parquet(out_path, index=False)
    return out_path


def main() -> None:
    games = build_kleague_games()
    filtered = filter_seoul_metro_games(games)
    out_path = save_processed(filtered)
    matched = int(filtered["attendance"].notna().sum())
    print(
        f"저장 완료: {out_path} ({len(filtered):,}경기, "
        f"전국 대비 {len(filtered) / len(games):.1%}, 관중수 있음 {matched:,}건)"
    )


if __name__ == "__main__":
    main()
