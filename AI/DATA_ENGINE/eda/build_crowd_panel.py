"""혼잡도 분석·학습용 패널 테이블을 만든다.

`data/CROWD/interim/crowd_daily_ridership_long.parquet`(일별 승하차)를 뼈대로 삼아
달력(휴일)·기상(ASOS)·역 좌표를 붙여 `data/CROWD/processed/crowd_panel_2024_2025.parquet`
하나로 만든다. 이후 상관분석·PCA·클러스터링·피처중요도는 전부 이 테이블 하나만 읽는다 —
조인 로직이 분석 스크립트마다 흩어지면 서로 다른 기준으로 계산하게 되기 때문이다.

**기본 분석 구간은 2024-01-01~2025-12-31 (731일)이다.**
승하차 자체는 2023년부터 있지만 ASOS 기상이 2024년부터라 2023년은 기상이 통째로 비어 있고,
2026년은 아직 상반기 데이터가 확보되지 않은 원천이 있어 양쪽을 다 잘라낸 값이다.

**구간은 `--start`·`--end`로 넓힐 수 있다(학습 기간 확장 백필용).** 기본값 밖으로 나가면
기상 컬럼이 통째로 NaN이 되므로 `main()`이 경고를 찍는다 — 기상을 안 쓰는 모델(배포 세트는
시차·이벤트만 쓴다)에는 문제가 없지만, 조용히 비어 있는 판을 만들지 않기 위한 장치다.
출력 파일명은 구간에서 자동으로 정해진다(`crowd_panel_<시작연도>_<끝연도>.parquet`) — 구간이
다른 판이 서로 덮어쓰지 않게 하려는 것이고, `--out`으로 직접 줄 수도 있다.

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
    python -m DATA_ENGINE.eda.build_crowd_panel --start 2023-01-01 --end 2023-12-31

**구간을 넓혀 새 패널을 지을 때는 이벤트 가공을 먼저 다시 돌린다**(227에서 두 번 겪었다):
    python -m DATA_ENGINE.eda.parsers_festival          # 축제 원천 CSV(연도별) → interim
    python -m DATA_ENGINE.eda.parsers_sports            # KBO·K리그 원문 → interim
    python -m DATA_ENGINE.eda.join_kbo_attendance
    python -m DATA_ENGINE.eda.filter_kleague_seoul_metro
    python -m DATA_ENGINE.eda.map_events_to_stations --panel crowd_panel_<시작>_<끝>.parquet
`map_events_to_stations`만 돌리면 옛 interim/processed 표를 그대로 써서, 원문은 있어도 새 연도의
경기·축제가 0(결측이 0으로)으로 들어간다. 145 후속에서 2023 경기가 전부 0으로, 227에서 2022 축제가
38건으로 들어간 뒤 파서 재실행으로 각각 534경기·804건으로 채워졌다. 재가공은 기존 연도의 값도
바꿀 수 있으니(축제 파일 간 중복 — `validation/CROWD/train-window-check/RESULTS.md` 1.2절) 배포
이벤트 표를 다시 만들 때는 변경 폭을 먼저 잰다.
"""

from __future__ import annotations

import argparse
import sys
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


def panel_output_name(start: pd.Timestamp, end: pd.Timestamp) -> str:
    """구간 → 출력 파일명. 기본 구간이면 기존 이름(`crowd_panel_2024_2025.parquet`) 그대로다."""
    return f"crowd_panel_{pd.Timestamp(start).year}_{pd.Timestamp(end).year}.parquet"


def load_ridership_window(
    start: pd.Timestamp = PANEL_START, end: pd.Timestamp = PANEL_END
) -> pd.DataFrame:
    """분석 구간의 일별 승하차만 읽어온다."""
    df = pd.read_parquet(CROWD_INTERIM / "crowd_daily_ridership_long.parquet")
    return df[(df["date"] >= start) & (df["date"] <= end)].copy()


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
    """휴일 달력을 붙이고 요일·주말 파생 컬럼을 만든다.

    `holiday_calendar.parquet`의 `is_holiday`는 "법정공휴일"이 아니라 원본(사립학교교직원
    연금공단 공휴일 관리 정보)이 정의하는 **학교 휴업일**이다 — 일요일 100%, 토요일 60%가
    Y로 잡혀 있다(2026-09-10 원본 대조 확인). 그래서 `is_holiday`를 조건 없이 덮어쓰면
    토요일·일요일이 전부 "휴일"로 흡수돼 `day_type`이 평일/휴일 2종으로만 나온다 — 아래
    `panel["dow"] < 5` 조건 없이는 이 버그가 재현된다.

    평일에 걸린 공휴일(신정·설날·추석 등, 평일 중 2.65%)만 "휴일"로 덮어써야 혼잡도
    스냅샷(`crowd_congestion_long`)의 day_type과 같은 축이 된다 — 1~8호선 스냅샷은
    평일/토요일/일요일 3종뿐이고(휴일 구분 없음), 9호선은 평일/휴일 2종이라 주말+공휴일을
    스냅샷 스스로 "휴일" 하나로 묶는다. `dow < 5` 가드가 있어야 주말은 항상 토요일/일요일로
    남고, "휴일"은 평일 공휴일만 가리키게 된다.
    """
    holiday = pd.read_parquet(HOLIDAY_INTERIM / "holiday_calendar.parquet")
    panel = panel.merge(holiday[["date", "weekday_ko", "is_holiday"]], on="date", how="left")
    panel["dow"] = panel["date"].dt.dayofweek  # 월=0
    panel["is_weekend"] = panel["dow"] >= 5
    panel["day_type"] = "평일"
    panel.loc[panel["dow"] == 5, "day_type"] = "토요일"
    panel.loc[panel["dow"] == 6, "day_type"] = "일요일"
    panel.loc[panel["is_holiday"] & (panel["dow"] < 5), "day_type"] = "휴일"
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


def build_panel(
    start: pd.Timestamp = PANEL_START, end: pd.Timestamp = PANEL_END
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, int]]:
    ridership = load_ridership_window(start, end)
    if ridership.empty:
        raise ValueError(
            f"{start:%Y-%m-%d}~{end:%Y-%m-%d} 구간에 승하차가 없다 — "
            "`crowd_daily_ridership_long.parquet`의 커버 범위를 먼저 확인할 것."
        )
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


def save_panel(panel: pd.DataFrame, output_name: str = OUTPUT_NAME) -> Path:
    CROWD_PROCESSED.mkdir(parents=True, exist_ok=True)
    out_path = CROWD_PROCESSED / output_name
    panel.to_parquet(out_path, index=False)
    return out_path


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--start", default=str(PANEL_START.date()), help="분석 구간 시작(YYYY-MM-DD)")
    ap.add_argument("--end", default=str(PANEL_END.date()), help="분석 구간 끝(YYYY-MM-DD)")
    ap.add_argument("--out", default=None, help="출력 파일명(기본: 구간에서 자동)")
    args = ap.parse_args(argv)
    start, end = pd.Timestamp(args.start), pd.Timestamp(args.end)
    if start > end:
        raise SystemExit("--start가 --end보다 늦다.")
    output_name = args.out or panel_output_name(start, end)

    panel, name_changes, fill_counts = build_panel(start, end)

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
        share = missing_weather / len(panel) * 100
        print(
            f"[경고] 기상 미매칭 {missing_weather:,}행({share:.1f}%) — "
            "몇 행이면 구간 경계(24~ 마지막 날)지만, 통째로 비면 ASOS가 그 연도를 안 덮는 것이다"
            "(기본 구간 2024~2025 밖은 아직 없다). 기상을 쓰는 분석은 이 판을 그대로 쓰면 안 된다."
        )
    if missing_coord:
        print(f"[경고] 좌표 미매칭 {missing_coord:,}행")

    out_path = save_panel(panel, output_name)
    print(
        f"저장 완료: {out_path} ({len(panel):,}행, "
        f"{panel['date'].min():%Y-%m-%d}~{panel['date'].max():%Y-%m-%d}, "
        f"역 {panel['station_no'].nunique()}개, 시간대 {panel['time_slot'].nunique()}개)"
    )


if __name__ == "__main__":
    main(sys.argv[1:])
