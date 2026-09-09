"""혼잡도 분석·학습용 패널 테이블을 만든다.

`data/CROWD/interim/crowd_daily_ridership_long.parquet`(일별 승하차)를 뼈대로 삼아
달력(휴일)·기상(ASOS)·역 좌표를 붙여 `data/CROWD/processed/crowd_panel_2024_2025.parquet`
하나로 만든다. 이후 상관분석·PCA·클러스터링·피처중요도는 전부 이 테이블 하나만 읽는다 —
조인 로직이 분석 스크립트마다 흩어지면 서로 다른 기준으로 계산하게 되기 때문이다.

**분석 구간은 2024-01-01~2025-12-31 (731일)로 고정한다.**
승하차 자체는 2023년부터 있지만 ASOS 기상이 2024년부터라 2023년은 기상·이벤트가 통째로
비어 있고, 2026년은 아직 상반기 데이터가 확보되지 않은 원천이 있어 양쪽을 다 잘라냈다.

**패널 격자**: (date, station_no, time_slot). 승차/하차는 행이 아니라 열(`boarding`/
`alighting`)로 편다 — 모델이 둘을 동시에 예측하고, 순유입(하차-승차)을 파생하기 쉽다.

**역 조인은 역명이 아니라 `station_no`로 한다.** 승하차 쪽 역명에는 부기명이 붙어 있고
(`낙성대(강감찬)`) 기간 중 개명된 역도 있어 이름으로 붙이면 어긋난다. `station_no`는
역사마스터 `역사_ID`와 273/273 전부 일치한다.

**시간대→기상 시각 매핑**: 승하차의 20개 구간 중 18개는 정시 1시간이라 그대로 붙지만
양 끝 2개는 다르다. `~06`은 "06시 이전"이지만 첫차가 05:30경이라 실질 30분 구간이고
(평균 134명, `06-07` 381명의 1/3 수준 — 6시간이었다면 이보다 훨씬 컸다), `24~`는
"24시 이후"로 달력상 **다음 날** 00시대다. 각각 같은 날 05시, 다음 날 00시 기상을 붙인다.

실행:
    cd AI
    python -m DATA_ENGINE.eda.build_crowd_panel
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

AI_ROOT = Path(__file__).resolve().parents[2]
CROWD_INTERIM = AI_ROOT / "data" / "CROWD" / "interim"
CROWD_PROCESSED = AI_ROOT / "data" / "CROWD" / "processed"
WEATHER_INTERIM = AI_ROOT / "data" / "EXTERNAL" / "weather" / "interim"
HOLIDAY_INTERIM = AI_ROOT / "data" / "EXTERNAL" / "holiday" / "interim"
STATION_RAW = AI_ROOT / "data" / "EXTERNAL" / "station" / "raw"

PANEL_START = pd.Timestamp("2024-01-01")
PANEL_END = pd.Timestamp("2025-12-31")

OUTPUT_NAME = "crowd_panel_2024_2025.parquet"

# ASOS는 "값이 0인 시간"을 빈칸으로 내려준다 — 무강수 시간의 강수량, 눈이 없는 날의
# 적설, 해가 없는 야간의 일조·일사가 그렇다. 표본이 없어서 비는 게 아니라 관측 규격상
# 0의 표현이므로 0으로 채운다(데이터-검증-리포트 "표본 부족 구간에 값을 채우지 않는다"
# 원칙의 예외 — 부족이 아니라 규격이다). 바람처럼 진짜 관측 누락인 항목은 채우지 않는다.
_ZERO_FILL_WEATHER = ["precip_mm", "snow_cm", "sunshine_hr", "solar_mj"]

_WEATHER_COLS = [
    "temp_c",
    "precip_mm",
    "wind_ms",
    "wind_dir16",
    "humidity_pct",
    "sunshine_hr",
    "solar_mj",
    "snow_cm",
]


def slot_to_weather_offset(slot: str) -> tuple[int, int]:
    """시간대 라벨을 (날짜 오프셋, 기상 시각)으로 바꾼다.

    `06-07`~`23-24`는 같은 날 앞자리 시각, `~06`은 첫차 구간이라 같은 날 05시,
    `24~`는 운행일 기준 자정 이후라 다음 날 00시에 대응한다.
    """
    if slot == "~06":
        return 0, 5
    if slot == "24~":
        return 1, 0
    return 0, int(slot.split("-")[0])


def load_ridership_window() -> pd.DataFrame:
    """분석 구간의 일별 승하차만 읽어온다."""
    df = pd.read_parquet(CROWD_INTERIM / "crowd_daily_ridership_long.parquet")
    return df[(df["date"] >= PANEL_START) & (df["date"] <= PANEL_END)].copy()


def station_name_inventory(df: pd.DataFrame) -> pd.DataFrame:
    """같은 `station_no`가 기간 중 두 개 이상의 역명으로 등장하는 경우를 나열한다.

    개명·부기명 추가가 실제로 있어 (line, station_name) 조합수(277)와 station_no
    개수(273)가 어긋난다. 조인은 station_no로 하니 문제되지 않지만, 무엇이 바뀌었는지는
    남겨 둔다 — 조용히 덮지 않는다.
    """
    names = df.groupby("station_no")["station_name"].unique()
    multi = names[names.map(len) > 1]
    return pd.DataFrame({"station_no": multi.index, "names": [list(v) for v in multi.to_numpy()]})


def pivot_directions(df: pd.DataFrame) -> pd.DataFrame:
    """승차/하차를 행에서 열로 편다."""
    wide = df.pivot_table(
        index=["date", "station_no", "time_slot"],
        columns="direction",
        values="passengers",
        aggfunc="sum",
    ).reset_index()
    wide.columns.name = None
    return wide


def attach_calendar(panel: pd.DataFrame) -> pd.DataFrame:
    """휴일 달력을 붙이고 요일·주말 파생 컬럼을 만든다."""
    holiday = pd.read_parquet(HOLIDAY_INTERIM / "holiday_calendar.parquet")
    panel = panel.merge(holiday[["date", "weekday_ko", "is_holiday"]], on="date", how="left")
    panel["dow"] = panel["date"].dt.dayofweek  # 월=0
    panel["is_weekend"] = panel["dow"] >= 5
    # 혼잡도 스냅샷(`crowd_congestion_long`)의 day_type과 맞춘 구분 — 나중에 스냅샷을
    # 참조 타겟으로 붙일 때 같은 축으로 비교하기 위해서다.
    panel["day_type"] = "평일"
    panel.loc[panel["dow"] == 5, "day_type"] = "토요일"
    panel.loc[panel["dow"] == 6, "day_type"] = "일요일"
    panel.loc[panel["is_holiday"], "day_type"] = "휴일"
    return panel


def prepare_weather() -> tuple[pd.DataFrame, dict[str, int]]:
    """ASOS를 (date, hour) 키로 정리하고 규격상 0인 항목을 채운다."""
    asos = pd.read_parquet(WEATHER_INTERIM / "asos_hourly.parquet")
    fill_counts = {c: int(asos[c].isna().sum()) for c in _ZERO_FILL_WEATHER}
    asos[_ZERO_FILL_WEATHER] = asos[_ZERO_FILL_WEATHER].fillna(0.0)
    asos["w_date"] = asos["datetime"].dt.normalize()
    asos["w_hour"] = asos["datetime"].dt.hour
    return asos[["w_date", "w_hour", *_WEATHER_COLS]], fill_counts


def attach_weather(panel: pd.DataFrame, weather: pd.DataFrame) -> pd.DataFrame:
    """시간대 라벨을 기상 시각으로 환산해 붙인다."""
    offsets = {slot: slot_to_weather_offset(slot) for slot in panel["time_slot"].unique()}
    day_offset = panel["time_slot"].map(lambda s: offsets[s][0])
    panel["w_date"] = panel["date"] + pd.to_timedelta(day_offset, unit="D")
    panel["w_hour"] = panel["time_slot"].map(lambda s: offsets[s][1])
    panel = panel.merge(weather, on=["w_date", "w_hour"], how="left")
    return panel.drop(columns=["w_date", "w_hour"])


def attach_station_meta(panel: pd.DataFrame) -> pd.DataFrame:
    """역사마스터에서 역명·호선·위경도를 붙인다(키는 station_no ↔ 역사_ID)."""
    master = pd.read_csv(STATION_RAW / "서울시 역사마스터 정보.csv", encoding="cp949")
    master = master.rename(
        columns={
            "역사_ID": "station_no",
            "역사명": "station_name",
            "호선": "line",
            "위도": "lat",
            "경도": "lon",
        }
    )
    # 환승역은 호선마다 행이 따로 있지만 좌표는 같다 — station_no 단위로 한 행만 남긴다.
    master = master.drop_duplicates(subset="station_no")
    panel["station_no"] = panel["station_no"].astype("int64")
    return panel.merge(
        master[["station_no", "station_name", "line", "lat", "lon"]],
        on="station_no",
        how="left",
    )


def build_panel() -> tuple[pd.DataFrame, pd.DataFrame, dict[str, int]]:
    ridership = load_ridership_window()
    name_changes = station_name_inventory(ridership)

    panel = pivot_directions(ridership)
    panel = attach_calendar(panel)
    weather, fill_counts = prepare_weather()
    panel = attach_weather(panel, weather)
    panel = attach_station_meta(panel)

    ordered = [
        "date",
        "station_no",
        "station_name",
        "line",
        "lat",
        "lon",
        "time_slot",
        "boarding",
        "alighting",
        "dow",
        "weekday_ko",
        "is_holiday",
        "is_weekend",
        "day_type",
        *_WEATHER_COLS,
    ]
    return panel[ordered], name_changes, fill_counts


def save_panel(panel: pd.DataFrame) -> Path:
    CROWD_PROCESSED.mkdir(parents=True, exist_ok=True)
    out_path = CROWD_PROCESSED / OUTPUT_NAME
    panel.to_parquet(out_path, index=False)
    return out_path


def main() -> None:
    panel, name_changes, fill_counts = build_panel()

    # 콘솔이 cp949라 이모지를 못 찍는다(UnicodeEncodeError) — 표기는 한글로 둔다.
    if len(name_changes):
        print(
            f"[안내] 기간 중 역명이 바뀐 station_no {len(name_changes)}건 (조인은 ID 기준이라 무영향):"
        )
        print(name_changes.to_string(index=False))

    print("[안내] ASOS 규격상 0 채움:", ", ".join(f"{k} {v:,}건" for k, v in fill_counts.items()))

    missing_weather = int(panel["temp_c"].isna().sum())
    missing_coord = int(panel["lat"].isna().sum())
    if missing_weather:
        print(f"[경고] 기상 미매칭 {missing_weather:,}행 — 구간 경계(24~ 마지막 날) 확인 필요")
    if missing_coord:
        print(f"[경고] 좌표 미매칭 {missing_coord:,}행")

    out_path = save_panel(panel)
    print(
        f"저장 완료: {out_path} ({len(panel):,}행, "
        f"{panel['date'].min():%Y-%m-%d}~{panel['date'].max():%Y-%m-%d}, "
        f"역 {panel['station_no'].nunique()}개, 시간대 {panel['time_slot'].nunique()}개)"
    )


if __name__ == "__main__":
    main()
