"""전국 문화축제 표준데이터(KC_488, 문화체육관광부) 원본 → data/EXTERNAL/events/interim/*.parquet.

원본은 전국 대상 연도별 CSV다. 우리 서비스 범위는 서울·경기·인천(수도권)뿐이라, 1차 가공에서
이 세 시도만 남긴다 — 지방 축제까지 그대로 두면 혼잡도 피처 후보로서는 노이즈일 뿐이다.
역 반경 매칭(EXTERNAL/station의 역사마스터와 좌표 조인) 같은 2차 가공은 이번 범위에 넣지
않았다 — 여기서는 "수도권만 걸러 tidy하게 정리"까지만 한다.

## 중복 등록을 여기서 걸러낸다

원본은 같은 축제를 연도 파일마다, 때로는 같은 파일 안에서도 **다른 ID로 반복 등록한다**
(수도권 802행 중 50행이 23개 축제의 중복). `map_events_to_stations.py`가 `festival_id`의
nunique로 역·날짜별 축제 수를 세기 때문에, 중복을 남기면 그 축제가 열린 날의 개수가
2~4배로 잡힌다 — 피처가 조용히 과대계상된다.

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

# 이름·기간·좌표가 모두 같으면 같은 축제로 본다. ID는 원본이 중복 발급하므로 판단 근거로
# 쓸 수 없다.
_DEDUPE_KEYS = ["name", "start_date", "end_date", "lat", "lon"]

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


def drop_duplicate_festivals(df: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """이름·기간·좌표가 같은 중복 등록을 하나로 합치고, 제거한 행 수를 함께 돌려준다.

    제거 건수를 같이 돌려주는 이유는 `main()`이 그 수를 출력해야 하기 때문이다 — 중복이
    조용히 사라지면 원본이 몇 건이었는지 추적할 수 없다.
    """
    before = len(df)
    deduped = df.drop_duplicates(_DEDUPE_KEYS).reset_index(drop=True)
    return deduped, before - len(deduped)


def build_capital_festival_long(raw_dir: Path = RAW_DIR) -> pd.DataFrame:
    """raw_dir 안의 연도별 CSV를 전부 읽어 합치고 수도권만 남긴 tidy long-format을 반환한다."""
    csv_paths = sorted(raw_dir.glob("KC_488_WNTY_CLTFSTVL_*.csv"))
    if not csv_paths:
        raise FileNotFoundError(
            f"{raw_dir} 에서 KC_488_WNTY_CLTFSTVL_*.csv 원본을 찾지 못했습니다."
        )

    frames = [load_festival_csv(path) for path in csv_paths]
    combined = pd.concat(frames, ignore_index=True)
    deduped, _ = drop_duplicate_festivals(filter_capital_area(combined))
    return deduped


def save_interim(df: pd.DataFrame) -> Path:
    INTERIM_DIR.mkdir(parents=True, exist_ok=True)
    out_path = INTERIM_DIR / "festival_capital.parquet"
    df.to_parquet(out_path, index=False)
    return out_path


def main() -> None:
    csv_paths = sorted(RAW_DIR.glob("KC_488_WNTY_CLTFSTVL_*.csv"))
    if not csv_paths:
        raise FileNotFoundError(
            f"{RAW_DIR} 에서 KC_488_WNTY_CLTFSTVL_*.csv 원본을 찾지 못했습니다."
        )

    capital = filter_capital_area(
        pd.concat([load_festival_csv(p) for p in csv_paths], ignore_index=True)
    )
    df, removed = drop_duplicate_festivals(capital)
    if removed:
        print(
            f"[안내] 이름·기간·좌표가 같은 중복 등록 {removed}행을 제거했다 "
            f"(수도권 {len(capital):,}행 → {len(df):,}행)."
        )

    out_path = save_interim(df)
    years = sorted(df["source_year"].unique().tolist())
    print(f"저장 완료: {out_path} ({len(df):,}행, {years}년)")


if __name__ == "__main__":
    main()
