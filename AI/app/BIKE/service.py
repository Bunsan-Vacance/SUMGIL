"""BIKE 조회 로직 — 배치 잡이 저장한 단일 최신 표(parquet)만 읽는다.

CROWD(`app/CROWD/service.py`)와 같은 원칙("서빙 경로는 가벼운 의존성만" — `AI/CLAUDE.md`,
모델·lightgbm은 여기서 import하지 않는다)이지만 저장 구조가 다르다 — CROWD는 날짜별
파일(predictions_YYYY-MM-DD.parquet)인데, `bike_stock_pred`는 기본키가
`rental_id·dow_type·time_slot`이라 날짜 축이 없다. 그래서 여기서는 디렉터리에서
**가장 최신 파일 하나**를 찾아 읽는다(파일이 바뀌면 mtime으로 감지해 재로딩).
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

from app.BIKE.pipeline import calendar
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


class LiveStockStore:
    """Kafka 컨슈머가 station별 upsert로 유지하는 실시간 재고 스냅샷.

    `bike_live_stock_path`의 parquet(컬럼: rental_id·current_stock·updated_at)을
    `BikeStockStore`와 동일한 mtime 캐시 방식으로 읽는다. Redis가 아니라 컨슈머와
    서빙 앱이 파일시스템을 공유한다는 전제 위에서 동작한다(`app/core/config.py` 참고).
    """

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._cache: tuple[float, pd.DataFrame] | None = None

    def load(self) -> pd.DataFrame | None:
        if not self.path.exists():
            return None
        mtime = self.path.stat().st_mtime
        if self._cache is not None and self._cache[0] == mtime:
            return self._cache[1]
        frame = pd.read_parquet(self.path)
        self._cache = (mtime, frame)
        return frame


_live_store: LiveStockStore | None = None


def get_live_stock_store(settings: Settings | None = None) -> LiveStockStore:
    global _live_store
    settings = settings or get_settings()
    if _live_store is None or _live_store.path != Path(settings.bike_live_stock_path):
        _live_store = LiveStockStore(settings.bike_live_stock_path)
    return _live_store


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


class LiveStockMissing(RuntimeError):
    """실시간 재고 없음 — 파일 없음 / 역 없음 / 값이 오래됨(stale) 셋 다 동일하게 취급한다."""


class AvgDataMissing(RuntimeError):
    """avg 표 자체가 없거나, 해당 station·dow_type·time_slot 조합에 표본이 없음."""


def _read_live_stock(rental_id: str, now: datetime, settings: Settings) -> int | None:
    frame = get_live_stock_store().load()
    if frame is None:
        return None

    rows = frame[frame["rental_id"].astype(str) == str(rental_id)]
    if rows.empty:
        return None

    row = rows.iloc[0]
    updated_at = pd.Timestamp(row["updated_at"]).to_pydatetime()
    age_seconds = (now - updated_at).total_seconds()
    if age_seconds > settings.bike_live_stock_max_staleness_seconds:
        return None

    return int(row["current_stock"])


def _lookup_avg_row(frame: pd.DataFrame, rental_id: str, dow_type: int, time_slot: int):
    mask_id = frame["rental_id"].astype(str) == str(rental_id)
    mask_dow = frame["dow_type"] == dow_type
    mask_slot = frame["time_slot"] == time_slot
    rows = frame[mask_id & mask_dow & mask_slot]
    if rows.empty:
        return None
    return rows.iloc[0]


def predict_eta_stock(rental_id: str, eta_minutes: int, now: datetime | None = None) -> dict:
    """실시간 재고(로컬 파일) + avg 표 델타로 도착 시점 재고를 예측한다.

    델타 계산은 avg 예측기 표(`bike_stock_pred_*.parquet`)의 도착 슬롯 exp_bikes와
    현재 슬롯 exp_bikes 차이를 쓴다 — 나중에 anchor+horizon 모델로 교체할 때도 이
    함수의 시그니처/반환값은 바뀌지 않는다(교체 지점은 `delta` 계산 한 줄뿐).
    """
    settings = get_settings()
    if now is None:
        now = pd.Timestamp.now()
    arrival = now + timedelta(minutes=eta_minutes)

    live_stock = _read_live_stock(rental_id, now, settings)
    if live_stock is None:
        raise LiveStockMissing(f"{rental_id} 실시간 재고 없음(파일 없음/역 없음/오래됨)")

    loaded = get_store().load()
    if loaded is None:
        raise AvgDataMissing("bike_stock_pred 표가 없다 - 배치 미실행")
    frame, _ = loaded

    holidays = calendar.get_holidays_cached()
    now_dow, now_slot = calendar.dow_type_and_time_slot(now, holidays)
    arr_dow, arr_slot = calendar.dow_type_and_time_slot(arrival, holidays)

    current_row = _lookup_avg_row(frame, rental_id, now_dow, now_slot)
    arrival_row = _lookup_avg_row(frame, rental_id, arr_dow, arr_slot)

    if current_row is None:
        current_exp = None
    else:
        current_exp = _num(current_row["exp_bikes"])

    if arrival_row is None:
        arrival_exp = None
    else:
        arrival_exp = _num(arrival_row["exp_bikes"])

    if current_exp is None or arrival_exp is None:
        detail = f"{rental_id} dow_type {now_dow}->{arr_dow} slot {now_slot}->{arr_slot} 표본 없음"
        raise AvgDataMissing(detail)

    delta = arrival_exp - current_exp
    predicted_stock = max(0.0, live_stock + delta)

    return {
        "rental_id": rental_id,
        "eta_minutes": eta_minutes,
        "current_stock": live_stock,
        "predicted_stock": predicted_stock,
        "p_empty": _num(arrival_row["p_empty"]),
        "p_full": _num(arrival_row["p_full"]),
        "arrival_dow_type": arr_dow,
        "arrival_time_slot": arr_slot,
        "source": "avg",
    }
