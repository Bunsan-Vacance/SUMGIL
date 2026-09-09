"""KBO 일정(`kbo_games.parquet`, 전국 대상)과 관중수(`kbo_crowd.parquet`, 잠실·고척·문학·
수원 4구장만)를 조인해 data/EXTERNAL/events/processed/kbo_games_with_attendance.parquet를
만든다.

**조인 키**: (date, stadium, 팀 조합). 일정 쪽 `team_left`/`team_right`는 원정/홈 중 무엇이
왼쪽인지 확인되지 않은 상태였는데(`kbo_schedule_backfill.py` 참고), 관중수 쪽은
`home_team`/`away_team`이 명확하다 — 조인 후 `team_left`가 어느 쪽과 일치하는지 세어보면
그 순서를 검증할 수 있다(`main()`이 출력).

**더블헤더 문제**: 같은 날 같은 구장에서 같은 두 팀이 두 번 붙는 경우(연장 서스펜디드 후
재경기 등) date+stadium+팀조합만으로는 그 날의 여러 경기를 구별하지 못한다. 두 원천 모두
원래 응답이 시간순으로 왔다는 점을 이용해 그룹 내 등장 순서(0번째, 1번째...)로 짝짓는다.

**관중수는 4구장뿐이다** — 그 4곳 경기만 채워지고 나머지(원정 경기 등)는 `attendance`가
NaN으로 남는다. 취소된 경기(일정에는 있지만 실제로 안 열림)는 관중수 원천에 애초에
없으므로 자연스럽게 NaN으로 빠진다 — 채우지 않는다.

실행:
    cd AI
    python -m DATA_ENGINE.eda.join_kbo_attendance
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from DATA_ENGINE.eda.parsers_sports import build_kbo_crowd, build_kbo_games

AI_ROOT = Path(__file__).resolve().parents[2]
PROCESSED_DIR = AI_ROOT / "data" / "EXTERNAL" / "events" / "processed"

_KEY_COLS = ["date", "stadium", "team_pair"]


def _team_pair(left: pd.Series, right: pd.Series) -> list[tuple[str, str]]:
    """팀 조합을 순서 무관하게 비교하도록 정렬된 튜플로 만든다."""
    return [tuple(sorted((a, b))) for a, b in zip(left, right)]


def _with_group_sequence(df: pd.DataFrame) -> pd.DataFrame:
    """같은 (date, stadium, team_pair) 안에서 몇 번째로 등장했는지(더블헤더 구분용)."""
    df = df.copy()
    df["game_seq"] = df.groupby(_KEY_COLS).cumcount()
    return df


def duplicate_group_inventory(crowd: pd.DataFrame) -> pd.DataFrame:
    """관중수 쪽에서 같은 (date, stadium, team_pair)가 2번을 초과해 등장하는 그룹을
    나열한다 — 3연전 이상의 더블헤더는 사실상 없어야 정상이라 있으면 확인이 필요하다."""
    crowd = crowd.copy()
    crowd["team_pair"] = _team_pair(crowd["home_team"], crowd["away_team"])
    counts = crowd.groupby(_KEY_COLS).size()
    suspicious = counts[counts > 2]
    return suspicious.reset_index(name="count")


def join_kbo_attendance(games: pd.DataFrame, crowd: pd.DataFrame) -> pd.DataFrame:
    games = games.copy()
    crowd = crowd.copy()

    games["team_pair"] = _team_pair(games["team_left"], games["team_right"])
    crowd["team_pair"] = _team_pair(crowd["home_team"], crowd["away_team"])

    games = _with_group_sequence(games)
    crowd = _with_group_sequence(crowd)

    merged = games.merge(
        crowd[[*_KEY_COLS, "game_seq", "home_team", "away_team", "attendance"]],
        on=[*_KEY_COLS, "game_seq"],
        how="left",
    )
    return merged.drop(columns="team_pair")


def report_team_order(merged: pd.DataFrame) -> str:
    """team_left가 home/away 중 어느 쪽과 일치하는지 세어 알려준다(재라벨링은 안 함)."""
    matched = merged.dropna(subset=["home_team"])
    left_is_home = int((matched["team_left"] == matched["home_team"]).sum())
    left_is_away = int((matched["team_left"] == matched["away_team"]).sum())
    return f"team_left==home_team: {left_is_home}건, team_left==away_team: {left_is_away}건"


def save_processed(df: pd.DataFrame) -> Path:
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    out_path = PROCESSED_DIR / "kbo_games_with_attendance.parquet"
    df.to_parquet(out_path, index=False)
    return out_path


def main() -> None:
    games = build_kbo_games()
    crowd = build_kbo_crowd()

    dup_groups = duplicate_group_inventory(crowd)
    if len(dup_groups):
        print(f"⚠️ 관중수에서 2경기 초과 그룹 {len(dup_groups)}건 발견 — 확인 필요:")
        print(dup_groups.to_string(index=False))

    merged = join_kbo_attendance(games, crowd)
    out_path = save_processed(merged)

    matched = int(merged["attendance"].notna().sum())
    print(f"저장 완료: {out_path} ({len(merged):,}경기, 관중수 매칭 {matched:,}건)")
    print(report_team_order(merged))


if __name__ == "__main__":
    main()
