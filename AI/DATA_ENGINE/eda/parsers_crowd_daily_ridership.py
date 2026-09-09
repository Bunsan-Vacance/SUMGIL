"""서울교통공사_역별 일별 시간대별 승하차인원(OA-12921, 수동 다운로드 CSV)
→ data/CROWD/interim/*.parquet.

`parsers_crowd_ridership.py`(OA-12252, "사용월" 월별 집계)와는 별개 원천이다 — 이쪽은 진짜
**일 단위 실측**이라 날씨·공휴일·스포츠·축제와 일 단위로 조인할 수 있는, CROWD 도메인에서
유일한 날짜축 있는 신호다([관련 논문] "장려상" 논문이 인용한 바로 그 데이터셋).

연도별로 받은 파일마다 헤더가 조금씩 다르다 — 2023·2025년 파일은 "수송일자"·"승하차구분"·
"06시이전"/"06-07시간대", 2024년 파일은 "날짜"·"구분"·"06시 이전"/"06시-07시" 식으로
띄어쓰기·표기가 다르다. 같은 뜻이라 컬럼명 정규화로 흡수한다.

`서울교통공사_역별 일별 시간대별 승하차인원 정보_23.11_24.01.csv`는 일부러 제외했다 —
2023-11-01~2024-01-31 범위가 2023년 파일(23.1~23.12)·2024년 파일(24.1~24.12)에 이미 그대로
들어있음을 직접 대조로 확인했다(2026-09-09). 그대로 합치면 그 3개월 구간만 행이 두 배가 된다.

실행:
    cd AI
    python -m DATA_ENGINE.eda.parsers_crowd_daily_ridership
"""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

AI_ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = AI_ROOT / "data" / "CROWD" / "raw"
INTERIM_DIR = AI_ROOT / "data" / "CROWD" / "interim"

# 2023-11~2024-01 구간이 연간 파일 두 개에 완전 중복돼 있어 제외 — 모듈 docstring 참고.
EXCLUDED_FILENAMES = {"서울교통공사_역별 일별 시간대별 승하차인원 정보_23.11_24.01.csv"}

# 연도별 파일마다 ID 컬럼 표기가 달라 후보를 순서대로 시도한다.
_ID_RENAME_VARIANTS = [
    {
        "수송일자": "date",
        "호선": "line",
        "역번호": "station_no",
        "역명": "station_name",
        "승하차구분": "direction",
    },
    {
        "날짜": "date",
        "호선": "line",
        "역번호": "station_no",
        "역명": "station_name",
        "구분": "direction",
    },
]
_DIRECTION_KO_TO_EN = {"승차": "boarding", "하차": "alighting"}

_BEFORE_PATTERN = re.compile(r"^(\d{2})시\s*이전$")
_AFTER_PATTERN = re.compile(r"^(\d{2})시\s*이후$")
_RANGE_DASH_PATTERN = re.compile(r"^(\d{2})-(\d{2})시간대$")
_RANGE_SI_PATTERN = re.compile(r"^(\d{2})시-(\d{2})시$")


def _normalize_hour_column(col: str) -> str | None:
    """시간대 컬럼명 두 표기 방식을 "HH-HH"/"~HH"/"HH~" 공통 라벨로 통일한다.

    id 컬럼(연번 등)처럼 매치되지 않는 컬럼은 None을 반환 — 호출부에서 걸러낸다.
    """
    before = _BEFORE_PATTERN.match(col)
    if before:
        return f"~{before.group(1)}"
    after = _AFTER_PATTERN.match(col)
    if after:
        return f"{after.group(1)}~"
    range_dash = _RANGE_DASH_PATTERN.match(col)
    if range_dash:
        return f"{range_dash.group(1)}-{range_dash.group(2)}"
    range_si = _RANGE_SI_PATTERN.match(col)
    if range_si:
        return f"{range_si.group(1)}-{range_si.group(2)}"
    return None


def load_daily_ridership_csv(path: str | Path) -> pd.DataFrame:
    """일별 승하차 CSV 한 개를 tidy long-format으로 변환한다.

    일부 연도 파일(2025년치에서 확인, 2026-09-09) 끝에 전체가 빈 꼬리 행이 섞여 있다 —
    엑셀/CSV 내보내기 흔한 잔재로, 실제 데이터가 아니라 그대로 두면 melt 후 시간대 수만큼
    뻥튀기된 "중복"으로 잘못 보인다. 실측값이 하나라도 있는 행과 구분하기 위해 핵심 식별
    컬럼(호선)이 전부 비어있는 행만 제거한다 — 값 일부가 진짜로 결측인 행은 건드리지 않는다.
    """
    df = pd.read_csv(path, encoding="cp949")

    rename = next((v for v in _ID_RENAME_VARIANTS if set(v).issubset(df.columns)), None)
    if rename is None:
        raise ValueError(f"알 수 없는 컬럼 형식입니다 — 헤더를 확인하세요: {path}")
    df = df.rename(columns=rename)
    id_vars = list(rename.values())
    df = df.dropna(subset=id_vars, how="all")

    hour_col_map = {
        c: _normalize_hour_column(c) for c in df.columns if c not in id_vars and c != "연번"
    }
    hour_col_map = {k: v for k, v in hour_col_map.items() if v is not None}

    long_df = df.melt(
        id_vars=id_vars, value_vars=list(hour_col_map), var_name="raw_col", value_name="passengers"
    )
    long_df["time_slot"] = long_df["raw_col"].map(hour_col_map)
    long_df["direction"] = long_df["direction"].map(_DIRECTION_KO_TO_EN)
    long_df["date"] = pd.to_datetime(long_df["date"])
    return long_df.drop(columns="raw_col")


def build_daily_ridership_long(raw_dir: Path = RAW_DIR) -> pd.DataFrame:
    csv_paths = [
        p
        for p in sorted(raw_dir.glob("서울교통공사_역별*승하차인원*.csv"))
        if p.name not in EXCLUDED_FILENAMES
    ]
    if not csv_paths:
        raise FileNotFoundError(f"{raw_dir} 에서 일별 승하차 csv 원본을 찾지 못했습니다.")

    frames = [load_daily_ridership_csv(path) for path in csv_paths]
    return pd.concat(frames, ignore_index=True)


def duplicate_cell_inventory(df: pd.DataFrame) -> pd.DataFrame:
    """(date, line, station_name, time_slot, direction) 조합 중복을 그대로 나열한다."""
    key = ["date", "line", "station_name", "time_slot", "direction"]
    dup_mask = df.duplicated(subset=key, keep=False)
    return df[dup_mask].sort_values(key)


def save_interim(df: pd.DataFrame) -> Path:
    INTERIM_DIR.mkdir(parents=True, exist_ok=True)
    out_path = INTERIM_DIR / "crowd_daily_ridership_long.parquet"
    df.to_parquet(out_path, index=False)
    return out_path


def main() -> None:
    df = build_daily_ridership_long()
    dups = duplicate_cell_inventory(df)
    out_path = save_interim(df)
    print(
        f"저장 완료: {out_path} ({len(df):,}행, "
        f"{df['date'].min().date()} ~ {df['date'].max().date()}, 중복 셀 {len(dups)}건)"
    )


if __name__ == "__main__":
    main()
