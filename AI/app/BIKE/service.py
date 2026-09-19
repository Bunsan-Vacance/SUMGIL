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
from app.BIKE.pipeline.predictor_eta import (  # noqa: F401 - router.py가 service.ModelUnavailable로 씀
    LightGBMEtaPredictor,
    ModelUnavailable,
    UnknownStation,
)
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


class LiveWeatherStore:
    """날씨 실시간 스냅샷(팀원이 별도 구축 중, `weather.nowcast` Kafka 토픽 기반).

    `LiveStockStore`와 동일한 mtime 캐시 방식. 역 단위가 아니라 도시 전체 단일 값이라
    파일엔 보통 한 행만 있다고 가정한다(ASOS 학습 데이터와 같은 전제).
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


_live_weather_store: LiveWeatherStore | None = None


def get_live_weather_store(settings: Settings | None = None) -> LiveWeatherStore:
    global _live_weather_store
    settings = settings or get_settings()
    if _live_weather_store is None or _live_weather_store.path != Path(
        settings.bike_live_weather_path
    ):
        _live_weather_store = LiveWeatherStore(settings.bike_live_weather_path)
    return _live_weather_store


_eta_predictor: LightGBMEtaPredictor | None = None


def get_eta_predictor(settings: Settings | None = None) -> LightGBMEtaPredictor:
    """anchor+horizon LightGBM(v4_weather) 지연 싱글톤 — `app/main.py`가 기동 시 warm-up으로
    미리 호출해서, 실제 요청은 콜드 스타트 비용을 안 떠안게 한다."""
    global _eta_predictor
    settings = settings or get_settings()
    if _eta_predictor is None or _eta_predictor.artifact_dir != Path(settings.bike_eta_model_dir):
        _eta_predictor = LightGBMEtaPredictor(
            settings.bike_eta_model_dir, settings.bike_station_master_path
        )
        _eta_predictor.ensure_loaded()  # warm-up 시점에 로딩 실패를 바로 드러낸다
    return _eta_predictor


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


def _read_live_stock_with_age(
    rental_id: str, now: datetime, settings: Settings
) -> tuple[int, float] | None:
    """LightGBM 경로 전용 — 재고값과 함께 "몇 분 전 값인지"(`minutes_since_stock_anchor`
    피처)도 같이 돌려준다. avg_delta 경로의 `_read_live_stock()`은 그대로 둔다."""
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

    return int(row["current_stock"]), age_seconds / 60.0


def _read_live_weather(now: datetime, settings: Settings) -> dict | None:
    """날씨 스냅샷 없거나 오래됐으면 `None`(모델 쪽에서 temp=0/is_rain=False로 폴백)."""
    frame = get_live_weather_store().load()
    if frame is None or frame.empty:
        return None

    row = frame.iloc[0]
    updated_at = pd.Timestamp(row["updated_at"]).to_pydatetime()
    age_seconds = (now - updated_at).total_seconds()
    if age_seconds > settings.bike_live_weather_max_staleness_seconds:
        return None

    return {"temp": float(row["temp"]), "is_rain": bool(row["is_rain"])}


def _lookup_avg_row(frame: pd.DataFrame, rental_id: str, dow_type: int, time_slot: int):
    mask_id = frame["rental_id"].astype(str) == str(rental_id)
    mask_dow = frame["dow_type"] == dow_type
    mask_slot = frame["time_slot"] == time_slot
    rows = frame[mask_id & mask_dow & mask_slot]
    if rows.empty:
        return None
    return rows.iloc[0]


def _predict_eta_stock_avg_delta(
    rental_id: str, eta_minutes: int, now: datetime | None = None
) -> dict:
    """[구버전, 임시 구현이었음 — 지금은 predict_eta_stock()이 안 씀]

    실시간 재고(로컬 파일) + avg 표 델타로 도착 시점 재고를 예측하던 avg_delta 방식.
    LightGBM(v4_weather, S15P21A104-160)으로 교체됐다. 롤백·비교용으로 코드만 남겨둔다
    — 지운 게 아니라 `predict_eta_stock`이라는 이름을 더 이상 안 쓸 뿐이다.
    """
    settings = get_settings()
    if now is None:
        now = calendar.now_kst()
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


def predict_eta_stock(rental_id: str, eta_minutes: int, now: datetime | None = None) -> dict:
    """실시간 재고 + LightGBM(anchor+horizon, v4_weather)이 직접 예측한 순증감으로
    도착 시점 재고를 낸다. 배치표(`bike_stock_pred`)는 이 경로에서 전혀 읽지 않는다 —
    그 표는 BE가 자체 DB로 적재해서 쓰는 폴백 전용이다(S15P21A104-159/-160 결정사항).

    확률(`p_empty`/`p_full`)은 모델 아티팩트 디렉터리에 이진분류 booster
    (`model_is_empty.txt`/`model_is_full.txt`, S15P21A104-160 Phase 6)가 있을 때만 채워지고,
    없으면 `None`이다 — `predictor_eta.LightGBMEtaPredictor`가 그 판단을 담당한다.

    `now`를 안 넘기면 `calendar.now_kst()`로 구한다 — `pd.Timestamp.now()`를 직접 쓰면
    AI EC2의 실제 OS 시간대(UTC)가 그대로 나와서 KST로 저장된 재고·날씨 `updated_at`과
    9시간 어긋난다(재고·날씨 신선도 체크와 모델 시간 피처가 전부 이 값을 쓰므로 영향이 크다).

    역이 학습 시점 목록에 없으면(`UnknownStation`, 신규 개설 대여소 등) 503으로 에러 내지
    않고 `predict_global_fallback()`(station 무관 전역 평균)으로 200을 준다 —
    `source`가 `lightgbm_global_fallback`으로 구분된다. 모델 아티팩트 자체가 망가진
    `ModelUnavailable`은 여전히 진짜 장애라 그대로 올려서 503으로 드러낸다.
    """
    settings = get_settings()
    if now is None:
        now = calendar.now_kst()
    arrival = now + timedelta(minutes=eta_minutes)

    live = _read_live_stock_with_age(rental_id, now, settings)
    if live is None:
        raise LiveStockMissing(f"{rental_id} 실시간 재고 없음(파일 없음/역 없음/오래됨)")
    live_stock, anchor_age_minutes = live

    weather = _read_live_weather(now, settings)

    predictor = get_eta_predictor()
    try:
        result = predictor.predict_delta(
            rental_id, live_stock, eta_minutes, now, anchor_age_minutes, weather
        )
        source = "lightgbm"
    except UnknownStation:
        result = predictor.predict_global_fallback(eta_minutes)
        source = "lightgbm_global_fallback"
    predicted_stock = max(0.0, live_stock + result["net_flow"])

    holidays = calendar.get_holidays_cached()
    arr_dow, arr_slot = calendar.dow_type_and_time_slot(arrival, holidays)

    return {
        "rental_id": rental_id,
        "eta_minutes": eta_minutes,
        "current_stock": live_stock,
        "predicted_stock": predicted_stock,
        "p_empty": result.get("p_empty"),
        "p_full": result.get("p_full"),
        "arrival_dow_type": arr_dow,
        "arrival_time_slot": arr_slot,
        "source": source,
        "model_horizon_min": result["horizon_min_used"],
    }
