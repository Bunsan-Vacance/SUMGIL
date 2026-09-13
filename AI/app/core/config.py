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

    @property
    def grade_thresholds(self) -> list[float]:
        return [float(x) for x in self.crowd_grade_thresholds.split(",") if x.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
