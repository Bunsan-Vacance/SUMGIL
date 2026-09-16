"""사립학교교직원연금공단 공휴일 관리 정보(수동 다운로드 CSV) → data/EXTERNAL/holiday/interim/*.parquet.

원본은 1980년부터 커버하는 일자별 공휴일 여부 테이블이다(컬럼: 일자, 공휴일여부(Y/N),
영어요일명, 한국어요일명). 대체공휴일 여부·공휴일명은 이 원본에 없다 — 있는 그대로
`is_holiday` 불리언만 만든다(없는 정보를 지어내지 않는다).

실행:
    cd AI
    python -m DATA_ENGINE.eda.parsers_holiday
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

AI_ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = AI_ROOT / "data" / "EXTERNAL" / "holiday" / "raw"
INTERIM_DIR = AI_ROOT / "data" / "EXTERNAL" / "holiday" / "interim"

_COLUMN_MAP = {
    "일자": "date",
    "공휴일여부": "is_holiday_raw",
    "영어요일명": "weekday_en",
    "한국어요일명": "weekday_ko",
}


def load_holiday_csv(path: str | Path) -> pd.DataFrame:
    df = pd.read_csv(path, encoding="utf-8-sig")
    df = df.rename(columns=_COLUMN_MAP)[list(_COLUMN_MAP.values())].copy()
    df["date"] = pd.to_datetime(df["date"])
    df["is_holiday"] = df["is_holiday_raw"] == "Y"
    return df.drop(columns="is_holiday_raw")


def build_holiday_calendar(raw_dir: Path = RAW_DIR) -> pd.DataFrame:
    csv_paths = sorted(raw_dir.glob("*.csv"))
    if not csv_paths:
        raise FileNotFoundError(f"{raw_dir} 에서 공휴일 csv 원본을 찾지 못했습니다.")
    if len(csv_paths) > 1:
        raise ValueError(
            f"{raw_dir} 에 파일이 여러 개 있습니다({[p.name for p in csv_paths]}) — "
            "어느 걸 정본으로 쓸지 확인 필요, 자동으로 합치지 않는다."
        )
    return load_holiday_csv(csv_paths[0])


def duplicate_date_inventory(df: pd.DataFrame) -> pd.DataFrame:
    dup_mask = df.duplicated(subset="date", keep=False)
    return df[dup_mask].sort_values("date")


def save_interim(df: pd.DataFrame) -> Path:
    INTERIM_DIR.mkdir(parents=True, exist_ok=True)
    out_path = INTERIM_DIR / "holiday_calendar.parquet"
    df.to_parquet(out_path, index=False)
    return out_path


def main() -> None:
    df = build_holiday_calendar()
    dups = duplicate_date_inventory(df)
    out_path = save_interim(df)
    print(
        f"저장 완료: {out_path} ({len(df):,}행, "
        f"{df['date'].min().date()} ~ {df['date'].max().date()}, "
        f"공휴일 {int(df['is_holiday'].sum()):,}일, 중복 날짜 {len(dups)}건)"
    )


if __name__ == "__main__":
    main()
