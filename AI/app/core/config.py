from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

AI_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "S15P21A104 AI Gateway"
    environment: str = "local"

    # ── CROWD 서빙 ──
    # 배치 예측 표가 놓이는 곳(predictions_YYYY-MM-DD.parquet + meta). API는 여기만 읽는다.
    crowd_serving_dir: Path = AI_ROOT / "data" / "CROWD" / "serving"
    # 학습 아티팩트(models/CROWD/<세트>_<시각>/). 배치 잡만 읽고 API는 건드리지 않는다.
    crowd_models_dir: Path = AI_ROOT / "models" / "CROWD"
    # 예측기 종류: auto(아티팩트 있으면 lightgbm, 없으면 lookup) | lookup | lightgbm | llm
    crowd_predictor: str = "auto"
    # 혼잡도 등급 임계치(%). 팀 논의 A-2 미확정 — 국토부 150/170/190은 판별력이 없어(90) 분포 기준 기본값.
    crowd_grade_thresholds: str = "50,100"
    # LLM 예측기(실험 축). 키가 없으면 llm kind는 명확한 오류로 막힌다.
    crowd_llm_api_key: str | None = None
    crowd_llm_model: str | None = None

    # ── BIKE 서빙 ──
    # bike_stock_pred 표가 놓이는 곳. CROWD와 달리 날짜별 파일이 아니라 **단일 최신 표**다
    # (bike_stock_pred의 기본키가 rental_id·dow_type·time_slot이라 날짜 축이 없음 — 주기적으로
    # 통째로 갱신되는 정적 표). API는 이 디렉터리에서 가장 최신 파일 하나만 읽는다.
    bike_serving_dir: Path = AI_ROOT / "data" / "BIKE" / "serving"
    bike_models_dir: Path = AI_ROOT / "models" / "BIKE"
    # 예측기 종류: avg | lightgbm. lightgbm은 아직 미구현(predictor.py의 LightGBMPredictor
    # 참고 — B4 model 소스 변환 미검증)이라 auto 분기 없이 기본값을 avg로 고정한다.
    bike_predictor: str = "avg"

    # ── BIKE 실시간(현재고) ──
    # Kafka 컨슈머가 station별 upsert로 유지하는 최신 스냅샷 파일. Redis 아님 — 컨슈머와
    # 서빙 앱이 같은 서버/파일시스템을 공유한다는 전제 위에서 성립한다.
    bike_live_stock_path: Path = (
        AI_ROOT / "data" / "BIKE" / "raw" / "realtime" / "latest_stock.parquet"
    )
    # 이 시간(초)보다 오래된 updated_at은 신뢰하지 않고 "없음"으로 취급한다.
    bike_live_stock_max_staleness_seconds: float = 300.0

    # ── BIKE D-1/D-7 lag (LightGBM anchor+horizon 서빙용, Phase 2) ──
    # snapshot_stock_history.py(30분마다)가 쌓는 일별 관측 로그.
    bike_stock_history_dir: Path = AI_ROOT / "data" / "BIKE" / "raw" / "realtime" / "stock_history"
    # update_lag_lookup.py(하루 1회)가 위 로그를 집계해 만드는 표 — lag_features.attach_lag()가
    # 그대로 읽을 수 있는 스키마(od_station_id·lag_date·lag_time_slot·lag_stock)를 쓴다.
    bike_lag_lookup_path: Path = (
        AI_ROOT / "data" / "BIKE" / "raw" / "realtime" / "lag_lookup_live.parquet"
    )
    # D-7까지만 있으면 되므로 여유를 조금 둔 보관 기간(일). 이보다 오래된 관측 로그·lookup
    # 행은 update_lag_lookup.py가 정리한다.
    bike_lag_lookup_retention_days: int = 10

    @property
    def grade_thresholds(self) -> list[float]:
        return [float(x) for x in self.crowd_grade_thresholds.split(",") if x.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
