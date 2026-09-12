# DATA_ENGINE/

원천 데이터 수집과 EDA 전용 — `app/`(서빙)도 `validation/`(모델 PoC)도 아니다. 현재 따릉이·
날씨(BIKE/EXTERNAL)와 지하철 혼잡도(CROWD) 두 갈래가 있다. `app/`은 이 폴더를 import하지
않는다(단방향).

## 구조

- `collect/` — 외부 API 수집 스크립트. `bike_realtime.py`(5min 폴링), `weather_nowcast.py`
  (초단기실황/예보, 10min 폴링), `weather_asos_backfill.py`(과거 백필, 기본 dry-run),
  `common.py`(재시도·시각·parquet 저장 공용). CROWD 원본은 API 폴링이 아니라 수동 다운로드
  파일이라 이 폴더에 수집 스크립트가 없다.
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
- `reports/` — `download_guide.md`(수동 다운로드 안내, 커밋 대상), `bike_weather_eda.md`·
  `crowd_eda.md`·`figures/*.png`(생성 산출물, `.gitignore` 대상 — 코드만 커밋되고 리포트
  자체는 재생성).
- `scripts/` — 폴러 백그라운드 실행용 nohup 스크립트·systemd 유닛 템플릿.

## 실시간 수집기 운영

따릉이와 날씨 nowcast 수집기는 서버에서 상시 실행해야 하므로 운영 환경에서는 systemd를
기본으로 사용한다. `start_*.sh`는 수동 테스트나 임시 실행용으로만 쓴다.

사전 준비:

```bash
cd <REPO_ROOT>/AI
python -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
mkdir -p logs
```

`AI/.env`에는 최소 아래 키가 필요하다.

```text
SEOUL_BIKE_KEY 또는 SEOUL_API_KEY
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

수동으로 시작·확인할 때는 아래 명령을 사용한다.

```bash
sudo systemctl enable --now bike-realtime-poller.service
sudo systemctl enable --now weather-nowcast-poller.service

sudo systemctl status bike-realtime-poller.service
sudo systemctl status weather-nowcast-poller.service

tail -n 100 AI/logs/bike_realtime.log
tail -n 100 AI/logs/weather_nowcast.log
```

정상 동작 기준:

- `bike-realtime-poller.service`, `weather-nowcast-poller.service`가 `active` 상태다.
- `AI/logs/bike_realtime.log`, `AI/logs/weather_nowcast.log`가 생성된다.
- `AI/data/BIKE/raw/realtime/dt=YYYY-MM-DD/hh=HH/snapshot_*.parquet`가 생성된다.
- `AI/data/EXTERNAL/weather/raw/nowcast/dt=YYYY-MM-DD/hh=HH/snapshot_*.parquet`가 생성된다.
- `AI/data/BIKE/raw/realtime/latest.parquet`가 갱신된다.
- `AI/data/EXTERNAL/weather/raw/nowcast/latest.parquet`가 갱신된다.

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
네트워크 접근 방식이 확정되기 전까지는 `latest.parquet`를 최신값 fallback으로 사용한다.

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
| `data/BIKE/raw/realtime/` | 대여소별 실시간 재고 스냅샷 | `bike_realtime.py` 폴링 (소급 불가, 지금부터 쌓는 것만 존재) | 5분 | 재고 분포·시간패턴·공간구조 (1·2·4번 섹션) |
| `data/BIKE/raw/realtime/latest.parquet` | 최신 따릉이 재고 스냅샷 | `bike_realtime.py`가 매 폴링마다 atomic replace로 갱신 | 최신 1회 | Redis 연동 전 latest fallback |
| `data/BIKE/raw/rental_history/` | 대여소별 이용정보 **월별 집계** (OA-15182) | 수동 다운로드 | 월 단위 | 정류소/자치구 월간 총량 참고용 — **날씨 분석엔 미사용** |
| `data/BIKE/raw/station_5min/` | 대여소별 5분단위 이용현황 O-D (OA-21229) | 수동 다운로드 | 5분(집계 시 시간 단위로 묶음) | **날씨-수요 핵심 분석 (3번 섹션)** |
| `data/BIKE/raw/station_master/` | 대여소 좌표 (OA-21235) | 수동 다운로드 | - | 공간분석 좌표 조인 (4번 섹션) |
| `data/EXTERNAL/weather/raw/asos/` | 종관기상관측 시간자료 2년 백필 (지점 108) | `weather_asos_backfill.py` | 시간 | 날씨-수요 핵심 분석 (3번 섹션) |
| `data/EXTERNAL/weather/raw/nowcast/` | 초단기실황/예보 스냅샷 | `weather_nowcast.py` 폴링 | 10분 | 재고 쪽 보조 분석(향후, 데이터 쌓이는 대로) |
| `data/EXTERNAL/weather/raw/nowcast/latest.parquet` | 최신 초단기실황/예보 스냅샷 | `weather_nowcast.py`가 매 폴링마다 atomic replace로 갱신 | 최신 1회 | Redis 연동 전 latest fallback |
| `data/EXTERNAL/station/raw/` | 서울시 역사마스터(역사_ID·역사명·호선·위경도, 지하철 전 노선) | 수동 다운로드 | - | CROWD 역 군집화·ROUTE 라우팅·BIKE 역-대여소 거리 등 여러 도메인이 참조 |
| `data/EXTERNAL/population/raw/` | 서울 생활인구 250M 격자, 일별 zip(시간대·연령·성별) | 수동 다운로드 | 시간 | 역 반경 집계 후 CROWD/BIKE 수요 보조 피처 (아직 집계 코드 없음) |
| `data/EXTERNAL/holiday/raw/` | 사립학교교직원연금공단 공휴일 관리 정보 | 수동 다운로드 | 일 단위 | 공휴일 파생변수(is_holiday) — CROWD/BIKE 이벤트 피처 |
| `data/BIKE/interim/` | `eda/parsers.py` 정규화 결과 (parquet) | 파서 실행 | 원본 그대로 | `report.py`가 직접 읽는 소스 |
| `data/BIKE/processed/`, `data/EXTERNAL/*/processed/` | (아직 미사용) 도메인·출처별 가공·피처 산출물 자리 | - | - | - |
| `data/CROWD/raw/` | 서울시 지하철혼잡도정보 CSV(1~8호선) + 9호선 xlsx 6개년 | 수동 다운로드 | "대표 1주" 스냅샷(날짜 아님) | 정적 프로파일 EDA |
| `data/CROWD/interim/crowd_congestion_long.parquet` | `parsers_crowd.py` tidy long-format 결과 | 파서 실행 | 원본 그대로 | `report_crowd.py`가 직접 읽는 소스 |
| `data/ROUTE/raw/transfer_info/` | 서울교통공사 환승정보(환승역 간 도보 소요시간) | 수동 다운로드 | - | A안(지하철) 경로 시간 계산 — 혼잡도 예측 피처 아님 |

## 하드 룰

호출 횟수가 크거나 반복 실행되는 수집 스크립트는 실행 범위를 사용자와 먼저 맞춘다
(`AI/CLAUDE.md` 참고). `weather_asos_backfill.py`는 기본이 dry-run이고 `--yes`를 줘야 실제
호출한다.
