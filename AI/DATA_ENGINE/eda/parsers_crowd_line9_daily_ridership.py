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

## 알려진 데이터 이상 — 중복 키, 값은 다름

원본 자체에 결함이 있다. **2025-03-22, 2025-06-22 두 날짜에서 13개 역 전부 `순하차` 행이
2건씩** 있고(같은 날짜·역번호·구분 키), 두 행의 시간대별 값이 서로 다르다(예: 언주역
2025-03-22 08-09시가 3,389명과 431명으로 갈림 — 8배 차이). `순승차`에는 이 문제가 없다.

어느 쪽이 맞는 값인지 판단할 근거가 없고(원천 문서에 설명 없음), 둘 중 하나를 임의로
버리거나 평균 내면 조용히 틀린 값을 만드는 것과 같다(데이터 검증 리포트 원칙 1). 그래서
`parsers_crowd_daily_ridership.py`의 `duplicate_cell_inventory()`와 같은 방식으로 **두 행을
그대로 남기고 인벤토리로 드러낸다** — 소비하는 쪽(패널 편입 단계)이 이 26개 역-일-구분
조합을 결측으로 볼지, 다른 방식으로 처리할지 결정한다.

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

    `parsers_crowd_daily_ridership.py`와 이름·형태를 맞췄다 — 이쪽도 값을 임의로 고르지
    않고 그대로 드러내는 원칙을 따른다.
    """
    key = ["date", "station_no", "time_slot", "direction"]
    dup_mask = df.duplicated(subset=key, keep=False)
    return df[dup_mask].sort_values(key)


def save_interim(df: pd.DataFrame) -> Path:
    INTERIM_DIR.mkdir(parents=True, exist_ok=True)
    out_path = INTERIM_DIR / "crowd_line9_daily_ridership_long.parquet"
    df.to_parquet(out_path, index=False)
    return out_path


def main() -> None:
    df = build_line9_daily_long()
    dups = duplicate_cell_inventory(df)
    out_path = save_interim(df)
    print(
        f"저장 완료: {out_path} ({len(df):,}행, "
        f"{df['date'].min().date()} ~ {df['date'].max().date()}, "
        f"역 {df['station_no'].nunique()}개)"
    )
    if len(dups):
        affected = dups.drop_duplicates(["date", "station_no", "direction"])
        print(
            f"[경고] 중복 키 {len(dups):,}행 — 값이 서로 다른데 원천에 설명이 없어 임의로 "
            f"고르지 않고 둘 다 남겼다. 영향받는 (날짜, 역, 방향) 조합 {len(affected):,}건:"
        )
        print(affected[["date", "station_no", "station_name", "direction"]].to_string(index=False))


if __name__ == "__main__":
    main()
