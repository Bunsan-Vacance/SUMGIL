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
    # 197: DL 배포 아티팩트를 이름으로 고정한다. latest_artifact(kind="dl")는 폴더명 정렬 최신을
    # 고르는데, DL 변형이 18개라 이름 운에 맡기면 dl_lstm_*(대조군)이 dl_gru_*(채택 구성)보다
    # 뒤에 와서 잘못 뽑힌다 — 198 V3(정적 이벤트 없음) 판정이 이 이름을 가리키게 명시로 고정한다.
    # 200: 2024+2025 전체(학습 2024-01~2025-10, 검증 2025-11~12)로 최종 fit한 V3 s42. 이전 배포
    # `dl_gru_s14_noev_s42_20260914-1358`(2024 단독)은 롤백용으로 남겨둔다. 이름 정렬 최신은 여전히
    # `dl_lstm_s14_noev_s44_*`(대조군)라 고정 없이는 잘못 뽑힌다.
    crowd_dl_artifact: str = "dl_gru_s14_noev_s42_train2024-2025"
    # 145 후속 — LightGBM 배포 아티팩트도 이름으로 고정한다(`latest_artifact` 이름 정렬은
    # `_masked-stack_`이 뒤에 와 우연히 맞지만 운에 맡기지 않는다). `None`이면 예전처럼
    # `latest_artifact(kind="lightgbm")`, 그것도 없으면 lookup.
    # 200: 2024+2025 전체로 최종 fit한 마스킹 stack 아티팩트(2023 제외 근거 masking-check 13·17절).
    # 이전 배포 `..._masked-stack_20260917-1113`(2024 단독)은 롤백용으로 남겨둔다.
    crowd_lgbm_artifact: str | None = "festival_selflag_d1sd_d7_resid_masked-stack_train2024-2025"
    # 혼잡도 등급 임계치(%). 팀 논의 A-2 미확정 — 국토부 150/170/190은 판별력이 없어(90) 분포 기준 기본값.
    crowd_grade_thresholds: str = "50,100"
    # 200: 배치 서빙이 읽는 이벤트 표 목록(콤마 구분, `CROWD_PROCESSED` 아래). 학습은
    # `dataset.EVENTS_NAME` 하나만 쓴다. 뒤 파일이 같은 (date, station_no)를 덮어쓴다. 명시
    # 목록인 이유: glob으로 잡으면 실험용 표(`_2023_2025` 등)가 섞인다.
    crowd_events_files: str = (
        "crowd_station_events_2024_2025.parquet,crowd_station_events_2026_2026.parquet"
    )
    # LLM 예측기(실험 축). 키가 없으면 llm kind는 명확한 오류로 막힌다.
    crowd_llm_api_key: str | None = None
    crowd_llm_model: str | None = None
    # 239: 열차·노드 표(`predictions_train_*.parquet`) 산출 여부. 기본 False — BE 적재 경로가
    # 정해지기 전까지 기존 산출물(`predictions_*.parquet`과 메타 값)을 바꾸지 않는다.
    crowd_train_table: bool = False
    # 239: 135 시각표 파서 산출물(공공데이터포털 15098251). 열차 표 옵션을 켰는데 이 파일이
    # 없으면 `timetable.load_timetable`이 무엇을 먼저 돌려야 하는지 알려주는 오류를 낸다.
    crowd_timetable_path: Path = AI_ROOT / "data" / "CROWD" / "interim" / "timetable_long.parquet"
    # 244: 링크(from/to) 표(`predictions_link_{date}.parquet` + BE용 CSV) 산출 여부. 기본 False —
    # B-5 적재 계약은 확정됐지만(`.claude/handoff/response/FROME_BE-crowd-pred-load-path.md`)
    # 배치 스케줄이 아직 등록되지 않아, 첫 릴리스는 명시적으로 켰을 때만 만든다.
    crowd_link_table: bool = False

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

    # ── BIKE 실시간 예측 모델(anchor+horizon LightGBM, S15P21A104-160 Phase 5~6) ──
    # train.py --feature-set v4_weather --train-empty-full 로 만든 아티팩트. station_categories.json이
    # 저장된 버전이어야 한다(2026-09-17 이전 아티팩트는 이 파일이 없어 못 씀).
    # 2026-09-17 20:37 아티팩트부터 model_is_empty.txt/model_is_full.txt(p_empty/p_full
    # 분류기, S15P21A104-160 Phase 6)가 같이 들어있다 — 이전 아티팩트는 회귀만 있고
    # 없어도 predictor_eta.LightGBMEtaPredictor가 없는 파일로 판단해 p_empty/p_full만 None으로 둔다.
    # 회귀는 이전 아티팩트(45% 샘플)보다 전체 데이터로 다시 학습돼 소폭 개선됐다
    # (valid MAE 1.4797->1.4741, R² 0.3319->0.3364) — validation/BYC/eta-empty-full-check/RESULTS.md.
    bike_eta_model_dir: Path = AI_ROOT / "models" / "BIKE" / "v4-weather-final_20260917-2037"
    # 역별 rack_count 룩업(학습 원본 대신 미리 뽑아둔 작은 파일) —
    # validation/BYC/anchor-horizon-feature-check/src/build_station_master.py가 만듦.
    bike_station_master_path: Path = (
        AI_ROOT / "data" / "EXTERNAL" / "station" / "processed" / "station_master.parquet"
    )
    # 날씨 실시간 스냅샷(팀원이 별도로 구축 중) — weather.nowcast Kafka 토픽을
    # bike.stock처럼 최신 스냅샷화한 결과. 없거나 오래되면 자동으로 temp=0/is_rain=False로
    # 폴백하므로, 이 계약(경로·컬럼)만 맞으면 코드 변경 없이 연결된다.
    bike_live_weather_path: Path = (
        AI_ROOT / "data" / "EXTERNAL" / "weather" / "raw" / "nowcast" / "latest_weather.parquet"
    )
    # 날씨 수집기는 약 1시간 간격 실행. 실측(관측 70회) 결과 다음 관측 직전 기존값 나이가
    # 최대 129.6분이었고 120분 기준으로도 22/69 구간이 폴백에 걸려, 실제 수집 주기 대비
    # 20분 여유를 둔 150분(9,000초)으로 잡았다 — 운영 초기값이며 지연 기록을 보고 재조정한다.
    bike_live_weather_max_staleness_seconds: float = 9000.0

    @property
    def grade_thresholds(self) -> list[float]:
        return [float(x) for x in self.crowd_grade_thresholds.split(",") if x.strip()]

    @property
    def events_paths(self) -> list[Path]:
        crowd_processed = AI_ROOT / "data" / "CROWD" / "processed"
        return [
            crowd_processed / x.strip() for x in self.crowd_events_files.split(",") if x.strip()
        ]


@lru_cache
def get_settings() -> Settings:
    return Settings()
