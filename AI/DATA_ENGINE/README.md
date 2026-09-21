# DATA_ENGINE/

원천 데이터 수집과 EDA 전용 — `app/`(서빙)도 `validation/`(모델 PoC)도 아니다. 현재 따릉이·
날씨(BIKE/EXTERNAL)와 지하철 혼잡도(CROWD) 두 갈래가 있다. `app/`은 이 폴더를 import하지
않는다(단방향).

## 구조

- `collect/` — 외부 API 배치 수집 스크립트. `weather_asos_backfill.py`(과거 백필, 기본 dry-run),
  `common.py`(재시도·시각·parquet 저장 공용), `subway_ridership_daily.py`(CROWD: 서울교통공사 역별
  시간대별 승하차 D−1 일 배치, `getStnPsgr`, 143). CROWD의 **학습** 원본(연간·일별 CSV, 혼잡도 스냅샷)은
  수동 다운로드 파일이고, 수집기는 배치 예측의 이력 창(시차 피처)을 채우는 최근 실측만 받는다.
- `batch/` — 상시 수집 raw parquet을 모델·분석에서 쓰기 쉬운 interim parquet으로 정규화한다.
  `build_bike_stock_5min.py`는 따릉이 재고 snapshot을 5분 단위 대여소 재고 테이블로 만들고,
  `build_weather_nowcast_features.py`는 기상청 초단기실황/예보 long row를 날씨 피처 컬럼으로 피벗한다.
- `eda/` (따릉이·날씨) — `parsers.py`(파일형 원본 → `data/BIKE/interim`), `analysis.py`
  (재고·날씨 분석 함수), `report.py`(`reports/bike_weather_eda.md` 생성).
- `eda/` (CROWD, 1단계 정적 프로파일) — `parsers_crowd.py`(서울시 CSV + 9호선 xlsx →
  `data/CROWD/interim`, 두 원천의 시간대 표기·요일유형/방향 체계 차이를 정규화 없이 그대로
  보존), `analysis_crowd.py`(역×시간대 피벗, 결측·이상치 탐지, 커버리지 비대칭 확인, 연도별
  변화율 — 순수 함수), `report_crowd.py`(`reports/crowd_eda.md` 생성). **두 원천 모두 날짜
  컬럼이 없는 "대표 1주 평균" 스냅샷**이라 일 단위 시계열이 아니다 — 상세 배경은
  `AI/validation/CROWD/README.md`와 생성된 `reports/crowd_eda.md` 1절 참고. 다음 단계
  (`CardSubwayTime` 동적 신호 확보, 보정계수 추정, 외부요인 상관)는 실행 전 사용자와 호출
  범위를 맞춰야 하는 하드 룰 대상이라 아직 코드가 없다.
- `conf/column_map.yaml` — 파일형 원본 컬럼명 → 정규화 컬럼명 매핑. **원본 헤더가 바뀌면
  이 파일부터 대조**(현재 매핑은 2026-09-06, 2026년 1~7월치 실물로 검증됨). CROWD는 컬럼이
  적고 고정적이라 여기 넣지 않고 `parsers_crowd.py` 안에 인라인 rename으로 처리한다 —
  따릉이처럼 헤더 드리프트 감지가 필요한 성격이 아니다.
- `eda/` (CROWD, 보고서 그림 — 136) — `figstyle.py`(한글 폰트 탐색·호선 공식 색 팔레트·
  PNG+SVG 저장 규약)와 `report_figures.py`(그림 함수 12개, `--only 5,10` 선택 실행). 88~135
  분석 결과를 슬라이드·Notion·MR에 붙일 수 있는 그림으로 만든다. 아래 "보고서 그림 재생성" 참고.
  모든 `fig_*`는 호선·역·요일유형·타깃 선택 인자를 받고, 기본값이 아니면 파일명에 접미가 붙는다(141).
- `eda/crowd_eda.ipynb` (CROWD, 탐색 노트북 — 141) — 위 그림 함수를 **호출만** 하는 셀과 결론 마크다운,
  그리고 아직 그림으로 굳지 않은 탐색 셀(서울역 1·4호선 잔차 비교, 호선별 잔차/산포, 요일유형×시간대
  잔차). 역·호선을 바꿔 보며 확인하는 용도라 공유 산출물은 여기서 만들지 않는다. **출력을 넣은 채로
  커밋한다**(실행 없이 바로 보고 설명하기 위해 — 지우지 않는다). `ruff check
  DATA_ENGINE/eda/crowd_eda.ipynb` 통과(CI가 ipynb 코드 셀을 검사).
- `reports/` — `download_guide.md`(수동 다운로드 안내, 커밋 대상), `bike_weather_eda.md`·
  `crowd_eda.md`·`figures/*.png|svg`(생성 산출물, `.gitignore` 대상 — 코드만 커밋되고 리포트
  자체는 재생성. 그림은 Drive `data/CROWD/reports/figures/` 미러와 Notion 실험실 첨부로 공유).
- `scripts/` — 배치용 systemd 유닛 템플릿과 모니터링·배치 통합 실행 스크립트.

## 배치 수집기 운영

따릉이와 날씨 nowcast는 `DATA_ENGINE.stream.kafka_consumer`가 수집한다. 이 설치 스크립트는
지하철 D−1 승하차 수집과 예측 배치처럼 정해진 시각에 실행하는 systemd timer를 설치한다.
Kafka consumer 운영 방법은 아래 "Kafka consumer" 절을 참고한다.

사전 준비:

```bash
cd <REPO_ROOT>/AI
python -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
mkdir -p logs
```

`AI/.env`에는 최소 아래 키가 필요하다.

```text
SEOUL_SUBWAY_KEY 또는 SEOUL_API_KEY   # getStnPsgr(D−1 승하차)
KMA_API_KEY
```

서비스 파일 설치:

```bash
bash DATA_ENGINE/scripts/install_data_engine_services.sh
```

기본 실행은 서비스 파일 설치와 `daemon-reload`까지만 수행한다. 설치와 동시에 자동 실행까지
하려면 명시적으로 `--enable-now`를 붙인다.

```bash
bash DATA_ENGINE/scripts/install_data_engine_services.sh --enable-now
```

### 지하철 D−1 승하차 수집(`subway_ridership_daily`, 143)

원천 `getStnPsgr`(OA-22723)는 **어제치를 오전 중에 올리고 최근 7일만 남긴다** — 하루라도 놓치면 그 날은
영구 결손이다. 그래서 상시 폴링이 아니라 `subway-ridership-daily.timer`가 09:00·13:00에
`subway-ridership-daily.service`(oneshot)를 띄우고, 서비스는 어제부터 7일 중 **누적 파일에 없는 날짜만**
받는다(하루 ≈67회 호출, 첫 실행 ≈460회; 둘째 회차에 이미 있으면 호출 0회). `Persistent=true`라 서버가
꺼져 있던 회차도 켜지면 바로 실행한다. 설치는 위 스크립트가 함께 한다.

```bash
sudo systemctl enable --now subway-ridership-daily.timer
sudo systemctl list-timers subway-ridership-daily.timer
sudo systemctl start subway-ridership-daily.service      # 지금 한 번 실행
tail -n 50 AI/logs/subway_ridership_daily.log
```

정상 동작 기준:

- `AI/data/CROWD/raw/ridership_daily/dt=YYYY-MM-DD/getStnPsgr.parquet`가 날짜별로 쌓인다(원문, 카드·사용자 구분 그대로).
- `AI/data/CROWD/interim/crowd_recent_ridership_long.parquet`의 최대 `date`가 어제다(오전 회차 뒤 아직이면 13:00 회차 뒤).
- `python -m app.CROWD.pipeline.batch_predict --today`의 meta에 `history_days_present` 7, `lag1d_available` true.
- 로그에 `totalCount 0 — 보존 창(7일) 밖이거나 아직 갱신되지 않았습니다`가 **어제 날짜**로 13:00 회차에도 남으면 원천 지연 — 확인 필요.

수동 실행(로컬 확인):

```bash
cd AI
python -m DATA_ENGINE.collect.subway_ridership_daily --check-schema   # 5건만 받아 원문 저장
python -m DATA_ENGINE.collect.subway_ridership_daily                  # dry-run: 새로 받을 날짜·호출 수만 출력
python -m DATA_ENGINE.collect.subway_ridership_daily --days 7 --yes
```

### BIKE avg 서빙 배치 (S15P21A104-225)

`bike-avg-batch.timer`는 매일 03:00(Asia/Seoul)에 `bike-avg-batch.service`를 실행한다.
서비스는 `AI/.env`의 `BIKE_AVG_ARTIFACT`에 지정한
`models/BIKE/<검증된-폴더>/stock_profile_avg.parquet`을 읽어
`data/BIKE/serving/bike_stock_pred_<생성시각>.parquet`, `.csv`, `.meta.json`을 만든다.
`time_slot` 숫자가 뜻하는 시각은 [`AI/README.md`](../README.md)의
"BIKE avg 배치 표의 시간 구간"을 참고한다.

서버의 저장소에서 다음 순서로 설정·확인한다. 경로와 폴더 이름은 서버에 실제로 있는 것을 쓴다.

```bash
cd <REPO_ROOT>/AI
find models/BIKE -mindepth 2 -maxdepth 2 -name stock_profile_avg.parquet -print
nano .env

bash DATA_ENGINE/scripts/install_data_engine_services.sh
sudo systemctl start bike-avg-batch.service
sudo systemctl status bike-avg-batch.service --no-pager
sudo journalctl -u bike-avg-batch.service -n 50 --no-pager
ls -lt data/BIKE/serving/bike_stock_pred_*.meta.json | head

sudo systemctl enable --now bike-avg-batch.timer
sudo systemctl list-timers --no-pager bike-avg-batch.timer
systemd-analyze calendar '*-*-* 03:00:00 Asia/Seoul'
```

`nano .env`에서 `BIKE_AVG_ARTIFACT=models/BIKE/실제폴더명`을 추가한다.
`find` 결과의 `stock_profile_avg.parquet`이 들어 있는 폴더를 선택하고,
실험용 `smoke` 폴더 대신 검증된 전체 데이터 아티팩트를 지정한다.
수동 실행에서 로그에 `[BIKE avg batch] OK`가 나오고 최신 meta의 `artifact`, `rows`,
`generated_at`이 기대한 값인지 확인한 뒤 타이머를 활성화한다.
타이머가 예약돼 있어도 입력 avg 파일이 그대로면 새 출력의 통계 값은 그대로다.
통계 자체를 갱신하려면 새 데이터로 `stock_profile_avg.parquet`을 다시 생성하고
`BIKE_AVG_ARTIFACT`를 검증된 새 폴더로 변경해야 한다.

### CROWD 혼잡도 예측 배치 (S15P21A104-245)

`crowd-batch-predict.timer`는 매일 09:30(Asia/Seoul)에 `crowd-batch-predict.service`를
실행한다. 서비스는 `app.CROWD.pipeline.batch_predict --today --tomorrow --link-table`을 돌려
`data/CROWD/serving/`에 오늘·내일 2일치 `predictions_<날짜>.parquet` + `.meta.json`,
`predictions_link_<날짜>.parquet`, 그리고 **BE 적재용 `predictions_<날짜>_<HHMMSS>.csv`**(파일명에
`link_` 토큰이 없다)와 그 사이드카 `predictions_<날짜>_<HHMMSS>.meta.json`(`target_date`·
`row_count`·`generated_at` 3키)을 만든다.

09:30인 이유는 D−1 승하차 수집기(`subway-ridership-daily.timer`, 09:00 + 최대 5분 랜덤 지연)가
끝난 뒤라야 전날 실측이 이어붙어 `lag1d_available: true`(가용성 `full`)가 되기 때문이고,
서버의 기존 일정(bike-avg 03:00, Drive 업로드 12:10, 리텐션 13:00, 배치 13:10, 품질검사 13:30)과
겹치지 않으며, BE(이원빈)가 이 시각을 수용했다.

선행 조건:

- venv에 `lightgbm`·`torch`가 설치돼 있어야 한다. `torch`가 없으면 가용성 `d1_only` 날짜의
  GRU 라우팅이 깨진다.
- gitignore 대상이라 따로 복사해야 하는 입력(합계 약 20MB):
  `data/CROWD/processed/crowd_panel_2024_2025.parquet`(16M),
  `crowd_station_events_2024_2025.parquet`, `crowd_station_events_2026_2026.parquet`,
  `crowd_congestion_calibration.parquet`(1.2M),
  `data/EXTERNAL/holiday/interim/holiday_calendar.parquet`(없으면 전 날짜를 비공휴일로
  취급하므로 반드시 복사),
  `models/CROWD/festival_selflag_d1sd_d7_resid_masked-stack_train2024-2025/`(2.2M),
  `models/CROWD/dl_gru_s14_noev_s42_train2024-2025/`(604K).
- `data/CROWD/interim/crowd_recent_ridership_long.parquet`은 복사하지 않는다 — D−1 수집기가
  서버에서 만든다.

서버의 저장소에서 다음 순서로 설정·확인한다.

```bash
cd <REPO_ROOT>/AI
bash DATA_ENGINE/scripts/install_data_engine_services.sh
sudo systemctl start crowd-batch-predict.service
sudo systemctl status crowd-batch-predict.service --no-pager
tail -n 50 logs/crowd_batch_predict.log
ls -lt data/CROWD/serving/predictions_*.csv | head

sudo systemctl enable --now crowd-batch-predict.timer
sudo systemctl list-timers --no-pager crowd-batch-predict.timer
systemd-analyze calendar '*-*-* 09:30:00 Asia/Seoul'
```

정상 동작 기준(수동 1회 실행 뒤 이걸 확인하고 나서 타이머를 켠다):

- 로그에 `[CROWD batch] OK`가 나온다.
- `.meta.json`의 `link_table`이 `true`이고, `link_csv_rows`가 CSV 실제 데이터 행 수와 같다
  (BE 로더가 이 값으로 전송 손상을 검증한다).
- `.meta.json`의 `generated_at` 시각(HHMMSS)이 CSV 파일명의 `_HHMMSS`와 같다.
- CSV와 같은 basename의 사이드카 `.meta.json`이 같이 생겼고, 그 `row_count`가 CSV 실제 데이터
  행 수와 같다.
- `lag1d_available`이 `true`다(D−1 수집기가 돌고 있으면). `false`면 표는 나오지만 가용성이
  `d7_only`로 떨어진 상태다 — 결함이 아니라 상태다.
- 첫 실행에서 **소요 시간과 피크 메모리를 기록**한다(`TimeoutStartSec` 조정 근거, 워커 노드에
  운영 PG·Redis가 같이 떠 있다).

BE 연동: 산출 CSV는 BE(이원빈)가 `scp`로 가져가 `congestion_pred` 테이블에 적재한다. 적재는
수동·비주기이고 upsert라 멱등이다. BE는 **파일명 사전순 최신**을 고르므로 같은 날짜를 다시
만들어도 파일명이 겹치지 않게 `_HHMMSS`가 들어간다. 재적재 판정은 `meta.generated_at`으로
한다. 자세한 계약은 [`AI/app/CROWD/SERVING_CONTRACT.md`](../app/CROWD/SERVING_CONTRACT.md) 8절.

## 데이터 수집 모니터링

systemd 서비스가 `active`여도 API 오류, 저장 실패, 일부 시간대 누락이 생길 수 있으므로
별도 모니터링 스크립트로 실제 산출물 갱신 상태를 확인한다. 정상 상태에서는 알림을 보내지
않고, 실패 상태에서만 Discord Webhook 알림을 보낼 수 있다.

수동 실행:

```bash
cd <REPO_ROOT>/AI
bash DATA_ENGINE/scripts/run_data_engine_monitor.sh
```

개별 점검:

```bash
python -m DATA_ENGINE.monitor.check_collection_freshness
python -m DATA_ENGINE.monitor.check_partition_counts
```

점검 기준:

- 따릉이 Kafka `latest_stock.parquet`: 내부 `updated_at` 최댓값이 10분 초과하거나,
  30분 초과 행이 하나라도 있으면 실패.
- 날씨 Kafka `latest_by_grid.parquet`: 내부 `ingested_at` 최댓값이 90분 초과 시 실패.
- 따릉이 완료 시간대 파티션: `kafka_topic=bike.stock` snapshot 최소 10개/hour.
- 날씨 완료 시간대 파티션: `kafka_topic=weather.nowcast` snapshot 최소 1개/hour.
- 현재 진행 중인 KST 시간대는 파티션 파일 수 검사에서 제외한다.

모니터는 과거 직접 수집기의 `latest.parquet`과 평탄화 snapshot을 집계하지 않는다. 파일
mtime이 새로워도 내부 데이터 시각이 오래됐으면 stale로 판정하며, 같은 디렉터리에 과거
파일이 남아 있어도 `kafka_topic` 값이 일치하는 Kafka snapshot만 센다.

기준값은 실행 시 환경변수로 조정할 수 있다.

```bash
BIKE_MAX_AGE_MIN=15 WEATHER_MAX_AGE_MIN=30 PARTITION_HOURS=3 \
  bash DATA_ENGINE/scripts/run_data_engine_monitor.sh
```

Discord 알림을 사용하려면 `AI/.env`에 아래 값을 추가한다. 실제 Webhook URL은 Git에
커밋하지 않는다.

```text
DISCORD_WEBHOOK_URL=<discord webhook url>
DATA_ENGINE_SERVER_NAME=J15A104A
```

알림 전송 없이 점검만 실행하려면 아래처럼 실행한다.

```bash
DISCORD_NOTIFY_ON_FAILURE=0 bash DATA_ENGINE/scripts/run_data_engine_monitor.sh
```

Discord dry-run:

```bash
python -m DATA_ENGINE.monitor.notify_discord \
  --message "DATA_ENGINE Discord 알림 테스트" \
  --server-name J15A104A \
  --dry-run
```

cron 등록 예시:

```cron
*/5 * * * * cd /home/ubuntu/Soomgil-INFRA-ai-data-monitoring/AI && bash DATA_ENGINE/scripts/run_data_engine_monitor.sh >> logs/data_engine_monitor.log 2>&1
```

장애 확인 순서:

```bash
sudo systemctl status data-engine-kafka-consumer.service --no-pager

sudo journalctl -u data-engine-kafka-consumer.service -n 100 --no-pager
tail -n 100 logs/data_engine_monitor.log

find data/BIKE/raw/realtime -type f | tail
find data/EXTERNAL/weather/raw/nowcast -type f | tail

df -h
```

## 수집 데이터 배치 파이프라인

상시 수집기는 API 응답을 최대한 원본에 가깝게 `raw`에 쌓고, 배치 파이프라인은 이를 하루 단위
`interim` 산출물로 정규화한다. 지금 단계에서는 따릉이와 날씨를 서로 조인하지 않고, 도메인별
중간 테이블만 만든다. 모델 학습용 최종 feature join은 실험/서비스 명세가 확정된 뒤 별도
`processed` 단계에서 다룬다.

입력:

```text
AI/data/BIKE/raw/realtime/dt=YYYY-MM-DD/hh=HH/snapshot_*.parquet
AI/data/EXTERNAL/weather/raw/nowcast/dt=YYYY-MM-DD/hh=HH/snapshot_*.parquet
```

출력:

```text
AI/data/BIKE/interim/realtime_stock_5min/dt=YYYY-MM-DD/part.parquet
AI/data/EXTERNAL/weather/interim/nowcast_features/dt=YYYY-MM-DD/part.parquet
```

배치 모듈:

```text
DATA_ENGINE.batch.build_bike_stock_5min
DATA_ENGINE.batch.build_weather_nowcast_features
```

통합 실행:

```bash
cd <REPO_ROOT>/AI

# dry-run: raw를 읽고 변환 가능 여부와 예상 row 수만 확인한다.
bash DATA_ENGINE/scripts/run_data_engine_batch.sh --date 2026-09-13

# 실제 저장: interim parquet을 쓴다.
bash DATA_ENGINE/scripts/run_data_engine_batch.sh --date 2026-09-13 --yes
```

개별 실행:

```bash
python -m DATA_ENGINE.batch.build_bike_stock_5min --date 2026-09-13
python -m DATA_ENGINE.batch.build_weather_nowcast_features --date 2026-09-13
```

정상 산출물 확인:

```bash
ls -lh data/BIKE/interim/realtime_stock_5min/dt=2026-09-13/part.parquet
ls -lh data/EXTERNAL/weather/interim/nowcast_features/dt=2026-09-13/part.parquet
```

EC2 검증 예시(2026-09-13 데이터 기준):

```text
bike snapshots=268 rows=733575 output=data/BIKE/interim/realtime_stock_5min/dt=2026-09-13/part.parquet
weather snapshots=134 rows=938 output=data/EXTERNAL/weather/interim/nowcast_features/dt=2026-09-13/part.parquet
```

따릉이 interim 주요 컬럼:

```text
station_id, station_name, rack_total_count, current_bike_count, shared, stock_ratio,
station_latitude, station_longitude, collected_at, collected_date, collected_hour,
collected_minute, source
```

날씨 interim 주요 컬럼:

```text
collected_at, collected_date, collected_hour, collected_minute, weather_source,
base_datetime, forecast_datetime, nx, ny, t1h, rn1, reh, wsd, pty
```

날씨 배치는 과거 직접 수집 raw의 평탄화된 컬럼과 Kafka raw의 `payload_json`을 함께 읽는다.
Kafka payload의 `obsrValue`/`fcstValue`로 `observed`/`forecast`를 구분하고,
동일 종류·발표 시각·유효 시각·격자·category가 반복되면 마지막 수집값을 사용한다.
따라서 위 2026-09-13 행 수는 변경 전 실행 기록이며 재실행 시 결과 행 수가 줄 수 있다.
해석할 수 없는 Kafka payload는 파일별 건수를 경고로 남기고 해당 이벤트만 건너뛴다.

주기 실행은 EC2에서 수동 실행 결과를 확인한 뒤 등록한다. 예를 들어 전날 데이터 기준으로 매일
새벽 04:10에 배치를 돌리려면 아래처럼 등록할 수 있다.

```cron
10 4 * * * cd /home/ubuntu/Soomgil-INFRA-ai-data-monitoring/AI && bash DATA_ENGINE/scripts/run_data_engine_batch.sh --date "$(TZ=Asia/Seoul date -d 'yesterday' +\%F)" --yes >> logs/data_engine_batch.log 2>&1
```

### 배치 산출물 품질 점검

배치가 `part.parquet` 파일을 만들었더라도 row 수, 필수 컬럼, 결측·중복·이상값이 깨질 수
있다. `check_batch_outputs.py`는 배치 결과가 모델·분석 입력으로 쓸 수 있는 최소 품질을
만족하는지 확인한다. 기본 날짜는 KST 기준 어제다.

수동 실행:

```bash
cd <REPO_ROOT>/AI

python -m DATA_ENGINE.monitor.check_batch_outputs
python -m DATA_ENGINE.monitor.check_batch_outputs --date 2026-09-13
```

점검 대상:

```text
AI/data/BIKE/interim/realtime_stock_5min/dt=YYYY-MM-DD/part.parquet
AI/data/EXTERNAL/weather/interim/nowcast_features/dt=YYYY-MM-DD/part.parquet
```

기본 기준:

- 따릉이 row 수 최소 100,000.
- 날씨 row 수 최소 100.
- 필수 컬럼이 모두 존재해야 한다.
- 따릉이 `station_id`, `collected_at`은 결측이면 실패한다.
- 따릉이 `current_bike_count`, `rack_total_count`는 음수이면 실패한다.
- 따릉이 `stock_ratio`는 음수이면 실패한다. 상한은 `rack_total_count` 기준 차이와 초과 거치가
  실제 데이터에 자주 나타나므로 실패 조건으로 두지 않고, `max_stock_ratio` 참고 통계로 출력한다.
- 따릉이 `collected_at + station_id` 중복 row가 있으면 실패한다.
- 날씨 `weather_source`는 `observed`, `forecast`만 허용한다.
- 날씨 `t1h`, `rn1`, `reh`, `wsd`, `pty`가 모두 비어 있으면 실패한다.
- 날씨 `rn1`, `reh`, `wsd`, `pty`는 음수이면 실패하고, `reh`는 0~100 범위여야 한다.

정상 출력 예:

```text
OK bike batch output: rows=733575 stations=2737 snapshots=268 max_stock_ratio=12.14 path=...
OK weather batch output: rows=938 path=...
DATA_ENGINE batch output quality OK
```

실패 출력 예:

```text
FAIL bike batch output missing: path=...
FAIL weather invalid weather_source: values=['bad']
DATA_ENGINE batch output quality FAILED
```

운영에서는 배치가 끝난 뒤 한 번 실행한다. 예를 들어 전날 데이터 배치가 04:10에 돈다면,
품질 점검은 04:30 이후에 등록한다.

```cron
30 4 * * * cd /home/ubuntu/Soomgil-INFRA-ai-data-monitoring/AI && .venv/bin/python -m DATA_ENGINE.monitor.check_batch_outputs --date "$(TZ=Asia/Seoul date -d 'yesterday' +\%F)" >> logs/data_engine_batch_quality.log 2>&1
```

## 데이터 보관 정책

Kafka consumer는 서버 로컬에 `snapshot_*.parquet`를 계속 쌓는다. 로컬 디스크가
무한히 커지지 않도록, 재생성 불가능한 수동 원천과 가공 산출물은 건드리지 않고 실시간 raw
snapshot만 48시간 기준으로 정리한다. 운영 삭제는 Drive 업로드 manifest에서 백업 성공이 확인된
파티션만 대상으로 한다.

삭제 대상은 아래 세 경로로만 제한한다.

```text
AI/data/BIKE/raw/realtime/dt=*/hh=*/snapshot_*.parquet
AI/data/EXTERNAL/weather/raw/nowcast/dt=*/hh=*/snapshot_*.parquet
AI/data/SUBWAY/raw/arrival/dt=*/hh=*/snapshot_*.parquet
```

삭제 제외 대상:

- `AI/data/BIKE/raw/realtime/latest_stock.parquet`
- `AI/data/EXTERNAL/weather/raw/nowcast/latest_by_grid.parquet`
- `AI/data/EXTERNAL/weather/raw/nowcast/latest_weather.parquet`
- `AI/data/BIKE/raw/station_5min/`, `AI/data/BIKE/raw/rental_history/`,
  `AI/data/BIKE/raw/station_master/`
- `AI/data/BIKE/interim/`, `AI/data/BIKE/processed/`
- `AI/data/CROWD/`, `AI/data/ROUTE/`
- `AI/data/EXTERNAL/weather/raw/asos/`, `AI/data/EXTERNAL/weather/raw/forecast/`
- `AI/data/EXTERNAL/station/`, `AI/data/EXTERNAL/population/`, `AI/data/EXTERNAL/holiday/`
- `AI/logs/`, `AI/.env`, `*.pem`

기본 실행은 dry-run이다. 삭제 후보 파일 수·총 용량·경로만 출력하고 파일은 지우지 않는다.
`--require-archive-success`를 함께 사용하면 `data/manifest/archive_uploads.jsonl`에서
해당 `dataset/dt/hh`의 최신 기록이 `status=success`인 경우만 삭제 후보에 포함한다.
백업 성공 기록이 없거나 최신 기록이 실패라면 `SKIP ... reason=archive_not_success`로 출력하고
삭제하지 않는다. manifest가 success여도 파일마다 Drive 원격 파일의 존재·크기·MD5를 다시 대조하며,
하나라도 어긋나면(`archive_file_missing`, `archive_size_mismatch`, `archive_checksum_mismatch` 등)
그 파일은 삭제하지 않는다. 현재 진행 중인 시간 파티션도 삭제하지 않는다.

`--notify-discord`를 붙이면 retention 기간을 넘겼는데도 Drive 검증 실패로 남겨진 파일이 있을 때
Discord로 알린다(사유·데이터셋·시간 파티션별 파일 수). 삭제 보류가 없으면 알리지 않는다.

```bash
cd <REPO_ROOT>/AI
python -m DATA_ENGINE.monitor.cleanup_retention \
  --retention-hours 48 \
  --require-archive-success
```

실제 삭제는 `--yes`를 명시한 경우에만 수행한다.

```bash
python -m DATA_ENGINE.monitor.cleanup_retention \
  --retention-hours 48 \
  --require-archive-success \
  --yes
```

운영 주기 실행은 EC2 dry-run 결과가 안전한지 확인한 뒤 등록한다. 등록한다면 하루 1회 새벽처럼
수집 부하가 낮은 시간대를 권장한다.

```cron
20 3 * * * cd /home/ubuntu/Soomgil-INFRA-ai-data-monitoring/AI && .venv/bin/python -m DATA_ENGINE.monitor.cleanup_retention --retention-hours 48 --require-archive-success --notify-discord --yes >> logs/data_engine_retention.log 2>&1
```

## Drive 임시 백업 인증

Spark/HDFS/S3 도입 전까지는 EC2 로컬 raw snapshot을 삭제하기 전에 Google Drive에 임시
백업할 수 있다. 이 백업은 최종 저장소가 아니라 임시 archive storage이며, Drive에는
`AI/data/` 구조를 그대로 미러링한다.

```text
SUMGIL/data/BIKE/raw/realtime/dt=YYYY-MM-DD/hh=HH/snapshot_*.parquet
SUMGIL/data/EXTERNAL/weather/raw/nowcast/dt=YYYY-MM-DD/hh=HH/snapshot_*.parquet
```

EC2 cron/systemd에서 무인 업로드가 가능해야 하므로 인증은 Google OAuth token 방식을 사용한다.
서비스 계정 방식은 개인 Drive나 `Shared with me` 폴더에서 저장 용량 문제로 실패할 수 있어
현재 운영 경로에서 제외한다.

OAuth token 생성:

```bash
cd <REPO_ROOT>/AI
python -m DATA_ENGINE.archive.authorize_drive_oauth \
  --client-secret-file /path/to/google-oauth-client-secret.json \
  --token-file /path/to/google-drive-token.json
```

생성된 token 파일은 EC2의 repo 밖에 배치한다.

```bash
mkdir -p /home/ubuntu/secrets
chmod 700 /home/ubuntu/secrets
chmod 600 /home/ubuntu/secrets/google-drive-token.json
```

`AI/.env` 설정:

```text
DATA_ENGINE_DRIVE_AUTH_MODE=oauth
GOOGLE_OAUTH_TOKEN_FILE=/home/ubuntu/secrets/google-drive-token.json
GOOGLE_DRIVE_ARCHIVE_ROOT_FOLDER_ID=<SUMGIL/data folder id>
DATA_ENGINE_ARCHIVE_STORAGE=drive
```

이미 Drive에 도메인별 폴더가 있는 경우에는 dataset별 root folder ID를 우선 사용할 수 있다.
예를 들어 기존 `BIKE` 폴더에 따릉이 raw만 올리고 싶다면 `GOOGLE_DRIVE_BIKE_ARCHIVE_ROOT_FOLDER_ID`
를 지정한다. 이 경우 Drive에는 `BIKE/raw/realtime/...`가 아니라 해당 `BIKE` 폴더 아래
`raw/realtime/...`만 생성된다.

```text
GOOGLE_DRIVE_BIKE_ARCHIVE_ROOT_FOLDER_ID=<existing BIKE folder id>
GOOGLE_DRIVE_BIKE_ARCHIVE_ROOT_LEVEL=domain
GOOGLE_DRIVE_WEATHER_ARCHIVE_ROOT_FOLDER_ID=<existing weather folder id>
GOOGLE_DRIVE_WEATHER_ARCHIVE_ROOT_LEVEL=domain
```

root folder ID가 이미 더 깊은 폴더라면 root level을 같이 바꾼다.

```text
# root가 BIKE/raw 폴더인 경우 → realtime/dt=.../hh=... 생성
GOOGLE_DRIVE_BIKE_ARCHIVE_ROOT_LEVEL=raw

# root가 BIKE/raw/realtime 폴더인 경우 → dt=.../hh=... 생성
GOOGLE_DRIVE_BIKE_ARCHIVE_ROOT_LEVEL=realtime
```

OAuth client secret, token 파일, `.env`, Drive Webhook/토큰류는 Git에 커밋하지 않는다. 업로드 성공 여부는
다음 단계에서 파티션 단위 manifest로 기록하고, retention cleanup은 archive success가 확인된
파티션만 삭제하도록 확장한다.

Drive 업로드 대상 확인(dry-run):

```bash
cd <REPO_ROOT>/AI
python -m DATA_ENGINE.archive.upload_raw_partitions
```

실제 업로드:

```bash
python -m DATA_ENGINE.archive.upload_raw_partitions --yes
```

주요 옵션:

```text
--dataset bike|weather|subway|all
--older-than-hours 1
--max-partitions 24
--manifest-path data/manifest/archive_uploads.jsonl
--notify-discord
```

기본값은 dry-run이라 Drive API를 호출하지 않고 manifest도 기록하지 않는다. `--yes`를 붙이면
완료된 시간대 파티션만 Drive에 올리고, 결과를 `data/manifest/archive_uploads.jsonl`에 기록한다.
`--dataset`을 생략하면(`all`) bike·weather·subway를 모두 대상으로 한다. 이미 success인 파티션도
매 실행마다 Drive와 대조해 누락된 파일만 다시 올린다.

`--notify-discord`를 붙이면 파티션 업로드가 실패하거나(크기·MD5 불일치 포함) 인증 오류로 전체가
중단됐을 때 Discord로 알린다. 모두 성공하면 알리지 않는다. 주기 실행 예시(매시 10분):

```cron
10 * * * * cd /home/ubuntu/Soomgil-INFRA-ai-data-monitoring/AI && .venv/bin/python -m DATA_ENGINE.archive.upload_raw_partitions --yes --notify-discord >> logs/data_engine_archive.log 2>&1
```

## Kafka consumer

Kafka broker·topic·producer 구축은 BE/Infra 소유다. 이 폴더에서는 BE/Infra가 발행하는
topic을 AI consumer group으로 구독해 기존 raw parquet 계층에 저장하는 consumer만 다룬다.
J15A104A는 k3s worker 노드이므로 `/etc/hosts`에 Kafka ClusterIP를 등록한 뒤
`kafka:9092`로 접속한다.

필요한 `.env` 값:

```text
KAFKA_BOOTSTRAP_SERVERS=kafka:9092
KAFKA_CONSUMER_GROUP=ai-spark
KAFKA_AUTO_OFFSET_RESET=earliest
KAFKA_TOPIC_BIKE_STOCK=bike.stock
KAFKA_TOPIC_WEATHER_NOWCAST=weather.nowcast
KAFKA_TOPIC_SUBWAY_ARRIVAL=subway.arrival
```

J15A104A host 설정:

```bash
echo "10.43.134.226 kafka" | sudo tee -a /etc/hosts
```

`10.43.134.226`은 현재 prod Kafka Service ClusterIP다. Service를 재생성하면 바뀔 수
있으므로, BE/Infra에서 변경 공유를 받으면 `/etc/hosts`도 함께 갱신한다.

저장 경로:

| topic | 저장 위치 |
| --- | --- |
| `bike.stock` | `data/BIKE/raw/realtime/dt=YYYY-MM-DD/hh=HH/snapshot_*.parquet` |
| `weather.nowcast` | `data/EXTERNAL/weather/raw/nowcast/dt=YYYY-MM-DD/hh=HH/snapshot_*.parquet` |
| `subway.arrival` | `data/SUBWAY/raw/arrival/dt=YYYY-MM-DD/hh=HH/snapshot_*.parquet` |

Kafka event는 공통 envelope 컬럼과 `payload_json` 원본 보존 컬럼으로 저장한다. partition 기준
시간은 `poll_run_at`을 우선 사용하고, 없으면 `ingested_at`으로 대체한다. 품질/신선도 기준
시간은 `source_generated_at`이 있으면 그 값을 쓰고, 따릉이처럼 원천 생성시각이 없으면
`ingested_at`을 쓴다. 이렇게 하면 기존 Drive archive·retention·partition count 계층과 같은
`dt=/hh=/snapshot_*.parquet` 구조를 유지할 수 있다.

`bike.stock`은 원본 snapshot 적재와 별도로 FastAPI BIKE 실시간 재고 조회가 바로 읽을 수 있는
station별 최신값 파일도 갱신한다.

```text
data/BIKE/raw/realtime/latest_stock.parquet
```

컬럼은 `rental_id`, `current_stock`, `updated_at`이다. `rental_id`는 Kafka envelope의
`entity_id`를 사용하고, `current_stock`은 payload의 `parkingBikeTotCnt`를 사용한다.
`updated_at`은 `freshness_at` 기준이며, 따릉이는 `source_generated_at`이 없으면 `ingested_at`을
KST naive datetime으로 저장한다. 같은 대여소의 이전 값은 더 최신 `updated_at` 이벤트로만
갱신된다. 최신 이벤트보다 `updated_at`이 30분 넘게 오래된 대여소는 폐쇄·삭제된 대여소의
마지막 값이 계속 남지 않도록 파일 갱신 시 제거한다.

### 따릉이 Kafka 입력 계약 (2026-09-21 확인)

`bike.stock`은 서울시 `bikeList` 행 하나를 Kafka event 하나로 발행한다. AI consumer가
저장하는 raw Parquet은 다음 공통 envelope 컬럼을 갖는다.

| 컬럼 | 계약 |
| --- | --- |
| `event_id` | topic·대여소·payload 기반 이벤트 식별자 |
| `source`, `kafka_topic` | `bike.stock` |
| `entity_id` | payload의 `stationId`와 같은 대여소 ID |
| `source_generated_at` | 원천에 생성시각이 없어 null |
| `ingested_at` | BE가 API 응답을 수집한 시각이며 따릉이 신선도 기준 |
| `poll_run_at` | 한 번의 전체 대여소 poll 시작 시각이며 `dt`/`hh` 파티션 기준 |
| `freshness_at` | `source_generated_at`이 없으므로 `ingested_at`과 같음 |
| `payload_json` | 아래 `bikeList` 원본 필드를 JSON 문자열로 보존 |
| `kafka_partition`, `kafka_offset` | Kafka 원본 위치 |

배치가 사용하는 `payload_json` 필드는 다음과 같다. 현재 원천 응답에서는 모두 문자열이며,
producer는 숫자형으로 바꾸지 않고 그대로 보존한다.

| 필드 | 용도 |
| --- | --- |
| `stationId` | 대여소 ID |
| `stationName` | 대여소 이름 |
| `rackTotCnt` | 거치대 수 |
| `parkingBikeTotCnt` | 현재 자전거 수 |
| `shared` | 거치율 |
| `stationLatitude`, `stationLongitude` | 대여소 좌표 |

J15A104A의 최신 Kafka raw snapshot에서도 645/645행이 위 7개 필드를 모두 포함하고,
모든 필드가 문자열이며 `source_generated_at`은 null임을 확인했다. 원천에 필드가 추가되는
것은 허용하지만 위 필드는 raw → interim 배치의 필수 계약으로 유지한다.

`weather.nowcast`도 raw snapshot 저장 후 공통 최신 날씨 파일을 갱신한다.

```text
data/EXTERNAL/weather/raw/nowcast/latest_by_grid.parquet
```

컬럼은 `nx`, `ny`, `weather_source`, `category`, `base_datetime`,
`forecast_datetime`, `weather_value`, `source_generated_at`, `ingested_at`,
`event_id`다. 시각은 KST naive로 저장한다. 격자·관측/예보 종류·category별로
가장 최근 발표 시각의 값만 유지하며, 예보는 해당 발표의 유효 시각별 값을 모두
유지한다. 늦게 도착한 이전 발표는 최신값을 덮지 않는다. BIKE 전용
`latest_weather.parquet`과는 별개의 공통 파일이다.

BIKE ETA 서빙용 어댑터는 공통 파일에서 대표 격자 `(60, 127)`의 동일한
`base_datetime`에 해당하는 실황 `T1H`와 `RN1`만 선택해 다음 파일을 갱신한다.

```text
data/EXTERNAL/weather/raw/nowcast/latest_weather.parquet
```

이 파일은 단일 행의 `temp`, `is_rain`, `updated_at` 컬럼을 갖는다.
`is_rain`은 학습 데이터와 동일하게 `RN1 > 0`으로 정의하고, `updated_at`은
파일 저장/수집 시각이 아닌 실제 관측 시각(KST naive)이다. 두 항목이 같은
관측 시각에 모두 없거나 숫자로 해석할 수 없으면 이전 파일을 유지한다.
Kafka 발행이 약 60분 간격인 현 상태에서 BIKE의 15분 신선도 기준을 그대로
적용하면 정상 수집 중에도 폴백이 발생하므로, BIKE 설정과 운영 관측을 함께
검토해야 한다. 공통 파일은 BIKE 전용 포맷으로 바꾸지 않는다.

### 날씨 Kafka 입력 계약 (2026-09-18 확인)

J15A104A의 최근 Kafka 날씨 snapshot을 확인한 결과, `weather.nowcast`의 envelope
`source`는 관측과 예보 모두 동일하다. 종류는 `payload_json`의 값 필드로 구분한다.

| 종류 | payload 필드 | 값 필드 | 기준 시각 |
| --- | --- | --- | --- |
| 실황 `observed` | `baseDate`, `baseTime`, `category`, `nx`, `ny`, `obsrValue` | `obsrValue` | `baseDate` + `baseTime` |
| 예보 `forecast` | `baseDate`, `baseTime`, `fcstDate`, `fcstTime`, `category`, `nx`, `ny`, `fcstValue` | `fcstValue` | 발표: `baseDate` + `baseTime`; 유효: `fcstDate` + `fcstTime` |

확인한 category는 `T1H`, `RN1`, `REH`, `WSD`, `PTY`이며, 샘플의 격자는
`nx=60, ny=127` 한 곳이다. 이는 현재 샘플의 사실이지 producer가 항상 한 격자만
발행한다는 계약은 아니다. 공통 산출물은 격자와 관측/예보 종류, 발표/유효 시각을
보존해야 한다. 과거 직접 수집 raw는 이 필드가 평탄화되어 있고 `source`가
`observed`/`forecast`인 반면, Kafka raw는 `payload_json` 안에 필드가 있으며
envelope `source`가 `weather.nowcast`다. 날씨 배치는 두 형식을 모두 읽고 같은 내부
스키마로 정규화한다.

최근 서버 snapshot의 서로 다른 `poll_run_at` 간격은 약 60분이었다. BIKE 서빙의
15분 신선도 기준을 Kafka 발행 간격에 그대로 적용하면 정상 수집 중에도 오래된 값으로
판정될 수 있다. 현재 적용한 정책은 다음과 같다.

- 동일 관측이 과거 직접 수집 raw와 Kafka 양쪽에 있거나 재전송되면 정규화 키로 중복 제거한다.
- BIKE 실황은 대표 격자 `(60, 127)`의 `T1H`와 `RN1`을 사용한다.
- 공통 날씨 신선도는 `ingested_at`, BIKE 실황 파일의 `updated_at`은 실제 관측 시각을 사용한다.

서버에서 수동 확인:

```bash
cd AI
timeout 60 python -m DATA_ENGINE.stream.kafka_consumer \
  --topics bike.stock \
  --batch-size 1 \
  --flush-interval-sec 5

python - <<'PY'
import pandas as pd

path = "data/BIKE/raw/realtime/latest_stock.parquet"
df = pd.read_parquet(path)

print(df.shape)
print(df.dtypes)
print(df.head())
print(df["updated_at"].max())
PY
```

mock/sample event 기반 parser·sink 테스트:

```bash
cd AI
pytest -q test/test_kafka_event_parser.py test/test_kafka_sink.py
```

실제 consumer 실행:

```bash
cd AI
bash DATA_ENGINE/scripts/run_kafka_consumer.sh
```

Kafka에 접속하지 않고 `.env` 설정만 먼저 확인:

```bash
cd AI
bash DATA_ENGINE/scripts/run_kafka_consumer.sh --check-config
```

실제 연결 전 BE/Infra 확인이 필요한 값:

- topic별 payload 실측 샘플 추가 변경 여부
- prod 이벤트 투입 시작 시각
- Kafka Service ClusterIP 변경 여부

## Redis 연동 상태

Redis는 AI EC2에 별도로 새로 띄우지 않는다. 현재 Redis 캐싱 전략과 서버 구성은 BE/Infra
소유 작업으로 분리되어 있다.

- `S15P21A104-61` — `[INFRA | BE] Redis 캐싱 전략 설계 및 연동`: Redis key 네이밍·TTL
  정책 문서화, Spring Data Redis 기본 연동. 실제 캐시 갱신 로직은 데이터 파이프라인 연동 후
  별도 작업으로 제외되어 있다.
- `S15P21A104-127` — `[INFRA | Infra] Postgres·Redis StatefulSet`: k3s 환경의
  PostgreSQL·Redis StatefulSet 구성 작업.
- `S15P21A104-123` — `[INFRA | Infra] VPN 네트워크 구성`: AI EC2와 k3s Redis 간 접근이
  필요하면 이 네트워크 구성과 함께 확인해야 한다.

따라서 이 폴더의 수집기는 Redis key/TTL을 임의로 확정하지 않는다. BE/Infra Redis 컨벤션과
네트워크 접근 방식이 확정되기 전까지는 Kafka consumer가 갱신하는 최신 parquet을 사용한다.

## `data/` 하위 각 디렉터리가 뭔지

`AI/data/`는 이 폴더와 이름이 비슷해 보이지만 별개 위치다(`.gitignore`가 `AI/data/**` 기준으로
걸려 있어 옮기지 않았다). 도메인(JIRA 에픽 prefix) 우선 구조라 따릉이는 `data/BIKE/`, 지하철
혼잡도는 `data/CROWD/`, 역전 판정(경로 시간 비교)은 `data/ROUTE/`, 여러 도메인이 공유하는
외부 요인은 `data/EXTERNAL/`에 있다. `EXTERNAL/`은 다른 도메인과 달리 출처(`weather/`,
`station/`, `population/`)가 최상위이고 그 밑에 각각 `raw/interim/processed`를 둔다 — 여러
출처의 가공 산출물이 한 폴더에 섞이지 않게 하기 위해서다. 전부 원본·가공 데이터라 커밋되지
않는다.

| 경로 | 내용 | 출처 | 시간 해상도 | 쓰이는 곳 |
| --- | --- | --- | --- | --- |
| `data/BIKE/raw/realtime/` | 대여소별 실시간 재고 Kafka 스냅샷 | `DATA_ENGINE.stream.kafka_consumer`가 `bike.stock` 수집 | producer 발행 주기 | 배치·재고 분포·시간패턴·공간구조 |
| `data/BIKE/raw/realtime/latest_stock.parquet` | Kafka `bike.stock` 기반 대여소별 최신 재고(`rental_id`, `current_stock`, `updated_at`) | `DATA_ENGINE.stream.kafka_consumer`가 `bike.stock` consume 시 atomic replace로 갱신 | 최신 1회 | BIKE 실시간 ETA 재고 API의 현재고 입력 |
| `data/BIKE/raw/rental_history/` | 대여소별 이용정보 **월별 집계** (OA-15182) | 수동 다운로드 | 월 단위 | 정류소/자치구 월간 총량 참고용 — **날씨 분석엔 미사용** |
| `data/BIKE/raw/station_5min/` | 대여소별 5분단위 이용현황 O-D (OA-21229) | 수동 다운로드 | 5분(집계 시 시간 단위로 묶음) | **날씨-수요 핵심 분석 (3번 섹션)** |
| `data/BIKE/raw/station_master/` | 대여소 좌표 (OA-21235) | 수동 다운로드 | - | 공간분석 좌표 조인 (4번 섹션) |
| `data/EXTERNAL/weather/raw/asos/` | 종관기상관측 시간자료 2년 백필 (지점 108) | `weather_asos_backfill.py` | 시간 | 날씨-수요 핵심 분석 (3번 섹션) |
| `data/EXTERNAL/weather/raw/nowcast/` | 초단기실황/예보 Kafka 스냅샷 | `DATA_ENGINE.stream.kafka_consumer`가 `weather.nowcast` 수집 | producer 발행 주기 | 날씨 배치와 재고 보조 피처 |
| `data/EXTERNAL/weather/raw/nowcast/latest_by_grid.parquet` | 격자·실황/예보·category별 최신 날씨 | Kafka consumer가 atomic replace로 갱신 | 최신 1회 | 모니터링과 공통 최신 날씨 조회 |
| `data/EXTERNAL/weather/raw/nowcast/latest_weather.parquet` | 대표 격자의 BIKE용 기온·강수 여부 | Kafka consumer가 atomic replace로 갱신 | 최신 1회 | BIKE ETA 날씨 입력 |
| `data/EXTERNAL/station/raw/` | 서울시 역사마스터(역사_ID·역사명·호선·위경도, 지하철 전 노선) | 수동 다운로드 | - | CROWD 역 군집화·ROUTE 라우팅·BIKE 역-대여소 거리 등 여러 도메인이 참조 |
| `data/EXTERNAL/population/raw/` | 서울 생활인구 250M 격자, 일별 zip(시간대·연령·성별) | 수동 다운로드 | 시간 | 역 반경 집계 후 CROWD/BIKE 수요 보조 피처 (아직 집계 코드 없음) |
| `data/EXTERNAL/holiday/raw/` | 사립학교교직원연금공단 공휴일 관리 정보 | 수동 다운로드 | 일 단위 | 공휴일 파생변수(is_holiday) — CROWD/BIKE 이벤트 피처 |
| `data/BIKE/interim/` | `eda/parsers.py` 정규화 결과 (parquet) | 파서 실행 | 원본 그대로 | `report.py`가 직접 읽는 소스 |
| `data/BIKE/processed/`, `data/EXTERNAL/*/processed/` | (아직 미사용) 도메인·출처별 가공·피처 산출물 자리 | - | - | - |
| `data/CROWD/raw/` | 서울시 지하철혼잡도정보 CSV(1~8호선) + 9호선 xlsx 6개년 | 수동 다운로드 | "대표 1주" 스냅샷(날짜 아님) | 정적 프로파일 EDA |
| `data/CROWD/interim/crowd_congestion_long.parquet` | `parsers_crowd.py` tidy long-format 결과 | 파서 실행 | 원본 그대로 | `report_crowd.py`가 직접 읽는 소스 |
| `data/CROWD/raw/ridership_daily/dt=*/getStnPsgr.parquet` | 역별 시간대별 승하차 D−1 원문(카드·사용자 구분 포함, OA-22723) | `subway_ridership_daily.py` 일 배치 (원천은 최근 7일만 제공 — 소급 불가) | 1시간 | 아래 롱 포맷의 원본 보존 |
| `data/CROWD/interim/crowd_recent_ridership_long.parquet` | 위 원문을 역×슬롯 합산한 롱 포맷(`crowd_daily_ridership_long`과 같은 스키마) 누적 | `subway_ridership_daily.py`가 같은 날짜는 교체하며 누적 | 20슬롯 | `batch_predict`가 패널 뒤에 이어붙여 시차 피처 이력 창을 채움 |
| `data/ROUTE/raw/transfer_info/` | 서울교통공사 환승정보(환승역 간 도보 소요시간) | 수동 다운로드 | - | A안(지하철) 경로 시간 계산 — 혼잡도 예측 피처 아님 |

## 보고서 그림 재생성 (CROWD, 136)

```bash
cd AI
python -m DATA_ENGINE.eda.report_figures                 # 전체 12종 → DATA_ENGINE/reports/figures/
python -m DATA_ENGINE.eda.report_figures --only 5,10,11  # 번호 선택
```

수치를 그림 코드에 하드코딩하지 않는다 — 입력은 아래 표의 parquet이고, 없는 입력의 그림은 건너뛰고
실행 끝에 인벤토리로 알린다. 8·9번 입력은 검증 스크립트가 만든다(각 5~10분):

```bash
python validation/CROWD/baseline-check/compare_models.py <세트 ...> --models=lightgbm,xgboost \
    --save-results=data/CROWD/interim/validation/compare_results.parquet
python validation/CROWD/baseline-check/grade_sensitivity.py \
    --save-cells=data/CROWD/interim/validation/grade_cells.parquet
python validation/CROWD/sim-eval/evaluate.py --seeds 0,1       # 13·14번 입력(약 5분)
```

| # | 파일(`reports/figures/`) | 내용 | 입력 | 출처 절 |
| --- | --- | --- | --- | --- |
| 1 | `panel_heatmap_station_slot_<요일유형>` (4장) | 역(호선 순) × 20슬롯 승차 평균, log 스케일 | `processed/crowd_panel_2024_2025` | 88 |
| 2 | `panel_daily_total_by_line` | 호선별 일 총 승차 7일 이동평균, 평일 공휴일 표시 | 패널 | 88 |
| 3 | `direction_validation_scatter` | 재귀식 raw 평균 vs 실측 스냅샷, 호선·방향별 상관 | `processed/crowd_congestion_calibration` | 88 방향 검증 |
| 4 | `calibration_ratio_heatmap` | 호선별 역 × 30분 배율(평일, 하선/내선) | 배율표 | 88 배율표 |
| 5 | `half_hour_share_curve` | 시간대별 후반 30분 비중 평균 ± 1σ(평일/토/일) | 배율표 → `half_hour_shares` | 135 1층 |
| 6 | `residual_concentration` | 잔차(실측 − 2024 lookup) 쏠림: 상위 15역·시간대·요일유형 | 패널 | 87·90 |
| 7 | `station_residual_timeseries` | 서울역·종합운동장 2025 일별 잔차, 경기일 표시 | 패널 + `crowd_station_events` | 90 미해결 |
| 8 | `feature_set_improvement_steps` | 세트별 RMSE/MAE 개선율, 실시간 필요 세트 색 구분 | `interim/validation/compare_results` | 89 |
| 9 | `grade_threshold_sensitivity` | 임계치 후보별 등급 분포 + lookup/모델 일치율 | `interim/validation/grade_cells` | 90 |
| 10 | `train_load_gangnam_rush` | 강남 내선 07:30~09:29 열차별 혼잡도 추정, 배차 주석 | `processed/crowd_load_by_train_*` | 135 2층 |
| 11 | `headway_distribution_by_line` | 호선별 배차 간격 분포(러시/비러시), 12분 초과 비율 | `interim/timetable_long` | 135 |
| 12 | `crowd_line9_*` (2장) | 9호선 히트맵·군집(기존 `report_crowd` 위임) | `interim/crowd_congestion_long` | 88 |
| 13 | `sim_predictor_comparison` | 시뮬레이션 정답 위 예측기 4종 등급 일치율·MAE, 시나리오별 | `interim/validation/sim_eval_base` | 92 |
| 14 | `sim_sensitivity_grid` | 생성기 가정(σ_shape × 도착 혼합) 격자에서 도착 혼합 − 30분 그대로 | `interim/validation/sim_eval_grid` | 92 |

그림의 숫자가 `validation/CROWD/**/RESULTS.md`와 어긋나면 RESULTS.md가 맞다 — 그림은 표를 옮긴 것이다.

**선택해서 보기(141).** 함수 인자로 좁힌다. 노트북에서는 `fs.apply(inline=True)` 뒤 호출하면 파일 대신
셀에 그려진다.

```python
from DATA_ENGINE.eda import figstyle as fs, report_figures as rf
fs.apply(inline=True); inp = rf.Inputs()
rf.fig_panel_heatmap(inp, lines=["2호선"], day_types=["평일"])          # 호선 하나 → 역 이름 축
rf.fig_station_residual_timeseries(inp, stations=[150, 426, 218])      # station_no 목록
rf.fig_train_load(inp, station_no=150, direction="하선", date="2025-06-04", slots=("18:00", "18:30"))
rf.fig_headway_distribution(inp, lines=["5호선"], day_type="일요일", long_headway_min=10)
rf.fig_grade_threshold_sensitivity(inp, thresholds={"50/100": [50, 100], "40/90": [40, 90]})
inp.stations()                                                          # station_no ↔ 역명·호선
```

노트북 전체 실행: `DATA_ENGINE/eda/crowd_eda.ipynb` (약 15초, 그림 15장). 새 탐색은 노트북에서 시작하고,
결론이 나면 `fig_*` 함수로 옮겨 노트북에는 호출만 남긴다.

## 하드 룰

호출 횟수가 크거나 반복 실행되는 수집 스크립트는 실행 범위를 사용자와 먼저 맞춘다
(`AI/CLAUDE.md` 참고). `weather_asos_backfill.py`는 기본이 dry-run이고 `--yes`를 줘야 실제
호출한다.
