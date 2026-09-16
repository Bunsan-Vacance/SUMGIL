"""기상청 ASOS 종관기상관측 시간자료(수동 다운로드 CSV) → data/EXTERNAL/weather/interim/*.parquet.

data.kma.go.kr에서 지점 108(서울) 시간자료를 연도별로 받은 CSV를 합친다. 원본은 cp949
인코딩에 한글 헤더("기온(°C)" 등)다 — 인코딩이 깨져 보이는 건 뷰어가 cp949를 utf-8로
잘못 열었을 때뿐이고 파일 자체는 정상이다.

`AI/DATA_ENGINE/collect/weather_asos_backfill.py`(API 백필)의 46개 필드 응답과는 컬럼
이름·형태가 다르다 — 그쪽은 API 원문 필드명(ta, rn, ws, wd, hm ...)을 그대로 쓰고, 이쪽은
수동 다운로드 CSV의 한글 헤더를 쓴다. 두 경로가 합쳐질 필요가 생기면 그때 공통 스키마로
맞춘다(지금은 필요 없다 — API 백필은 아직 실행된 적이 없다).

실행:
    cd AI
    python -m DATA_ENGINE.eda.parsers_weather
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

AI_ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = AI_ROOT / "data" / "EXTERNAL" / "weather" / "raw" / "asos"
INTERIM_DIR = AI_ROOT / "data" / "EXTERNAL" / "weather" / "interim"

# 원본 한글 헤더 → snake_case. 응답에 있는 컬럼 중 논문들이 상위 중요도로 꼽은 항목
# (기온·강수량·습도·풍속·일사량·풍향) 위주로만 옮긴다 — 지중온도 등 8종 초과분은 필요해지면 추가.
_COLUMN_MAP = {
    "지점": "station_id",
    "일시": "datetime",
    "기온(°C)": "temp_c",
    "강수량(mm)": "precip_mm",
    "풍속(m/s)": "wind_ms",
    "풍향(16방위)": "wind_dir16",
    "습도(%)": "humidity_pct",
    "일조(hr)": "sunshine_hr",
    "일사(MJ/m2)": "solar_mj",
    "적설(cm)": "snow_cm",
}


def load_asos_csv(path: str | Path) -> pd.DataFrame:
    """ASOS 시간자료 CSV 한 개를 로드해 컬럼만 정리한다. 결측(NaN)은 채우지 않는다.

    강수량·일조·일사·적설은 관측값이 없으면(비/눈/일조가 없었던 시간) 원본이 빈 칸으로
    남기는데, 이걸 0으로 채우면 "미관측"과 "0"이 구분되지 않는다 — 그대로 NaN으로 둔다.
    """
    df = pd.read_csv(path, encoding="cp949")
    df = df.rename(columns=_COLUMN_MAP)[list(_COLUMN_MAP.values())].copy()
    df["datetime"] = pd.to_datetime(df["datetime"])
    return df


def build_asos_hourly(raw_dir: Path = RAW_DIR) -> pd.DataFrame:
    """raw_dir 안의 연도별 CSV를 전부 읽어 시간순으로 합친다. 중복 시각은 평균으로 뭉개지 않고
    그대로 남겨 호출부에서 확인할 수 있게 한다."""
    csv_paths = sorted(raw_dir.glob("*.csv"))
    if not csv_paths:
        raise FileNotFoundError(f"{raw_dir} 에서 ASOS csv 원본을 찾지 못했습니다.")

    frames = [load_asos_csv(path) for path in csv_paths]
    combined = pd.concat(frames, ignore_index=True)
    return combined.sort_values("datetime").reset_index(drop=True)


def duplicate_datetime_inventory(df: pd.DataFrame) -> pd.DataFrame:
    """같은 시각이 여러 연도 파일에 중복으로 들어있는 행을 그대로 나열한다(제거하지 않음)."""
    dup_mask = df.duplicated(subset="datetime", keep=False)
    return df[dup_mask].sort_values("datetime")


def save_interim(df: pd.DataFrame) -> Path:
    INTERIM_DIR.mkdir(parents=True, exist_ok=True)
    out_path = INTERIM_DIR / "asos_hourly.parquet"
    df.to_parquet(out_path, index=False)
    return out_path


def main() -> None:
    df = build_asos_hourly()
    dups = duplicate_datetime_inventory(df)
    out_path = save_interim(df)
    print(
        f"저장 완료: {out_path} ({len(df):,}행, "
        f"{df['datetime'].min()} ~ {df['datetime'].max()}, 중복 시각 {len(dups)}건)"
    )


if __name__ == "__main__":
    main()
