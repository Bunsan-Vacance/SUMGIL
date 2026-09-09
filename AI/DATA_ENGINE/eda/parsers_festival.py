"""전국 문화축제 표준데이터(KC_488, 문화체육관광부) 원본 → data/EXTERNAL/events/interim/*.parquet.

원본은 전국 대상 연도별 CSV다. 우리 서비스 범위는 서울·경기·인천(수도권)뿐이라, 1차 가공에서
이 세 시도만 남긴다 — 지방 축제까지 그대로 두면 혼잡도 피처 후보로서는 노이즈일 뿐이다.
역 반경 매칭(EXTERNAL/station의 역사마스터와 좌표 조인) 같은 2차 가공은 이번 범위에 넣지
않았다 — 여기서는 "수도권만 걸러 tidy하게 정리"까지만 한다.

실행:
    cd AI
    python -m DATA_ENGINE.eda.parsers_festival
"""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

AI_ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = AI_ROOT / "data" / "EXTERNAL" / "events" / "raw" / "festival"
INTERIM_DIR = AI_ROOT / "data" / "EXTERNAL" / "events" / "interim"

# 원본 CTPRVN_NM 표기 그대로 — 재라벨링하지 않는다.
CAPITAL_PROVINCES = ["서울특별시", "경기도", "인천광역시"]

_COLUMN_MAP = {
    "ID": "festival_id",
    "FCLTY_NM": "name",
    "CTPRVN_NM": "province",
    "SIGNGU_NM": "district",
    "OPMTN_PLACE_NM": "venue",
    "FCLTY_LO": "lon",
    "FCLTY_LA": "lat",
    "FSTVL_BEGIN_DE": "start_date",
    "FSTVL_END_DE": "end_date",
    "FSTVL_CN": "description",
    "MNNST_NM": "host",
}

_FILENAME_YEAR_PATTERN = re.compile(r"(20\d{2})")


def load_festival_csv(path: str | Path, year: int | None = None) -> pd.DataFrame:
    """KC_488_WNTY_CLTFSTVL_<year>.csv 한 개를 로드해 컬럼만 정리한다. 지역 필터링은 하지 않는다.

    `year`를 넘기지 않으면 파일명에서 4자리 연도를 정규식으로 추출한다(parsers_crowd.py의
    9호선 워크북 로더와 동일한 관례).
    """
    if year is None:
        match = _FILENAME_YEAR_PATTERN.search(Path(path).name)
        if match is None:
            raise ValueError(f"파일명에서 연도를 추출할 수 없습니다: {path}")
        year = int(match.group(1))

    df = pd.read_csv(path, encoding="utf-8-sig")
    df = df.rename(columns=_COLUMN_MAP)[list(_COLUMN_MAP.values())].copy()
    df["start_date"] = pd.to_datetime(df["start_date"], errors="coerce")
    df["end_date"] = pd.to_datetime(df["end_date"], errors="coerce")
    df["source_year"] = year
    return df


def filter_capital_area(df: pd.DataFrame) -> pd.DataFrame:
    """서울·경기·인천만 남긴다 — 전국 데이터 중 서비스 범위 밖은 노이즈일 뿐이다."""
    return df[df["province"].isin(CAPITAL_PROVINCES)].reset_index(drop=True)


def build_capital_festival_long(raw_dir: Path = RAW_DIR) -> pd.DataFrame:
    """raw_dir 안의 연도별 CSV를 전부 읽어 합치고 수도권만 남긴 tidy long-format을 반환한다."""
    csv_paths = sorted(raw_dir.glob("KC_488_WNTY_CLTFSTVL_*.csv"))
    if not csv_paths:
        raise FileNotFoundError(
            f"{raw_dir} 에서 KC_488_WNTY_CLTFSTVL_*.csv 원본을 찾지 못했습니다."
        )

    frames = [load_festival_csv(path) for path in csv_paths]
    combined = pd.concat(frames, ignore_index=True)
    return filter_capital_area(combined)


def save_interim(df: pd.DataFrame) -> Path:
    INTERIM_DIR.mkdir(parents=True, exist_ok=True)
    out_path = INTERIM_DIR / "festival_capital.parquet"
    df.to_parquet(out_path, index=False)
    return out_path


def main() -> None:
    df = build_capital_festival_long()
    out_path = save_interim(df)
    years = sorted(df["source_year"].unique().tolist())
    print(f"저장 완료: {out_path} ({len(df):,}행, {years}년)")


if __name__ == "__main__":
    main()
