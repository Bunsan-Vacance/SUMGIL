"""서울교통공사_9호선2_3단계 역별일별시간대별승하차인원(수동 다운로드 CSV)
→ data/CROWD/interim/*.parquet.

`parsers_crowd_daily_ridership.py`(OA-12921, 1~8호선)와 원천이 다르다 — 9호선은 운영사가
둘로 쪼개져 있어(1단계: 서울시메트로9호선 민간, 2·3단계: 서울교통공사 직영) 서울교통공사가
공급하는 일별 데이터는 **자기가 운영하는 2·3단계(언주~중앙보훈병원, 13역)만** 담는다. 1단계는
이번 스코프에서 제외했다 — 결정 배경은 Notion [CROWD] 혼잡도 / "9호선 1단계 스코프 제외" 참고.

## 파일 3개 중 하나는 완전 중복이라 뺀다

받은 파일은 기간이 겹친다:
    - `..._20250101-251231.csv` — 2025-01-01~2025-12-31 (연간)
    - `..._20250731.csv`        — 2025-01-01~2025-07-31 (연간 파일의 앞부분과 완전히 겹침)
    - `..._20260131.csv`        — 2026-01-01~2026-01-31 (겹치지 않는 신규 구간)

`_20250731.csv`는 연간 파일의 순수 부분집합이다 — 겹치는 2025-01-01~07-31 구간에서 값이
행 단위로 완전히 일치함을 직접 대조로 확인했다(2026-09-10, 아래 "알려진 데이터 이상" 문단의
중복 키 두 건까지 포함해서 동일). `parsers_crowd_daily_ridership.py`의 `23.11_24.01.csv`
제외와 같은 상황이라 `EXCLUDED_FILENAMES`로 뺀다 — 그대로 합치면 7개월치 행이 두 배가 된다.

## 알려진 데이터 이상 — 중복 키, 값은 다름 → 결측 처리

원본 자체에 결함이 있다. **2025-03-22(토), 2025-06-22(일) 두 날짜에서 13개 역(= 이 구간
전체) 순하차 행이 2건씩** 있고(같은 날짜·역번호·구분 키), 두 행의 시간대별 값이 서로 다르다
(예: 언주역 2025-03-22 08-09시가 3,389명과 431명으로 갈림 — 8배 차이). `순승차`에는 이
문제가 없다. 공식 컬럼 설명("연번: 구분을 위한 번호")을 확인해봤지만 어느 쪽이 맞는지
판단할 근거가 되는 필드(생성시각·정정 여부 등)가 없다 — 두 파일(연간·0731, 0731은 이후
삭제)이 두 값을 동일하게 담고 있어 다운로드 시점 문제도 아니고, 13역이 같은 날 동시에
터진 것도 역별 결함이 아니라 그날 배치 집계가 중복 실행됐음을 시사한다.

둘 중 하나를 임의로 고르거나 평균 내면 조용히 틀린 값을 만드는 것과 같다(데이터 검증
리포트 원칙 1). 영향 범위가 전체 10,296개 역-일-구분 조합 중 26건(0.25%)으로 작고 그마저
비연속 이틀에 고립돼 있어, 이 26개 조합은 아예 **행에서 제거해 결측으로 남긴다**
(`drop_conflicting_duplicates`) — 값을 추정해 채우는 것보다 시계열에 주는 손상이 작다.

실행:
    cd AI
    python -m DATA_ENGINE.eda.parsers_crowd_line9_daily_ridership
"""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

AI_ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = AI_ROOT / "data" / "CROWD" / "raw"
INTERIM_DIR = AI_ROOT / "data" / "CROWD" / "interim"
STATION_RAW = AI_ROOT / "data" / "EXTERNAL" / "station" / "raw"

# 연간 파일(20250101-251231)의 순수 부분집합이라 뺀다 — 모듈 docstring 참고.
EXCLUDED_FILENAMES = {"서울교통공사_9호선2_3단계 역별일별시간대별승하차인원_20250731.csv"}

_ID_RENAME = {
    "날짜": "date",
    "호선": "line",
    "역번호": "station_no",
    "역사명": "station_name",
    "구분": "direction",
}
# "순" 접두는 원본 표기 그대로다 — 승차/하차 각각 한 방향만 담는다는 뜻으로 보이나 원천
# 문서에 정의가 없어 "왜 순인지"는 확인하지 못했다. boarding/alighting은 다른 CROWD 파서와
# 맞춘 이름이다.
_DIRECTION_KO_TO_EN = {"순승차": "boarding", "순하차": "alighting"}

_HOUR_PATTERN = re.compile(r"^(\d{2})시-(\d{2})시$")


def _normalize_hour_column(col: str) -> str | None:
    """`"06시-07시"` → `"06-07"`. 매치되지 않는 컬럼(연번 등)은 None."""
    m = _HOUR_PATTERN.match(col)
    return f"{m.group(1)}-{m.group(2)}" if m else None


def load_line9_daily_csv(path: str | Path) -> pd.DataFrame:
    """9호선 2·3단계 일별 승하차 CSV 한 개를 tidy long-format으로 변환한다.

    시간대 컬럼 중 러시아워대(06시~23시)는 원본이 천 단위 콤마(`"1,032"`)를 써서 pandas가
    문자열로 읽는다 — 콤마를 지우고 정수로 바꾼다. 새벽·자정 컬럼은 세 자리를 안 넘어
    애초에 숫자로 읽히지만, 처리를 컬럼별로 분기하면 그 경계가 바뀔 때 깨지므로 전체
    시간대 컬럼에 동일하게 적용한다.
    """
    df = pd.read_csv(path, encoding="cp949")
    df = df.rename(columns=_ID_RENAME)
    id_vars = list(_ID_RENAME.values())

    hour_col_map = {
        c: _normalize_hour_column(c) for c in df.columns if c not in id_vars and c != "연번"
    }
    hour_col_map = {k: v for k, v in hour_col_map.items() if v is not None}
    for col in hour_col_map:
        df[col] = df[col].astype(str).str.replace(",", "", regex=False).astype(int)

    long_df = df.melt(
        id_vars=id_vars, value_vars=list(hour_col_map), var_name="raw_col", value_name="passengers"
    )
    long_df["time_slot"] = long_df["raw_col"].map(hour_col_map)
    long_df["direction"] = long_df["direction"].map(_DIRECTION_KO_TO_EN)
    long_df["date"] = pd.to_datetime(long_df["date"])
    long_df["line"] = "9호선"
    return long_df.drop(columns="raw_col")


def build_line9_daily_long(raw_dir: Path = RAW_DIR) -> pd.DataFrame:
    csv_paths = [
        p
        for p in sorted(raw_dir.glob("서울교통공사_9호선2_3단계*승하차인원*.csv"))
        if p.name not in EXCLUDED_FILENAMES
    ]
    if not csv_paths:
        raise FileNotFoundError(
            f"{raw_dir} 에서 9호선 2·3단계 일별 승하차 csv 원본을 찾지 못했습니다."
        )

    frames = [load_line9_daily_csv(path) for path in csv_paths]
    return pd.concat(frames, ignore_index=True)


def duplicate_cell_inventory(df: pd.DataFrame) -> pd.DataFrame:
    """(date, station_no, time_slot, direction) 조합 중복을 그대로 나열한다.

    `parsers_crowd_daily_ridership.py`와 이름·형태를 맞췄다. `drop_conflicting_duplicates`가
    이 함수로 찾은 조합을 실제로 제거하기 전에, 무엇을 지우는지 확인하는 용도로 쓴다.
    """
    key = ["date", "station_no", "time_slot", "direction"]
    dup_mask = df.duplicated(subset=key, keep=False)
    return df[dup_mask].sort_values(key)


def drop_conflicting_duplicates(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """값이 서로 다른 중복 키를 가진 (date, station_no, direction) 조합을 통째로 제거한다.

    조회 실패와 같은 취급이다 — 채워 넣을 근거가 없는 값은 결측으로 남긴다(원칙 1).
    남은 값 중 하나가 우연히 맞을 수도 있지만, 어느 쪽인지 모르는 채로 하나를 골라 쓰면
    "틀렸을 수도 있는 값"이 "결측"보다 항상 더 나쁘다. 두 번째 반환값은 제거된 (date,
    station_no, direction) 조합 인벤토리 — 호출부가 몇 건이 빠졌는지 보고할 수 있게 한다.
    """
    dups = duplicate_cell_inventory(df)
    if dups.empty:
        return df, dups.drop_duplicates(["date", "station_no", "direction"])

    conflict_keys = dups.drop_duplicates(["date", "station_no", "direction"])
    key_cols = ["date", "station_no", "direction"]
    is_conflict = df.set_index(key_cols).index.isin(conflict_keys.set_index(key_cols).index)
    cleaned = df[~is_conflict].reset_index(drop=True)
    return cleaned, conflict_keys


def load_station_master(station_raw: Path = STATION_RAW) -> pd.DataFrame:
    """역사마스터에서 이 원천의 역(4126~4138, "9호선(연장)")만 골라 온다.

    `build_crowd_panel.py`가 1~8호선을 `station_no ↔ 역사_ID`로 조인하는 것과 같은
    방식이다 — 9호선 2·3단계도 원본 CSV의 `역번호`가 이미 역사마스터 `역사_ID`와 같은
    체계(4126~4138)를 그대로 쓰고 있어(2026-09-10 대조 확인, 순수 충돌 0건), 새로
    번호를 매길 필요 없이 그대로 조인 키로 쓴다.
    """
    master = pd.read_csv(station_raw / "서울시 역사마스터 정보.csv", encoding="cp949")
    return master[master["역사_ID"].between(4126, 4138)].rename(
        columns={
            "역사_ID": "station_no",
            "역사명": "station_name_master",
            "위도": "lat",
            "경도": "lon",
        }
    )[["station_no", "station_name_master", "lat", "lon"]]


def attach_station_master(df: pd.DataFrame, station_raw: Path = STATION_RAW) -> pd.DataFrame:
    """역사마스터의 위경도를 붙이고, 역명 표기가 다른 역만 마스터 이름으로 정정한다.

    두 원천의 역명은 12/13역이 완전히 같고, `올림픽공원`(이 CSV) 하나만 역사마스터가
    `올림픽공원(한국체대)`로 부기명을 붙여 쓴다. 조인은 station_no로 하니 지장은 없지만,
    표출용 이름은 하나로 통일해야 하므로 마스터 쪽을 정본으로 채택한다 — 부기명이 실제
    시설(한국체대 캠퍼스 인접)을 가리키는 더 구체적인 표기라서다.
    """
    master = load_station_master(station_raw)
    merged = df.merge(master, on="station_no", how="left")
    if merged["station_name_master"].isna().any():
        missing = sorted(merged.loc[merged["station_name_master"].isna(), "station_no"].unique())
        raise ValueError(f"역사마스터에서 찾지 못한 station_no: {missing}")
    merged["station_name"] = merged["station_name_master"]
    return merged.drop(columns="station_name_master")


def save_interim(df: pd.DataFrame) -> Path:
    INTERIM_DIR.mkdir(parents=True, exist_ok=True)
    out_path = INTERIM_DIR / "crowd_line9_daily_ridership_long.parquet"
    df.to_parquet(out_path, index=False)
    return out_path


def main() -> None:
    raw = build_line9_daily_long()
    df, dropped = drop_conflicting_duplicates(raw)
    out_path = save_interim(df)
    print(
        f"저장 완료: {out_path} ({len(df):,}행, "
        f"{df['date'].min().date()} ~ {df['date'].max().date()}, "
        f"역 {df['station_no'].nunique()}개)"
    )
    if len(dropped):
        print(
            f"[경고] 값이 서로 다른 중복 키 (날짜, 역, 방향) {len(dropped):,}건을 결측으로 "
            "남기고 제거했다 — 어느 쪽이 맞는지 원천에 판단 근거가 없다:"
        )
        print(dropped[["date", "station_no", "station_name", "direction"]].to_string(index=False))


if __name__ == "__main__":
    main()
