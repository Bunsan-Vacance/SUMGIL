"""BIKE 조회 로직 — 배치 잡이 저장한 단일 최신 표(parquet)만 읽는다.

CROWD(`app/CROWD/service.py`)와 같은 원칙("서빙 경로는 가벼운 의존성만" — `AI/CLAUDE.md`,
모델·lightgbm은 여기서 import하지 않는다)이지만 저장 구조가 다르다 — CROWD는 날짜별
파일(predictions_YYYY-MM-DD.parquet)인데, `bike_stock_pred`는 기본키가
`rental_id·dow_type·time_slot`이라 날짜 축이 없다. 그래서 여기서는 디렉터리에서
**가장 최신 파일 하나**를 찾아 읽는다(파일이 바뀌면 mtime으로 감지해 재로딩).
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from app.core.config import Settings, get_settings

FILE_GLOB = "bike_stock_pred_*.parquet"


class BikeStockStore:
    def __init__(self, serving_dir: Path) -> None:
        self.dir = Path(serving_dir)
        self._cache: tuple[float, str, pd.DataFrame, dict] | None = None

    def _latest_path(self) -> Path | None:
        if not self.dir.exists():
            return None
        paths = sorted(self.dir.glob(FILE_GLOB))
        return paths[-1] if paths else None

    def load(self) -> tuple[pd.DataFrame, dict] | None:
        path = self._latest_path()
        if path is None:
            return None
        mtime = path.stat().st_mtime
        if self._cache and self._cache[0] == mtime and self._cache[1] == str(path):
            return self._cache[2], self._cache[3]
        frame = pd.read_parquet(path)
        meta_path = path.with_suffix(".meta.json")
        meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
        self._cache = (mtime, str(path), frame, meta)
        return frame, meta


_store: BikeStockStore | None = None


def get_store(settings: Settings | None = None) -> BikeStockStore:
    global _store
    settings = settings or get_settings()
    if _store is None or _store.dir != Path(settings.bike_serving_dir):
        _store = BikeStockStore(settings.bike_serving_dir)
    return _store


def _num(v) -> float | None:
    import math

    return None if v is None or (isinstance(v, float) and math.isnan(v)) else float(v)


def station_stock(rental_id: str, dow_type: int | None = None) -> dict | None:
    """대여소 하나의 슬롯별 재고 예측. 표가 없으면 None, 대여소가 없으면 빈 slots."""
    loaded = get_store().load()
    if loaded is None:
        return None
    frame, _ = loaded
    rows = frame[frame["rental_id"] == rental_id]
    if dow_type is not None:
        rows = rows[rows["dow_type"] == dow_type]
    rows = rows.sort_values(["dow_type", "time_slot"])
    return {
        "rental_id": rental_id,
        "station_name": None,  # bike_stock_pred엔 이름이 없음 — BE가 station master로 조합
        "slots": [
            {
                "dow_type": int(r["dow_type"]),
                "time_slot": int(r["time_slot"]),
                "exp_bikes": _num(r["exp_bikes"]),
                "p_empty": _num(r["p_empty"]),
                "p_full": _num(r["p_full"]),
                "source": r.get("source"),
            }
            for _, r in rows.iterrows()
        ],
    }


def bike_meta() -> dict:
    loaded = get_store().load()
    if loaded is None:
        return {"generated_at": None, "source": None, "rows": None, "stations": None}
    frame, meta = loaded
    return {
        "generated_at": meta.get("generated_at"),
        "source": meta.get("source"),
        "rows": len(frame),
        "stations": frame["rental_id"].nunique(),
    }
