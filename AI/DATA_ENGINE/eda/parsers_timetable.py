"""서울교통공사 서울 도시철도 열차운행시각표 파서 — 135번(시간 해상도 분해) 2층의 입력.

원천: 공공데이터포털 15098251 「서울교통공사_서울 도시철도 열차운행시각표」(CSV, 수시 갱신,
2026-09-02 수정본). 로그인 다운로드라 자동 수집 대상이 아니다 —
`data/CROWD/raw/timetable/` 아래에 받아둔 파일을 읽는다.

원문 컬럼(포털 명세): 고유번호, 호선, 역사코드, 역사명, 주중주말, 방향, 급행여부, 열차코드,
열차도착시간, 열차출발시간, 출발역, 도착역. 주중주말은 DAY(주중)/SAT(토요일)/END(일요일·공휴일).

## 우리 체계로 맞추는 세 지점

1. **역 매핑** — `역사코드`가 역사마스터 `역사_ID`(= 패널 `station_no`)와 같으면 그대로 쓰고,
   다르면 (호선, 역사명)으로 패널 역 목록에 붙인다. 어느 쪽으로도 안 붙는 역은 결번 인벤토리로
   남기고 조용히 버리지 않는다(9호선 스냅샷이 역번호가 없어 역명 매핑했던 88과 같은 상황).
2. **방향 라벨** — 원문 표기(상행/하행/내선/외선 등)를 우리 라벨(상선/하선/내선/외선)로 정규화한다.
   처음 보는 값은 예외로 올려 매핑을 추가하게 한다(임의 추정 금지).
3. **요일유형** — DAY→평일, SAT→토요일, END→일요일. 시각표는 공휴일을 일요일과 같이 보므로 패널
   day_type "휴일"은 **일요일 시각표**에 대응시킨다(`day_type_to_timetable`).

실행:
    cd AI
    python -m DATA_ENGINE.eda.parsers_timetable   # 파일 인벤토리·매핑 결과 출력
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

AI_ROOT = Path(__file__).resolve().parents[2]
TIMETABLE_RAW = AI_ROOT / "data" / "CROWD" / "raw" / "timetable"
TIMETABLE_INTERIM = AI_ROOT / "data" / "CROWD" / "interim" / "timetable_long.parquet"
STATION_MASTER = AI_ROOT / "data" / "EXTERNAL" / "station" / "raw" / "서울시 역사마스터 정보.csv"

COLUMN_MAP = {
    "고유번호": "row_id",
    "호선": "line_raw",
    "역사코드": "station_code",
    "역사명": "station_name",
    "주중주말": "day_code",
    "방향": "direction_raw",
    "급행여부": "express_raw",
    "열차코드": "train_id",
    "열차도착시간": "arrival_time",
    "열차출발시간": "departure_time",
    "출발역": "origin",
    "도착역": "terminus",
}
DAY_CODE_MAP = {"DAY": "평일", "SAT": "토요일", "END": "일요일"}
DIRECTION_MAP = {
    "상행": "상선",
    "하행": "하선",
    "상선": "상선",
    "하선": "하선",
    "내선": "내선",
    "외선": "외선",
    "내선순환": "내선",
    "외선순환": "외선",
}


def day_type_to_timetable(day_type: str) -> str:
    """패널 day_type → 시각표 요일유형. 공휴일은 일요일 시각표."""
    return "일요일" if day_type == "휴일" else day_type


def read_timetable_csv(path: Path) -> pd.DataFrame:
    for enc in ("utf-8-sig", "cp949"):
        try:
            raw = pd.read_csv(path, encoding=enc, dtype=str)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ValueError(f"인코딩을 알 수 없다: {path}")
    missing = [c for c in COLUMN_MAP if c not in raw.columns]
    if missing:
        raise ValueError(f"기대한 컬럼이 없다: {missing} (있는 컬럼: {list(raw.columns)})")
    return raw.rename(columns=COLUMN_MAP)


def normalize_line(line_raw: pd.Series) -> pd.Series:
    """'2', '02', '2호선' → '2호선'."""
    digits = line_raw.astype(str).str.extract(r"(\d+)")[0]
    return digits.astype("Int64").astype(str) + "호선"


def normalize_direction(direction_raw: pd.Series) -> pd.Series:
    cleaned = direction_raw.astype(str).str.strip()
    unknown = sorted(set(cleaned.unique()) - set(DIRECTION_MAP))
    if unknown:
        raise ValueError(f"방향 표기 매핑이 없다: {unknown} — DIRECTION_MAP에 추가할 것")
    return cleaned.map(DIRECTION_MAP)


def map_stations(frame: pd.DataFrame, stations: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """역사코드 → station_no. 1차 코드 일치, 2차 (호선, 역명) 일치. (매핑된 프레임, 미매핑 인벤토리)."""
    st = stations[["station_no", "station_name", "line"]].drop_duplicates()
    out = frame.copy()
    code = pd.to_numeric(out["station_code"], errors="coerce").astype("Int64")
    known = set(st["station_no"].astype(int))
    out["station_no"] = code.where(code.isin(known))

    need = out["station_no"].isna()
    if need.any():
        by_name = st.rename(columns={"station_no": "station_no_by_name"})
        out = out.merge(by_name, on=["line", "station_name"], how="left")
        out["station_no"] = out["station_no"].fillna(out["station_no_by_name"])
        out = out.drop(columns="station_no_by_name")

    unmapped = (
        out[out["station_no"].isna()][["line", "station_code", "station_name"]]
        .drop_duplicates()
        .reset_index(drop=True)
    )
    return out[out["station_no"].notna()].copy(), unmapped


def build_timetable_long(path: Path, stations: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """CSV → (station_no, line, direction, day_type, train_id, arrival_time, departure_time, express)."""
    raw = read_timetable_csv(path)
    raw["line"] = normalize_line(raw["line_raw"])
    raw["direction"] = normalize_direction(raw["direction_raw"])
    raw["day_type"] = raw["day_code"].str.strip().str.upper().map(DAY_CODE_MAP)
    if raw["day_type"].isna().any():
        bad = sorted(raw.loc[raw["day_type"].isna(), "day_code"].unique())
        raise ValueError(f"주중주말 코드 매핑이 없다: {bad}")
    raw["express"] = (
        raw["express_raw"].astype(str).str.strip().isin(["Y", "급행", "1", "TRUE", "True"])
    )
    mapped, unmapped = map_stations(raw, stations)
    mapped["station_no"] = mapped["station_no"].astype(int)
    cols = [
        "station_no",
        "line",
        "direction",
        "day_type",
        "train_id",
        "arrival_time",
        "departure_time",
        "express",
        "origin",
        "terminus",
    ]
    out = mapped[cols].sort_values(["line", "station_no", "direction", "day_type", "arrival_time"])
    return out.reset_index(drop=True), unmapped


def load_stations_from_panel() -> pd.DataFrame:
    panel_path = AI_ROOT / "data" / "CROWD" / "processed" / "crowd_panel_2024_2025.parquet"
    return pd.read_parquet(
        panel_path, columns=["station_no", "station_name", "line"]
    ).drop_duplicates("station_no")


def main() -> None:
    files = sorted(TIMETABLE_RAW.glob("*.csv"))
    if not files:
        print(f"시각표 CSV가 없다: {TIMETABLE_RAW} — 공공데이터포털 15098251에서 받아 넣을 것")
        return
    stations = load_stations_from_panel()
    frames, gaps = [], []
    for f in files:
        long, unmapped = build_timetable_long(f, stations)
        frames.append(long)
        gaps.append(unmapped.assign(file=f.name))
        print(
            f"[{f.name}] {len(long):,}행, 역 {long['station_no'].nunique()}개, 미매핑 {len(unmapped)}역"
        )
    out = pd.concat(frames, ignore_index=True)
    TIMETABLE_INTERIM.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(TIMETABLE_INTERIM, index=False)
    gap_frame = pd.concat(gaps, ignore_index=True)
    if len(gap_frame):
        print("\n[미매핑 역 — 결번 인벤토리]")
        print(gap_frame.to_string(index=False))
    per_day = out.groupby(["line", "day_type"], observed=True)["train_id"].nunique()
    print("\n[호선·요일유형별 열차 수]")
    print(per_day.to_string())
    print(f"\n저장: {TIMETABLE_INTERIM} ({len(out):,}행)")


if __name__ == "__main__":
    main()
