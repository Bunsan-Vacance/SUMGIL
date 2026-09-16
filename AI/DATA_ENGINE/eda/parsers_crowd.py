"""지하철 혼잡도 스냅샷 원천(서울시 CSV, 9호선 xlsx) → data/CROWD/interim/*.parquet 파서.

두 원천 모두 날짜 컬럼이 없는 "대표 1주 평균" 스냅샷이다 — 요일별 시계열이 아니라
역×시간대×요일유형 단위의 정적 프로파일로 다뤄야 한다. 자세한 배경은
AI/validation/CROWD/README.md 참고.

실행:
    cd AI
    python -m DATA_ENGINE.eda.parsers_crowd
"""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

AI_ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = AI_ROOT / "data" / "CROWD" / "raw"
CROWD_INTERIM_DIR = AI_ROOT / "data" / "CROWD" / "interim"

_LINE9_SHEET_PATTERN = re.compile(
    r"^(?P<direction>상선|하선)(?P<train_type>일반|급행)\((?P<day_type>평일|휴일)\)$"
)
_LINE9_FILENAME_YEAR_PATTERN = re.compile(r"(20\d{2})")
_CSV_TIME_SLOT_PATTERN = re.compile(r"^(\d{1,2})시(\d{2})분$")
_XLSX_TIME_SLOT_PATTERN = re.compile(r"^(\d{2}:\d{2})~\d{2}:\d{2}$")


def _normalize_time_slot(raw: pd.Series, source: str) -> pd.Series:
    """두 원천의 시간대 표기를 "HH:MM"(구간 시작 기준) 공통 포맷으로 맞춘다.

    - seoul_1_8: "6시00분" 같은 시점 표기.
    - line9: "06:00~06:29" 같은 구간 표기 — '~' 앞부분만 취한다.
    """
    if source == "seoul_1_8":
        extracted = raw.str.extract(_CSV_TIME_SLOT_PATTERN)
        hour = extracted[0].astype(int).astype(str).str.zfill(2)
        minute = extracted[1]
        return hour + ":" + minute
    if source == "line9":
        return raw.str.extract(_XLSX_TIME_SLOT_PATTERN)[0]
    raise ValueError(f"알 수 없는 source: {source!r}")


def load_seoul_congestion_csv(path: str | Path) -> pd.DataFrame:
    """서울교통공사_지하철혼잡도정보.csv(1~8호선, 요일구분 스냅샷)를 long-format으로 로드.

    원본 컬럼: 요일구분, 호선, 역번호, 출발역, 상하구분 + 시간대별 컬럼(5시30분, 6시00분, ...).
    인코딩은 CP949다. 요일구분은 평일/토요일/일요일, 상하구분은 상선/하선(2호선만 내선/외선)이다
    — 9호선 원천(평일/휴일, 상선/하선만)과 체계가 다르니 합치지 않는다.

    **연도판마다 표기가 조금씩 다르다**(142에서 2023·2024판을 받아 확인). `연번` 컬럼이 붙은
    판(2023·2024)이 있고, `호선`이 `"1호선"`이 아니라 `1`인 판, 요일구분 값에 앞뒤 공백이
    들어간 판(`" 토요일 "`)도 있다. 시간대 컬럼은 `HH시MM분` 패턴으로만 고르고 나머지 표기는
    여기서 정규화해, 어느 연도판을 읽어도 같은 스키마가 나오게 한다.
    """
    df = pd.read_csv(path, encoding="cp949")
    df.columns = [str(c).strip() for c in df.columns]
    id_vars = ["요일구분", "호선", "역번호", "출발역", "상하구분"]
    for col in ("요일구분", "출발역", "상하구분"):
        df[col] = df[col].astype("string").str.strip()
    # `1` / `"1"` 표기를 `"1호선"`으로 맞춘다(2023·2024판).
    line = df["호선"].astype("string").str.strip()
    df["호선"] = line.where(~line.str.fullmatch(r"\d+"), line + "호선")
    # `연번` 같은 부가 컬럼이 시간대로 섞여 들어가지 않게 패턴으로만 고른다.
    time_cols = [c for c in df.columns if c not in id_vars and _CSV_TIME_SLOT_PATTERN.match(c)]
    long_df = df.melt(
        id_vars=id_vars, value_vars=time_cols, var_name="time_slot", value_name="congestion_pct"
    )
    long_df = long_df.rename(
        columns={
            "요일구분": "day_type",
            "호선": "line",
            "역번호": "station_no",
            "출발역": "station_name",
            "상하구분": "direction",
        }
    )
    long_df["time_slot"] = _normalize_time_slot(long_df["time_slot"], "seoul_1_8")
    long_df["source"] = "seoul_1_8"
    return long_df


def load_line9_workbook(path: str | Path, year: int | None = None) -> pd.DataFrame:
    """9호선 역별 시간별 혼잡도 xlsx(연도별)를 long-format으로 로드.

    시트는 방향×열차종별×요일유형 조합(예: "상선일반(평일)") 8개고, 시트마다 1행은
    "기준일자: ..." 대표주간 안내, 2행이 시간대 헤더, 3행부터 역별 값이다.
    `_xlnm._FilterDatabase` 같은 데이터가 아닌 시트는 건너뛴다.

    2020~2023년 파일은 실제 데이터가 40행 안쪽인데도 엑셀 서식이 시트 전체
    범위(최대 104만 행)까지 적용돼 있어 파일 용량이 부풀려져 있다 — 로드 자체는
    정상 동작하지만 참고할 것.

    `year`를 넘기지 않으면 파일명에서 4자리 연도를 정규식으로 추출한다.
    """
    if year is None:
        match = _LINE9_FILENAME_YEAR_PATTERN.search(Path(path).name)
        if match is None:
            raise ValueError(f"파일명에서 연도를 추출할 수 없습니다: {path}")
        year = int(match.group(1))

    sheets = pd.read_excel(path, sheet_name=None, header=1)
    frames = []
    for sheet_name, sheet_df in sheets.items():
        match = _LINE9_SHEET_PATTERN.match(sheet_name)
        if match is None:
            continue
        station_col = sheet_df.columns[0]
        time_cols = [c for c in sheet_df.columns[1:] if pd.notna(c)]
        long_df = sheet_df.melt(
            id_vars=[station_col],
            value_vars=time_cols,
            var_name="time_slot",
            value_name="congestion_pct",
        )
        long_df = long_df.rename(columns={station_col: "station_name"})
        long_df["year"] = year
        long_df["line"] = "9호선"
        for key, value in match.groupdict().items():
            long_df[key] = value
        frames.append(long_df)

    result = pd.concat(frames, ignore_index=True)
    result["time_slot"] = _normalize_time_slot(result["time_slot"], "line9")
    result["source"] = "line9"
    return result


def build_congestion_long(raw_dir: Path = RAW_DIR) -> pd.DataFrame:
    """raw_dir 안의 서울시 CSV 1개 + 9호선 xlsx 전부를 읽어 하나의 tidy long-format으로 합친다."""
    frames = []

    # raw/에는 88 이후 승하차·환승·역사마스터 CSV/xlsx도 함께 있어 파일명으로 좁힌다.
    csv_candidates = sorted(raw_dir.glob("*지하철혼잡도정보*.csv"))
    for csv_path in csv_candidates:
        frames.append(load_seoul_congestion_csv(csv_path))

    xlsx_candidates = sorted(raw_dir.glob("*9호선*혼잡도*.xlsx"))
    for xlsx_path in xlsx_candidates:
        frames.append(load_line9_workbook(xlsx_path))

    if not frames:
        raise FileNotFoundError(f"{raw_dir} 에서 csv/xlsx 원본을 찾지 못했습니다.")

    return pd.concat(frames, ignore_index=True)


def save_interim(df: pd.DataFrame) -> Path:
    CROWD_INTERIM_DIR.mkdir(parents=True, exist_ok=True)
    out_path = CROWD_INTERIM_DIR / "crowd_congestion_long.parquet"
    df.to_parquet(out_path, index=False)
    return out_path


def main() -> None:
    df = build_congestion_long()
    out_path = save_interim(df)
    print(f"저장 완료: {out_path} ({len(df):,} rows)")


if __name__ == "__main__":
    main()
