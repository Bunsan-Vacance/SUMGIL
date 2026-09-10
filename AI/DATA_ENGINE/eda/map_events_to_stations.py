"""경기·축제 이벤트를 인근 지하철역에 연결한다.

`crowd_panel_2024_2025.parquet`은 지금 승하차·달력·기상까지만 붙어 있다. 이벤트(KBO·K리그
경기, 축제)는 **날짜뿐 아니라 장소**가 있어서 "그 날 서울 어딘가에서 경기가 있었다"가 아니라
"이 역 근처에서 경기가 있었다"로 붙여야 의미가 있다 — 잠실 경기가 신촌 혼잡도를 올리지는
않기 때문이다. 그래서 좌표 거리로 역을 먼저 찾고, 그 역에만 이벤트를 붙인다.

**좌표 출처가 둘로 갈린다.** 축제는 원본(전국 문화축제 표준데이터)에 lon/lat이 들어 있고,
경기장은 일정·관중수 어느 원천에도 좌표가 없어 `conf/venue_coordinates.yaml`에 수기로
넣었다(근사값 — 그 파일의 경고 참고).

**커버리지 한계가 크다.** 승하차 데이터가 서울교통공사 1~8호선 273역뿐이라, 경기장 인근
역이 코레일·인천교통공사 소속이면 붙일 데가 없다. 어느 경기장이 실제로 연결됐는지는
`main()`이 표로 출력한다 — 연결 안 된 경기장의 경기는 이 패널에서 신호가 되지 못한다.

실행:
    cd AI
    python -m DATA_ENGINE.eda.map_events_to_stations
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from DATA_ENGINE.eda.parsers_festival import SPIKE_MAX_DAYS

AI_ROOT = Path(__file__).resolve().parents[2]
CONF_DIR = AI_ROOT / "DATA_ENGINE" / "conf"
CROWD_PROCESSED = AI_ROOT / "data" / "CROWD" / "processed"
EVENTS_PROCESSED = AI_ROOT / "data" / "EXTERNAL" / "events" / "processed"
EVENTS_INTERIM = AI_ROOT / "data" / "EXTERNAL" / "events" / "interim"
STATION_RAW = AI_ROOT / "data" / "EXTERNAL" / "station" / "raw"

PANEL_NAME = "crowd_panel_2024_2025.parquet"
OUTPUT_NAME = "crowd_station_events_2024_2025.parquet"

EARTH_RADIUS_KM = 6371.0


def haversine_km(
    lat1: np.ndarray, lon1: np.ndarray, lat2: np.ndarray, lon2: np.ndarray
) -> np.ndarray:
    """두 좌표 사이의 대권 거리(km). 브로드캐스팅으로 (n, m) 거리 행렬을 만든다."""
    lat1, lon1, lat2, lon2 = map(np.radians, (lat1, lon1, lat2, lon2))
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = np.sin(dlat / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_KM * np.arcsin(np.sqrt(a))


def load_venues() -> tuple[pd.DataFrame, float]:
    with (CONF_DIR / "venue_coordinates.yaml").open(encoding="utf-8") as f:
        conf = yaml.safe_load(f)
    rows = [
        {"sport": sport, "stadium": name, "lat": c["lat"], "lon": c["lon"]}
        for sport in ("kbo", "kleague")
        for name, c in conf[sport].items()
    ]
    return pd.DataFrame(rows), float(conf["radius_km"])


def load_panel_stations() -> pd.DataFrame:
    """패널에 실제로 있는 역과 그 좌표."""
    panel = pd.read_parquet(
        CROWD_PROCESSED / PANEL_NAME, columns=["station_no", "station_name", "line", "lat", "lon"]
    )
    return panel.drop_duplicates("station_no").dropna(subset=["lat", "lon"]).reset_index(drop=True)


def nearest_stations(
    points: pd.DataFrame, stations: pd.DataFrame, radius_km: float
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """각 지점에서 반경 안에 있는 역을 모두 찾고, 최근접 역 요약도 같이 낸다.

    반환값은 `(반경 내 전체 쌍, 지점별 최근접 역 1개)`. 최근접 요약은 좌표가 맞는지
    눈으로 확인하기 위한 것이라 반경 밖이어도 항상 한 줄 나온다.
    """
    dist = haversine_km(
        points["lat"].to_numpy()[:, None],
        points["lon"].to_numpy()[:, None],
        stations["lat"].to_numpy()[None, :],
        stations["lon"].to_numpy()[None, :],
    )

    pi, si = np.nonzero(dist <= radius_km)
    within = pd.concat(
        [
            points.iloc[pi].reset_index(drop=True),
            stations.iloc[si][["station_no", "station_name", "line"]].reset_index(drop=True),
        ],
        axis=1,
    )
    within["distance_km"] = dist[pi, si].round(3)

    best = dist.argmin(axis=1)
    summary = points.copy().reset_index(drop=True)
    summary["최근접역"] = stations.iloc[best]["station_name"].to_numpy()
    summary["호선"] = stations.iloc[best]["line"].to_numpy()
    summary["거리_km"] = dist[np.arange(len(points)), best].round(2)
    summary["반경내"] = summary["거리_km"] <= radius_km
    return within, summary


def load_games() -> pd.DataFrame:
    """KBO·K리그 경기를 (date, stadium, attendance) 한 형태로 모은다."""
    kbo = pd.read_parquet(EVENTS_PROCESSED / "kbo_games_seoul_metro_no_doubleheader.parquet")
    kbo = kbo[["date", "stadium", "attendance"]].assign(sport="kbo")
    kleague = pd.read_parquet(EVENTS_PROCESSED / "kleague_games_seoul_metro.parquet")
    kleague = kleague[["date", "stadium", "attendance"]].assign(sport="kleague")
    games = pd.concat([kbo, kleague], ignore_index=True)
    games["date"] = pd.to_datetime(games["date"])
    return games


def load_festivals(start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    """축제를 하루 한 행으로 편다 — 기간 축제는 열린 날마다 한 행이 된다.

    `duration_days`는 **패널 구간으로 자르기 전 원래 개최 기간**을 그대로 들고 온다. 잘린
    기간을 다시 계산하면 2024-01-01 이전에 시작한 장기 전시가 "짧은 축제"로 뒤바뀐다.
    """
    fest = pd.read_parquet(EVENTS_INTERIM / "festival_capital.parquet")
    fest = fest.dropna(subset=["lat", "lon"])
    fest = fest[(fest["end_date"] >= start) & (fest["start_date"] <= end)].copy()
    fest["start_date"] = fest["start_date"].clip(lower=start)
    fest["end_date"] = fest["end_date"].clip(upper=end)
    fest["date"] = [
        pd.date_range(s, e, freq="D") for s, e in zip(fest["start_date"], fest["end_date"])
    ]
    cols = ["festival_id", "name", "lat", "lon", "date", "duration_days", "sponsor"]
    return fest.explode("date")[cols]


def aggregate_festival_rows(fest_events: pd.DataFrame) -> pd.DataFrame:
    """축제-역-일 행을 역·날짜별로 집계한다.

    축제는 관중수가 원천에 없어(`parsers_festival.py` 참고) 개수 하나로만 잡혀 있었는데, 그
    개수의 83.6%가 개최 기간 31일 이상인 상설·기간 행사에서 나와 정작 인원이 몰리는 단기
    축제의 신호를 덮고 있었다. 그래서 개수를 기간 기준으로 쪼개고, 트리가 경계를 직접
    고를 수 있도록 연속값(최단 기간)도 같이 낸다.
    """
    flagged = fest_events.assign(
        _spike=fest_events["duration_days"].between(1, SPIKE_MAX_DAYS),
        _sponsored=fest_events["sponsor"].notna(),
    )
    rows = (
        flagged.groupby(["date", "station_no"])
        .agg(
            festival_count=("festival_id", "nunique"),
            festival_short_count=("_spike", "sum"),
            festival_min_duration_days=("duration_days", "min"),
            festival_sponsored_count=("_sponsored", "sum"),
        )
        .reset_index()
    )
    # 장기 행사 수는 전체 − 단기로 유도한다 — 두 열을 따로 세면 합이 festival_count와
    # 어긋날 수 있다.
    rows["festival_long_count"] = rows["festival_count"] - rows["festival_short_count"]
    return rows


def build_station_events(
    panel_range: tuple[pd.Timestamp, pd.Timestamp],
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    stations = load_panel_stations()
    venues, radius_km = load_venues()

    venue_links, venue_summary = nearest_stations(venues, stations, radius_km)
    games = load_games()
    game_events = games.merge(venue_links, on="stadium", how="inner", suffixes=("", "_venue"))
    # 관중수가 없는 경기(우천취소 등)를 합계에서 0으로 흘려보내면 "관중 0명"과 구별이
    # 안 된다. 결측 건수를 따로 세어 남기고, 그런 날의 합계는 NaN으로 둔다.
    game_rows = (
        game_events.groupby(["date", "station_no"])
        .agg(
            game_count=("stadium", "size"),
            game_attendance=("attendance", lambda s: s.sum() if s.notna().all() else np.nan),
            game_attendance_missing=("attendance", lambda s: int(s.isna().sum())),
        )
        .reset_index()
    )

    festivals = load_festivals(*panel_range)
    fest_links, _ = nearest_stations(
        festivals.drop_duplicates("festival_id")[["festival_id", "lat", "lon"]],
        stations,
        radius_km,
    )
    fest_events = festivals.merge(
        fest_links[["festival_id", "station_no"]], on="festival_id", how="inner"
    )
    fest_rows = aggregate_festival_rows(fest_events)

    events = game_rows.merge(fest_rows, on=["date", "station_no"], how="outer")
    # 건수는 "이벤트가 없었다"를 0으로 두는 게 맞다. 관중수는 채우지 않는다 —
    # 경기 자체가 없는 날의 NaN과 관중수만 없는 날의 NaN을 game_count로 구별한다.
    # `festival_min_duration_days`도 채우지 않는다: 축제가 없는 날의 "기간"은 0도 1도
    # 아니라 정의되지 않는 값이고, 0으로 채우면 "1일 축제보다 더 짧은 축제"라는 없는
    # 순서가 생긴다(원칙 1). festival_count로 구별된다.
    count_cols = [
        "game_count",
        "game_attendance_missing",
        "festival_count",
        "festival_short_count",
        "festival_long_count",
        "festival_sponsored_count",
    ]
    events[count_cols] = events[count_cols].fillna(0).astype(int)
    return events, venue_summary, venue_links


def save_events(events: pd.DataFrame) -> Path:
    CROWD_PROCESSED.mkdir(parents=True, exist_ok=True)
    out_path = CROWD_PROCESSED / OUTPUT_NAME
    events.to_parquet(out_path, index=False)
    return out_path


def main() -> None:
    panel_dates = pd.read_parquet(CROWD_PROCESSED / PANEL_NAME, columns=["date"])["date"]
    events, venue_summary, venue_links = build_station_events(
        (panel_dates.min(), panel_dates.max())
    )

    print("[안내] 경기장별 최근접 역 — 좌표가 맞는지 확인용(예상 역이 아니면 좌표를 의심할 것):")
    print(
        venue_summary[["sport", "stadium", "최근접역", "호선", "거리_km", "반경내"]].to_string(
            index=False
        )
    )

    linked = set(venue_links["stadium"])
    unlinked = sorted(set(venue_summary["stadium"]) - linked)
    if unlinked:
        print(
            f"\n[경고] 반경 내 역이 없어 이벤트를 붙이지 못한 경기장 {len(unlinked)}곳: "
            f"{', '.join(unlinked)}"
        )
        print("       승하차 데이터가 서울교통공사 1~8호선뿐이라 코레일·인천 소속 역은 없다.")

    short_rows = int((events["festival_short_count"] > 0).sum())
    long_rows = int((events["festival_long_count"] > 0).sum())
    print(
        f"\n[축제 구성] 축제가 있는 역·일 {int((events['festival_count'] > 0).sum()):,}행 중 "
        f"단기(≤{SPIKE_MAX_DAYS}일) 포함 {short_rows:,}행 / 장기 포함 {long_rows:,}행 — "
        "장기 쪽이 압도적이면 festival_count 단독으로는 신호가 묻힌다."
    )

    out_path = save_events(events)
    print(
        f"\n저장 완료: {out_path} ({len(events):,}행, "
        f"경기 {int((events['game_count'] > 0).sum()):,}건, "
        f"축제 {int((events['festival_count'] > 0).sum()):,}건, "
        f"역 {events['station_no'].nunique()}개)"
    )


if __name__ == "__main__":
    main()
