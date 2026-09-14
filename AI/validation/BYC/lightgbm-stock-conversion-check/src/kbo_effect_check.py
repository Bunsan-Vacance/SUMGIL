"""0-2 — KBO 경기가 따릉이 재고에 실제로 신호를 주는지 가볍게 확인한다(전체 파이프라인
만들기 전 사전 검증, `AI/CLAUDE.md`의 "정직한 baseline 먼저" 원칙).

구장 좌표는 CROWD 작업 때 만든 `DATA_ENGINE/conf/venue_coordinates.yaml`을 그대로 재사용한다
(잠실·고척·문학·수원 4구장, 관중수 있는 경기만). 반경(`radius_km`, 기본 1.5km) 안의 BIKE
역만 "그 구장 영향권"으로 보고, 그 역들의 경기일 vs 비경기일 net_flow를 비교한다.

**커버리지 한계**: 문학(인천)·수원은 서울 밖이라 BIKE 역 반경 안에 아예 안 걸릴 수 있다 —
main()이 구장별로 몇 개 역이 잡혔는지 출력한다.

실행:
    cd AI
    PYTHONPATH=. PYTHONIOENCODING=utf-8 python validation/BYC/lightgbm-stock-conversion-check/src/kbo_effect_check.py
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from app.BIKE.pipeline.dataset import monthly_paths

AI_ROOT = Path(__file__).resolve().parents[4]
VENUE_CONF = AI_ROOT / "DATA_ENGINE" / "conf" / "venue_coordinates.yaml"
KBO_PARQUET = AI_ROOT / "data" / "EXTERNAL" / "events" / "processed" / "kbo_games_with_attendance.parquet"

EARTH_RADIUS_KM = 6371.0


def haversine_km(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = map(np.radians, (lat1, lon1, lat2, lon2))
    dlat, dlon = lat2 - lat1, lon2 - lon1
    a = np.sin(dlat / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_KM * np.arcsin(np.sqrt(a))


def load_stadiums() -> tuple[pd.DataFrame, float]:
    conf = yaml.safe_load(VENUE_CONF.read_text(encoding="utf-8"))
    rows = [{"stadium": name, "lat": c["lat"], "lon": c["lon"]} for name, c in conf["kbo"].items()]
    return pd.DataFrame(rows), float(conf["radius_km"])


def load_bike_stations() -> pd.DataFrame:
    """netflow 산출물 1개 파일에서 station 좌표만 뽑는다(월마다 동일하므로 1개면 충분)."""
    p = monthly_paths("train", ["202401"])[0]
    df = pd.read_parquet(p, columns=["od_station_id", "lat_stock", "lon_stock"])
    return df.drop_duplicates("od_station_id").dropna(subset=["lat_stock", "lon_stock"])


def match_stations_to_stadiums(stations: pd.DataFrame, stadiums: pd.DataFrame, radius_km: float) -> pd.DataFrame:
    rows = []
    for _, st in stadiums.iterrows():
        d = haversine_km(stations["lat_stock"].to_numpy(), stations["lon_stock"].to_numpy(), st["lat"], st["lon"])
        near = stations.loc[d <= radius_km, "od_station_id"]
        for sid in near:
            rows.append({"od_station_id": sid, "stadium": st["stadium"]})
    return pd.DataFrame(rows)


def main() -> None:
    if not KBO_PARQUET.exists():
        raise FileNotFoundError(f"{KBO_PARQUET} 없음 — Drive에서 받아서 넣어야 함")

    stadiums, radius_km = load_stadiums()
    stations = load_bike_stations()
    print(f"[KBO] 전체 BIKE 역 {len(stations):,}개, 구장 반경 {radius_km}km")

    matched = match_stations_to_stadiums(stations, stadiums, radius_km)
    print("[KBO] 구장별 매칭된 역 수:")
    print(matched.groupby("stadium").size().to_string())

    if matched.empty:
        print("[KBO] 매칭된 역이 없음 — 이 반경으로는 효과 검증 불가, 종료")
        return

    games = pd.read_parquet(KBO_PARQUET)
    games = games.dropna(subset=["attendance"])  # 관중수 있는 4구장 실제 경기만
    games["date"] = pd.to_datetime(games["date"]).dt.normalize()
    print(f"[KBO] 관중수 있는 경기 {len(games):,}건, 기간 {games['date'].min().date()} ~ {games['date'].max().date()}")

    # ── 구장별 경기일 집합 ──
    game_dates_by_stadium = games.groupby("stadium")["date"].apply(set).to_dict()

    train_paths = monthly_paths("train", None)
    valid_paths = monthly_paths("valid", None)
    test_paths = monthly_paths("test", None)
    all_paths = train_paths + valid_paths + test_paths

    target_ids = set(matched["od_station_id"])
    id_to_stadium = dict(zip(matched["od_station_id"], matched["stadium"], strict=False))

    rows = []
    for p in all_paths:
        df = pd.read_parquet(
            p, columns=["od_station_id", "date", "horizon_min", "target_net_flow"]
        )
        df = df[(df["od_station_id"].isin(target_ids)) & (df["horizon_min"] == 5)]
        if df.empty:
            continue
        df["date"] = pd.to_datetime(df["date"]).dt.normalize()
        df["stadium"] = df["od_station_id"].map(id_to_stadium)
        df["is_game_day"] = df.apply(lambda r: r["date"] in game_dates_by_stadium.get(r["stadium"], set()), axis=1)
        rows.append(df[["stadium", "is_game_day", "target_net_flow"]])

    if not rows:
        print("[KBO] 매칭된 역의 데이터가 netflow 산출물에 없음 — 종료")
        return

    combined = pd.concat(rows, ignore_index=True)
    print("\n[KBO] 구장별 경기일 vs 비경기일 net_flow 평균/표준편차:")
    summary = combined.groupby(["stadium", "is_game_day"])["target_net_flow"].agg(["mean", "std", "count"])
    print(summary.to_string())


if __name__ == "__main__":
    main()


def hourly_breakdown() -> None:
    """게임 시간대(보통 저녁)에만 국한된 효과가 하루 평균에 묻혔을 수 있어 시간대별로 다시 본다."""
    stadiums, radius_km = load_stadiums()
    stations = load_bike_stations()
    matched = match_stations_to_stadiums(stations, stadiums, radius_km)
    games = pd.read_parquet(KBO_PARQUET).dropna(subset=["attendance"])
    games["date"] = pd.to_datetime(games["date"]).dt.normalize()
    game_dates_by_stadium = games.groupby("stadium")["date"].apply(set).to_dict()

    target_ids = set(matched["od_station_id"])
    id_to_stadium = dict(zip(matched["od_station_id"], matched["stadium"], strict=False))
    all_paths = monthly_paths("train", None) + monthly_paths("valid", None) + monthly_paths("test", None)

    rows = []
    for p in all_paths:
        df = pd.read_parquet(p, columns=["od_station_id", "date", "hour", "horizon_min", "target_net_flow"])
        df = df[(df["od_station_id"].isin(target_ids)) & (df["horizon_min"] == 5)]
        if df.empty:
            continue
        df["date"] = pd.to_datetime(df["date"]).dt.normalize()
        df["stadium"] = df["od_station_id"].map(id_to_stadium)
        df["is_game_day"] = df.apply(lambda r: r["date"] in game_dates_by_stadium.get(r["stadium"], set()), axis=1)
        rows.append(df[["stadium", "hour", "is_game_day", "target_net_flow"]])

    combined = pd.concat(rows, ignore_index=True)
    print("\n[KBO] 시간대별 경기일 vs 비경기일 net_flow 평균 (구장별):")
    piv = combined.groupby(["stadium", "hour", "is_game_day"])["target_net_flow"].mean().unstack("is_game_day")
    piv["diff"] = piv[True] - piv[False]
    print(piv.to_string())


if __name__ == "__main__":
    hourly_breakdown()


def three_metric_recheck() -> None:
    """weather/holiday 재검증과 같은 3개 지표(net_flow/활동량/empty·full 발생률)로 KBO도
    공정하게 다시 본다 — net_flow만 봐서 놓쳤을 가능성 배제."""
    stadiums, radius_km = load_stadiums()
    stations = load_bike_stations()
    matched = match_stations_to_stadiums(stations, stadiums, radius_km)
    games = pd.read_parquet(KBO_PARQUET).dropna(subset=["attendance"])
    games["date"] = pd.to_datetime(games["date"]).dt.normalize()
    game_dates_by_stadium = games.groupby("stadium")["date"].apply(set).to_dict()

    target_ids = set(matched["od_station_id"])
    id_to_stadium = dict(zip(matched["od_station_id"], matched["stadium"], strict=False))
    all_paths = monthly_paths("train", None) + monthly_paths("valid", None) + monthly_paths("test", None)

    cols = [
        "od_station_id", "date", "horizon_min", "stock_anchor_hour", "rack_count",
        "target_net_flow", "target_rent_count", "target_return_count",
    ]
    rows = []
    for p in all_paths:
        df = pd.read_parquet(p, columns=cols)
        df = df[(df["od_station_id"].isin(target_ids)) & (df["horizon_min"] == 5)]
        if df.empty:
            continue
        df = df.dropna(subset=["stock_anchor_hour", "target_net_flow"])
        df["date"] = pd.to_datetime(df["date"]).dt.normalize()
        df["stadium"] = df["od_station_id"].map(id_to_stadium)
        df["is_game_day"] = df.apply(lambda r: r["date"] in game_dates_by_stadium.get(r["stadium"], set()), axis=1)
        df["activity"] = df["target_rent_count"] + df["target_return_count"]
        future_stock = df["stock_anchor_hour"] + df["target_net_flow"]
        df["is_empty_future"] = future_stock <= 0
        df["is_full_future"] = future_stock >= df["rack_count"]
        rows.append(df[["stadium", "is_game_day", "activity", "target_net_flow", "is_empty_future", "is_full_future"]])

    combined = pd.concat(rows, ignore_index=True)
    print(f"\n[KBO 3지표 재검증] 전체 {len(combined):,}행")
    agg = combined.groupby(["stadium", "is_game_day"]).agg(
        net_flow_mean=("target_net_flow", "mean"),
        activity_mean=("activity", "mean"),
        empty_rate=("is_empty_future", "mean"),
        full_rate=("is_full_future", "mean"),
        n=("target_net_flow", "size"),
    )
    print(agg.to_string())


if __name__ == "__main__":
    three_metric_recheck()
