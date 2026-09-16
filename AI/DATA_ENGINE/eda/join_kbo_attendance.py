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

**수도권 범위 축소**: 서울 지하철 혼잡도와 무관한 지방 구장(사직·대구·광주·대전·창원·포항
등) 경기는 "어느 팀이 홈/원정이냐"가 아니라 "경기가 물리적으로 어디서 열리느냐"(구장) 기준
으로 걸러낸다 — 관중수를 수집한 4구장(잠실·고척·문학·수원) 기준과 동일하다. 전국 원본
(`kbo_games.parquet`)은 그대로 두고 `kbo_games_seoul_metro.parquet`로 별도 저장한다 —
원본을 지우면 스코프가 넓어질 때 재수집해야 하니 발췌만 한다.

**더블헤더 제외(선택적 산출물)**: 더블헤더 경기는 티켓이 경기별로 독립이어도 실제로는
1경기 관람 후 안 나가고 2경기까지 이어보는 인원이 섞여 있어, "관중수 = 그 시간대 유출입"
가정이 두 경기 모두에서 깨진다. 이걸 정확히 보정하려면 구장 인근 생활인구(250m 격자)
실측 대조가 필요한데 아직 구장↔격자 매핑이 없다(README 미해결 사항 참고). 비중이 작아서
(11일/약 350~400 게임데이, 약 3%) 정밀 보정 없이 통째로 빼는 쪽을 택했다 —
`kbo_games_seoul_metro_no_doubleheader.parquet`로 별도 저장하고, 더블헤더를 포함한
`kbo_games_seoul_metro.parquet`도 그대로 남겨둔다(나중에 생활인구 검증이 되면 되살릴 수
있게).

실행:
    cd AI
    python -m DATA_ENGINE.eda.join_kbo_attendance
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from DATA_ENGINE.collect.kbo_crowd_backfill import STADIUMS
from DATA_ENGINE.eda.parsers_sports import build_kbo_crowd, build_kbo_games

AI_ROOT = Path(__file__).resolve().parents[2]
PROCESSED_DIR = AI_ROOT / "data" / "EXTERNAL" / "events" / "processed"

# 관중수를 수집한 구장과 동일한 기준 — kbo_crowd_backfill.STADIUMS를 그대로 재사용해
# 두 목록이 따로 놀지 않게 한다.
SEOUL_METRO_STADIUMS = set(STADIUMS.values())

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


def filter_seoul_metro_games(merged: pd.DataFrame) -> pd.DataFrame:
    """전국 일정 중 서울/경기/인천 4구장(관중수 수집 대상과 동일) 경기만 남긴다.

    팀(홈/원정)이 아니라 구장으로 거른다 — 지방 팀이 잠실 등으로 원정 온 경기는 서울
    교통량과 관련 있고, 반대로 서울권 팀이 지방으로 원정 간 경기는 무관하기 때문이다.
    """
    return merged[merged["stadium"].isin(SEOUL_METRO_STADIUMS)].reset_index(drop=True)


def identify_doubleheader_keys(crowd: pd.DataFrame) -> pd.MultiIndex:
    """더블헤더가 열린 (date, stadium) 조합을 식별한다.

    팀 조합이 아니라 (date, stadium)만 본다 — 같은 구장에서 하루에 두 팀이 다른 대진으로
    두 번 뛰는 일은 없으니, 그 구장에 그 날 경기가 2건 이상이면 더블헤더로 본다.
    """
    counts = crowd.groupby(["date", "stadium"]).size()
    return counts[counts > 1].index


def drop_doubleheader_days(games: pd.DataFrame, doubleheader_keys: pd.MultiIndex) -> pd.DataFrame:
    """더블헤더가 열린 날은 그 구장의 그 날짜 경기를 두 경기 다 제외한다.

    한쪽 경기만 남기면 "그날 게임 있었음/없었음" 신호가 반쪽짜리로 왜곡되니 날짜 전체를
    뺀다 — README 미해결 사항 참고(생활인구 검증 전까지 정밀 보정 대신 택한 절충안).
    """
    key = pd.MultiIndex.from_frame(games[["date", "stadium"]])
    return games[~key.isin(doubleheader_keys)].reset_index(drop=True)


def save_parquet(df: pd.DataFrame, filename: str) -> Path:
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    out_path = PROCESSED_DIR / filename
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
    out_path = save_parquet(merged, "kbo_games_with_attendance.parquet")
    matched = int(merged["attendance"].notna().sum())
    print(f"저장 완료: {out_path} ({len(merged):,}경기, 관중수 매칭 {matched:,}건)")
    print(report_team_order(merged))

    seoul_metro = filter_seoul_metro_games(merged)
    seoul_metro_path = save_parquet(seoul_metro, "kbo_games_seoul_metro.parquet")
    seoul_metro_matched = int(seoul_metro["attendance"].notna().sum())
    print(
        f"저장 완료: {seoul_metro_path} ({len(seoul_metro):,}경기, "
        f"관중수 매칭 {seoul_metro_matched:,}건, "
        f"전국 대비 {len(seoul_metro) / len(merged):.1%})"
    )

    dh_keys = identify_doubleheader_keys(crowd)
    no_dh = drop_doubleheader_days(seoul_metro, dh_keys)
    no_dh_path = save_parquet(no_dh, "kbo_games_seoul_metro_no_doubleheader.parquet")
    dropped = len(seoul_metro) - len(no_dh)
    print(
        f"저장 완료: {no_dh_path} ({len(no_dh):,}경기, "
        f"더블헤더 {len(dh_keys)}일치 {dropped}경기 제외)"
    )


if __name__ == "__main__":
    main()
