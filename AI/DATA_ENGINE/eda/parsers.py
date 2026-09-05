"""파일형 원본(수동 다운로드) → data/interim/*.parquet 정규화 파서.

대상: 따릉이 대여이력(OA-15182), 대여소별 5분단위(OA-21229), 대여소 마스터
(OA-21235/OA-13252). 다운로드 위치·안내는 reports/download_guide.md 참고.

실행 예:
    cd AI
    python -m DATA_ENGINE.eda.parsers rental_history data/raw/bike/rental_history/2025년01월.csv
"""

from __future__ import annotations

import argparse
import logging
import zipfile
from pathlib import Path

import chardet
import pandas as pd
import yaml

AI_ROOT = Path(__file__).resolve().parents[2]
COLUMN_MAP_PATH = AI_ROOT / "DATA_ENGINE" / "conf" / "column_map.yaml"
INTERIM_DIR = AI_ROOT / "data" / "interim"

logger = logging.getLogger("parsers")


def _load_column_map(dataset: str) -> dict[str, str]:
    mapping = yaml.safe_load(COLUMN_MAP_PATH.read_text(encoding="utf-8"))
    if dataset not in mapping:
        raise KeyError(f"conf/column_map.yaml 에 '{dataset}' 항목이 없습니다.")
    return mapping[dataset]


def _detect_encoding(path: Path) -> str:
    raw = path.read_bytes()[:200_000]
    guess = chardet.detect(raw)
    encoding = guess.get("encoding") or "cp949"
    logger.info(
        "인코딩 감지: %s (%s, confidence=%.2f)", path.name, encoding, guess.get("confidence", 0)
    )
    return encoding


def _read_csv_any_encoding(path: Path) -> pd.DataFrame:
    encoding = _detect_encoding(path)
    try:
        return pd.read_csv(path, encoding=encoding)
    except (UnicodeDecodeError, LookupError):
        logger.warning("%s 인코딩 실패(%s), cp949로 재시도", path.name, encoding)
        return pd.read_csv(path, encoding="cp949")


def _normalize(df: pd.DataFrame, dataset: str) -> pd.DataFrame:
    column_map = _load_column_map(dataset)
    missing = set(df.columns) - set(column_map)
    if missing:
        logger.warning(
            "%s: column_map.yaml에 없는 컬럼 %s — 원본 헤더가 바뀌었을 수 있음, conf/column_map.yaml 확인 필요",
            dataset,
            sorted(missing),
        )
    return df.rename(columns=column_map)


def parse_rental_history(csv_path: Path) -> Path:
    df = _read_csv_any_encoding(csv_path)
    df = _normalize(df, "rental_history")
    out_path = INTERIM_DIR / f"rental_history_{csv_path.stem}.parquet"
    df.to_parquet(out_path, index=False)
    logger.info("저장: %s (%d rows)", out_path, len(df))
    return out_path


def parse_station_5min(zip_path: Path) -> list[Path]:
    out_paths: list[Path] = []
    with zipfile.ZipFile(zip_path) as zf:
        for name in zf.namelist():
            if not name.lower().endswith(".csv"):
                continue
            with zf.open(name) as f:
                raw = f.read()
            encoding = chardet.detect(raw[:200_000]).get("encoding") or "cp949"
            import io

            df = pd.read_csv(io.BytesIO(raw), encoding=encoding)
            df = _normalize(df, "station_5min")
            out_path = INTERIM_DIR / f"station_5min_{Path(name).stem}.parquet"
            df.to_parquet(out_path, index=False)
            out_paths.append(out_path)
            logger.info("저장: %s (%d rows)", out_path, len(df))
    return out_paths


def parse_station_master(path: Path) -> Path:
    if path.suffix.lower() in {".xlsx", ".xls"}:
        df = pd.read_excel(path)
    else:
        df = _read_csv_any_encoding(path)
    df = _normalize(df, "station_master")
    out_path = INTERIM_DIR / f"station_master_{path.stem}.parquet"
    df.to_parquet(out_path, index=False)
    logger.info("저장: %s (%d rows)", out_path, len(df))
    return out_path


_PARSERS = {
    "rental_history": parse_rental_history,
    "station_5min": parse_station_5min,
    "station_master": parse_station_master,
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", choices=sorted(_PARSERS))
    parser.add_argument("path", type=Path)
    args = parser.parse_args()

    INTERIM_DIR.mkdir(parents=True, exist_ok=True)
    _PARSERS[args.dataset](args.path)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s"
    )
    main()
