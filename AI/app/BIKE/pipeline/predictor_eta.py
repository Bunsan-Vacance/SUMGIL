"""anchor+horizon LightGBM(v4_weather) 실시간 추론 — 요청 1건짜리 서빙 전용.

배치 그리드용 `predictor.py`(`Predictor` Protocol, 전체 역×48슬롯을 한 번에 만듦)와는
완전히 다른 축이다. 여기는 API 요청 하나가 들어올 때마다 그 역 하나, 그 horizon 하나에
대해서만 피처 한 행을 조립해서 `target_net_flow`를 직접 예측한다(배치 없음).

무거운 의존성(lightgbm)은 함수 안에서 지연 import한다(`AI/CLAUDE.md`).

필요 아티팩트(`app/BIKE/pipeline/train.py`가 `--feature-set v4_weather`로 만든 것):
    model.txt                  LightGBM booster(target_net_flow 직접 예측, 잔차 아님)
    historical_profile_*.parquet   HistoricalProfileBuilder 3종(train.py가 저장)
    station_categories.json    station_code 복원용 카테고리 목록(train.py가 저장)

+ 선택 아티팩트(`--train-empty-full` 플래그로 같이 만든 것, S15P21A104-160 Phase 6):
    model_is_empty.txt         빈 재고(0대) 확률 LightGBM 이진분류 booster
    model_is_full.txt          만차 확률 LightGBM 이진분류 booster
    없으면 `p_empty`/`p_full`을 `None`으로 둔다 — 구버전 아티팩트 디렉터리에서도 회귀는
    그대로 동작해야 하므로 필수 아님(`ensure_loaded()`가 없어도 에러를 안 낸다).

+ 별도 룩업(train.py 아티팩트 밖):
    station_master.parquet     역별 rack_count(validation/BYC/anchor-horizon-feature-check
                                /src/build_station_master.py가 만듦)

피처 조립 규칙은 `build_full_station_netflow.py`(원본 학습 데이터 생성 스크립트)의
컬럼 정의를 그대로 따른다 — anchor(현재 시각) 기준이라 target 시각 재계산이 필요 없다
(날짜축 멀티소스 모델과 다른 점).

`ModelUnavailable`(진짜 장애, 503)과 `UnknownStation`(학습 시점에 없던 역, 정상적인
엣지케이스)을 구분한다 — 후자는 `service.py`가 잡아서 `predict_global_fallback()`
(station 무관 전역 평균, `HistoricalProfileBuilder.global_` 재사용)으로 200 응답을 대신
준다(S15P21A104-160 후속).
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
EMPTY_MODEL_FILENAME = "model_is_empty.txt"
FULL_MODEL_FILENAME = "model_is_full.txt"


class ModelUnavailable(RuntimeError):
    """모델 아티팩트 파일 자체를 못 읽음 — 진짜 장애, 503으로 그대로 드러낸다."""


class UnknownStation(RuntimeError):
    """역이 학습 시점 station_code/rack_count 목록에 없음 — 시스템 장애가 아니라 신규
    개설 대여소 등에서 정상적으로 생기는 상황이다. `service.py`가 이걸 잡아서
    `predict_global_fallback()`으로 전역 평균 응답을 대신 준다(S15P21A104-160 후속)."""


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

            self._booster_is_empty = self._load_optional_classifier(lgb, d / EMPTY_MODEL_FILENAME)
            self._booster_is_full = self._load_optional_classifier(lgb, d / FULL_MODEL_FILENAME)
        except Exception as exc:
            raise ModelUnavailable(f"모델 아티팩트 로딩 실패({self.artifact_dir}): {exc}") from exc
        self._loaded = True

    @staticmethod
    def _load_optional_classifier(lgb, path: Path):
        return lgb.Booster(model_file=str(path)) if path.exists() else None

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
            raise UnknownStation(f"{rental_id} — 학습 시점 rack_count 목록에 없는 역")
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
            raise UnknownStation(f"{rental_id} — 학습 시점 station_code 목록에 없는 역")
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
        p_empty = float(self._booster_is_empty.predict(x)[0]) if self._booster_is_empty else None
        p_full = float(self._booster_is_full.predict(x)[0]) if self._booster_is_full else None
        return {
            "net_flow": net_flow,
            "horizon_min_used": horizon_min,
            "p_empty": p_empty,
            "p_full": p_full,
        }

    def predict_global_fallback(self, eta_minutes: int) -> dict:
        """학습 시점에 없던 역(`UnknownStation`)용 전역 평균 폴백.

        `HistoricalProfileBuilder`가 이미 만들어 저장해둔 `global_` 티어
        (`PROFILE_KEYS_GLOBAL = ["horizon_min"]` — station·요일·시간대 무관, horizon만으로
        집계한 전체 평균)를 그대로 조회한다. 새 학습·새 아티팩트가 필요 없다. `p_empty`/
        `p_full`은 분류기도 station_code가 있어야 도는 구조라 마찬가지로 못 내므로 `None`
        (기존 "분류기 아티팩트 없음=null" 관례와 일관).
        """
        self.ensure_loaded()
        horizon_min = round_horizon(eta_minutes)
        global_profile = self._profile.global_
        row = global_profile.loc[global_profile["horizon_min"] == horizon_min]
        net_flow = float(row["historical_net_flow_mean"].iloc[0]) if len(row) else 0.0
        return {
            "net_flow": net_flow,
            "horizon_min_used": horizon_min,
            "p_empty": None,
            "p_full": None,
        }
