"""CROWD 조회 로직 — 배치 잡이 저장한 예측 표(parquet)만 읽는다.

모델·lightgbm·재귀식은 여기서 import하지 않는다. 서빙 경로는 pandas·pyarrow만 쓴다
(`AI/CLAUDE.md`). 표는 날짜별 파일이고 mtime이 바뀌면 다시 읽는다(배치가 덮어써도 재시작 불필요).
"""

from __future__ import annotations

import json
import math
from datetime import date as date_type
from pathlib import Path

import pandas as pd

from app.core.config import Settings, get_settings


class PredictionStore:
    def __init__(self, serving_dir: Path) -> None:
        self.dir = Path(serving_dir)
        self._cache: dict[str, tuple[float, pd.DataFrame, dict]] = {}

    def _path(self, day: date_type) -> Path:
        return self.dir / f"predictions_{day:%Y-%m-%d}.parquet"

    def available_dates(self) -> list[date_type]:
        if not self.dir.exists():
            return []
        out = []
        for p in sorted(self.dir.glob("predictions_*.parquet")):
            try:
                out.append(pd.Timestamp(p.stem.split("_", 1)[1]).date())
            except ValueError:
                continue
        return out

    def load(self, day: date_type) -> tuple[pd.DataFrame, dict] | None:
        path = self._path(day)
        if not path.exists():
            return None
        mtime = path.stat().st_mtime
        key = str(day)
        cached = self._cache.get(key)
        if cached and cached[0] == mtime:
            return cached[1], cached[2]
        frame = pd.read_parquet(path)
        meta_path = path.with_suffix(".meta.json")
        meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
        self._cache[key] = (mtime, frame, meta)
        return frame, meta


_store: PredictionStore | None = None


def get_store(settings: Settings | None = None) -> PredictionStore:
    global _store
    settings = settings or get_settings()
    if _store is None or _store.dir != Path(settings.crowd_serving_dir):
        _store = PredictionStore(settings.crowd_serving_dir)
    return _store


def _num(v) -> float | None:
    return None if v is None or (isinstance(v, float) and math.isnan(v)) else float(v)


def _int(v) -> int | None:
    f = _num(v)
    return None if f is None else int(f)


def station_congestion(
    day: date_type, station_no: int, direction: str | None = None
) -> dict | None:
    """역 하나의 하루치 30분 슬롯. 표가 없으면 None, 역이 없으면 빈 slots."""
    loaded = get_store().load(day)
    if loaded is None:
        return None
    frame, meta = loaded
    rows = frame[frame["station_no"] == station_no]
    if direction:
        rows = rows[rows["direction"] == direction]
    rows = rows.sort_values(["direction", "time_slot_30min"])
    first = rows.iloc[0] if len(rows) else None
    return {
        "date": day,
        "station_no": station_no,
        "station_name": None if first is None else first["station_name"],
        "line": None if first is None else first["line"],
        "train_capacity": None if first is None else _int(first["train_capacity"]),
        "predictor_version": meta.get("predictor_version"),
        "lag1d_available": meta.get("lag1d_available"),
        "slots": [
            {
                "time_slot_30min": r["time_slot_30min"],
                "direction": r["direction"],
                "congestion_pct": _num(r["congestion_pct"]),
                "grade": _int(r["grade"]),
                "data_status": r["data_status"],
                "pred_source": r["pred_source"],
            }
            for _, r in rows.iterrows()
        ],
    }


def line_congestion(day: date_type, line: str, time_slot_30min: str) -> dict | None:
    loaded = get_store().load(day)
    if loaded is None:
        return None
    frame, _ = loaded
    rows = frame[(frame["line"] == line) & (frame["time_slot_30min"] == time_slot_30min)]
    rows = rows.sort_values(["direction", "station_no"])
    return {
        "date": day,
        "line": line,
        "time_slot_30min": time_slot_30min,
        "stations": [
            {
                "station_no": int(r["station_no"]),
                "station_name": r["station_name"],
                "direction": r["direction"],
                "congestion_pct": _num(r["congestion_pct"]),
                "grade": _int(r["grade"]),
                "data_status": r["data_status"],
                "pred_source": r["pred_source"],
            }
            for _, r in rows.iterrows()
        ],
    }


def crowd_meta() -> dict:
    store = get_store()
    dates = store.available_dates()
    latest = store.load(dates[-1])[1] if dates else {}
    settings = get_settings()
    return {
        "available_dates": dates,
        "grade_thresholds": latest.get("grade_thresholds", settings.grade_thresholds),
        "predictor": latest.get("predictor"),
        "predictor_version": latest.get("predictor_version"),
        "generated_at": latest.get("generated_at"),
        "status_counts": latest.get("status_counts"),
        "topology_gaps": latest.get("topology_gaps"),
    }
