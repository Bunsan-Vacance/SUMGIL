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

## 축제 "규모"를 이 원천에서 만들 수 없다

33개 컬럼을 전수 확인한 결과 **관람객수·방문객수·예산·규모에 해당하는 필드가 없다.** 경기
쪽은 `game_attendance`(실측 관중수)가 있는데 축제는 대응물이 없다. 분류 컬럼(LCLAS_NM·
MLSFC_NM)도 전 행이 `"행사"` 단일값이라 분산이 0이어서 대리 지표로도 못 쓴다.

그래서 `festival_attendance` 같은 이름의 추정 컬럼을 만들지 않는다 — 데이터 검증 리포트
**원칙 4**("산출 불가능한 지표는 이름을 바꾼다")에 걸린다. 대신 원본에서 실제로 관측되는
값만 정직한 이름으로 남긴다:

- `duration_days` — 개최 일수. 규모 자체는 아니지만 **1일 축제와 상설 전시를 가르는 축**이다.
- `sponsor` — 후원기관명. 산출물 775건 중 371건(48%)만 채워져 있어 분산이 있는 유일한 규모
  프록시지만, 관중수의 대체물로는 약하다.

## 개최 일수가 왜 필요한가

`festival_count`(역·날짜별 축제 수)만으로 학습했을 때 신호가 거의 없었던 원인이 희소성이
아니라 **구성 오염**이었다. 패널 구간(2024~2025) 안에서 역에 연결된 축제-역-일 8,942행 중
**83.6%가 개최 기간 31일 이상인 축제 16건에서 나왔다** — 서울아트쇼(231일), 박물관 기획전,
"차 없는 거리 축제"(155일)처럼 일별 유입이 평탄한 행사다. 반면 1일 축제 92건은 347행(3.9%)
뿐이라, 혼잡도를 실제로 밀어올리는 쪽이 개수 집계에서 소수가 된다.

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
    # 후원기관 — 규모 프록시. 원본 33컬럼에 관람객수·예산이 없어 규모를 직접 알 수 없고,
    # 대분류·중분류(LCLAS_NM·MLSFC_NM)는 전 행이 "행사" 단일값이라 분산이 0이다. 이 컬럼만
    # 원본 수도권 802건 중 372건(46%)이 채워져 있어 유일하게 분산이 있다(모듈 docstring 참고).
    "SUPRT_INSTT_NM": "sponsor",
}

# 이름·기간·좌표가 모두 같으면 같은 축제로 본다. ID는 원본이 중복 발급하므로 판단 근거로
# 쓸 수 없다.
_DEDUPE_KEYS = ["name", "start_date", "end_date", "lat", "lon"]

# 이 일수까지를 "인원이 몰리는 단기 축제"로 본다. 개최 일수의 중위가 2일, 75분위가 3일이라
# 여기서 끊었다. 임의 경계라서 소비하는 쪽(`map_events_to_stations.py`)이 연속값
# `festival_min_duration_days`도 함께 내보내 모델이 다른 경계를 고를 수 있게 해뒀다.
SPIKE_MAX_DAYS = 3

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


def add_duration_days(df: pd.DataFrame) -> pd.DataFrame:
    """개최 일수(`duration_days`)를 붙인다. 시작·종료 같은 날이면 1이다.

    이 값이 축제의 성격을 가른다 — 1~3일이면 특정 날짜에 인원이 몰리는 축제고, 수십~수백
    일이면 상설 전시·기획전처럼 일별 유입이 평탄한 행사다. 둘을 `festival_count` 하나로
    묶으면 후자가 개최일 수만큼 행을 차지해 전자의 신호를 덮는다.
    """
    out = df.copy()
    out["duration_days"] = (out["end_date"] - out["start_date"]).dt.days + 1
    return out


def find_reversed_dates(df: pd.DataFrame) -> pd.DataFrame:
    """종료일이 시작일보다 이른 행 — 원본 입력 오류다.

    이런 행은 `pd.date_range(start, end)`가 빈 배열이 되어 개최일 전개에서 **조용히**
    사라진다. 채워 넣을 근거가 없으므로(원칙 1) 값을 고치지는 않고, 몇 건이 빠졌는지
    드러내기 위해 따로 센다.
    """
    return df[df["duration_days"] <= 0]


def build_capital_festival_long(raw_dir: Path = RAW_DIR) -> pd.DataFrame:
    """raw_dir 안의 연도별 CSV를 전부 읽어 합치고 수도권만 남긴 tidy long-format을 반환한다."""
    csv_paths = sorted(raw_dir.glob("KC_488_WNTY_CLTFSTVL_*.csv"))
    if not csv_paths:
        raise FileNotFoundError(
            f"{raw_dir} 에서 KC_488_WNTY_CLTFSTVL_*.csv 원본을 찾지 못했습니다."
        )

    frames = [load_festival_csv(path) for path in csv_paths]
    combined = pd.concat(frames, ignore_index=True)
    capital = filter_capital_area(combined)
    deduped, _ = drop_duplicate_festivals(capital)
    return add_duration_days(deduped)


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
    deduped, removed = drop_duplicate_festivals(capital)
    if removed:
        print(
            f"[안내] 이름·기간·좌표가 같은 중복 등록 {removed}행을 제거했다 (수도권 {len(capital):,}행 → {len(deduped):,}행)."
        )

    df = add_duration_days(deduped)

    reversed_rows = find_reversed_dates(df)
    if len(reversed_rows):
        print(
            f"\n[경고] 종료일이 시작일보다 이른 행 {len(reversed_rows)}건 — 개최일 전개에서 빠진다(값을 고치지 않는다):"
        )
        print(reversed_rows[["name", "province", "start_date", "end_date"]].to_string(index=False))

    spike = int((df["duration_days"].between(1, SPIKE_MAX_DAYS)).sum())
    standing = int((df["duration_days"] > SPIKE_MAX_DAYS).sum())
    print(
        f"\n[개최 일수] {SPIKE_MAX_DAYS}일 이하 {spike:,}건 / 초과 {standing:,}건 — "
        f"중위 {df['duration_days'].median():.0f}일, 최장 {df['duration_days'].max():.0f}일"
    )
    print(f"[규모 프록시] 후원기관 명시 {int(df['sponsor'].notna().sum()):,}건 / {len(df):,}건")

    out_path = save_interim(df)
    years = sorted(df["source_year"].unique().tolist())
    print(f"\n저장 완료: {out_path} ({len(df):,}행, {years}년)")


if __name__ == "__main__":
    main()
