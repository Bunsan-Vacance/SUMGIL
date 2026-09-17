"""anchor+horizon LightGBM(v4_weather) 실시간 추론 — 요청 1건짜리 서빙 전용.

배치 그리드용 `predictor.py`(`Predictor` Protocol, 전체 역×48슬롯을 한 번에 만듦)와는
완전히 다른 축이다. 여기는 API 요청 하나가 들어올 때마다 그 역 하나, 그 horizon 하나에
대해서만 피처 한 행을 조립해서 `target_net_flow`를 직접 예측한다(배치 없음).

무거운 의존성(lightgbm)은 함수 안에서 지연 import한다(`AI/CLAUDE.md`).

필요 아티팩트(`app/BIKE/pipeline/train.py`가 `--feature-set v4_weather`로 만든 것):
    model.txt                  LightGBM booster(target_net_flow 직접 예측, 잔차 아님)
    historical_profile_*.parquet   HistoricalProfileBuilder 3종(train.py가 저장)
    station_categories.json    station_code 복원용 카테고리 목록(train.py가 저장)

+ 별도 룩업(train.py 아티팩트 밖):
    station_master.parquet     역별 rack_count(validation/BYC/anchor-horizon-feature-check
                                /src/build_station_master.py가 만듦)

피처 조립 규칙은 `build_full_station_netflow.py`(원본 학습 데이터 생성 스크립트)의
컬럼 정의를 그대로 따른다 — anchor(현재 시각) 기준이라 target 시각 재계산이 필요 없다
(날짜축 멀티소스 모델과 다른 점).
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from app.BIKE.pipeline.calendar import get_holidays_cached
from app.BIKE.pipeline.features import MODEL_FEATURE_COLS_V4_WEATHER

HORIZON_CHOICES = (5, 10, 15, 30)


class ModelUnavailable(RuntimeError):
    """모델 아티팩트를 못 읽었거나, 역이 학습 당시 station_code 목록에 없음."""


def round_horizon(eta_minutes: int, choices: tuple[int, ...] = HORIZON_CHOICES) -> int:
    """`eta_minutes`를 모델이 학습한 horizon(5·10·15·30분) 중 가장 가까운 값으로 반올림한다.

    모델이 안 본 구간을 외삽하지 않기 위한 안전장치 — 응답의 도착 시각 라벨
    (`arrival_dow_type`/`arrival_time_slot`)에는 영향 없음, 모델 입력에만 쓴다.
    """
    return min(choices, key=lambda h: abs(h - eta_minutes))


class LightGBMEtaPredictor:
    def __init__(self, artifact_dir: Path, rack_count_path: Path) -> None:
        self.artifact_dir = Path(artifact_dir)
        self.rack_count_path = Path(rack_count_path)
        self._loaded = False

    def ensure_loaded(self) -> None:
        if self._loaded:
            return
        try:
            import lightgbm as lgb

            from app.BIKE.pipeline.features import HistoricalProfileBuilder

            d = self.artifact_dir
            self._booster = lgb.Booster(model_file=str(d / "model.txt"))
            self._profile = HistoricalProfileBuilder.load(d)
            categories = json.loads((d / "station_categories.json").read_text(encoding="utf-8"))
            self._station_dtype = pd.CategoricalDtype(categories=categories)
            rack = pd.read_parquet(self.rack_count_path)
            self._rack_count = rack.set_index("od_station_id")["rack_count"]
        except Exception as exc:
            raise ModelUnavailable(f"모델 아티팩트 로딩 실패({self.artifact_dir}): {exc}") from exc
        self._loaded = True

    def _build_feature_row(
        self,
        rental_id: str,
        current_stock: int,
        eta_minutes: int,
        now: datetime,
        anchor_age_minutes: float,
        weather: dict | None,
    ) -> tuple[pd.DataFrame, int]:
        if rental_id not in self._rack_count.index:
            raise ModelUnavailable(f"{rental_id} — 학습 시점 rack_count 목록에 없는 역")
        rack_count = float(self._rack_count.loc[rental_id])

        horizon_min = round_horizon(eta_minutes)
        hour, minute = now.hour, now.minute
        day_of_week = now.weekday()
        slot_5m = hour * 12 + minute // 5

        holidays = get_holidays_cached()
        normalized_date = pd.Timestamp(now.date())
        matched = holidays.loc[holidays["date"] == normalized_date, "is_holiday"]
        is_holiday = bool(matched.iloc[0]) if not matched.empty else False

        row = {
            "od_station_id": rental_id,
            "day_of_week": day_of_week,
            "hour": hour,
            "horizon_min": horizon_min,
            "stock_anchor_hour": float(current_stock),
            "stock_ratio_hour": float(current_stock) / rack_count if rack_count else 0.0,
            "minutes_since_stock_anchor": float(anchor_age_minutes),
            "is_empty_anchor": int(current_stock <= 0),
            "is_full_anchor": int(current_stock >= rack_count),
            "minute": minute,
            "is_weekend": int(day_of_week >= 5),
            "month": now.month,
            "sin_hour": np.sin(2 * np.pi * hour / 24),
            "cos_hour": np.cos(2 * np.pi * hour / 24),
            "sin_slot": np.sin(2 * np.pi * slot_5m / 288),
            "cos_slot": np.cos(2 * np.pi * slot_5m / 288),
            "is_holiday": int(is_holiday),
            "is_rain": int(weather["is_rain"]) if weather else 0,
            "temp": float(weather["temp"]) if weather else 0.0,
        }
        frame = pd.DataFrame([row])
        frame = self._profile.transform(frame)
        code = frame["od_station_id"].astype(self._station_dtype).cat.codes.iloc[0]
        if code == -1:
            raise ModelUnavailable(f"{rental_id} — 학습 시점 station_code 목록에 없는 역")
        frame["station_code"] = code
        return frame, horizon_min

    def predict_delta(
        self,
        rental_id: str,
        current_stock: int,
        eta_minutes: int,
        now: datetime,
        anchor_age_minutes: float = 0.0,
        weather: dict | None = None,
    ) -> dict:
        self.ensure_loaded()
        frame, horizon_min = self._build_feature_row(
            rental_id, current_stock, eta_minutes, now, anchor_age_minutes, weather
        )
        x = frame.reindex(columns=MODEL_FEATURE_COLS_V4_WEATHER).fillna(0)
        net_flow = float(self._booster.predict(x)[0])
        return {"net_flow": net_flow, "horizon_min_used": horizon_min}
