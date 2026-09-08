# DATA_ENGINE/

원천 데이터 수집과 EDA 전용 — `app/`(서빙)도 `validation/`(모델 PoC)도 아니다. 현재 따릉이·
날씨(BYC/EXTERNAL)와 지하철 혼잡도(CROWD) 두 갈래가 있다. `app/`은 이 폴더를 import하지
않는다(단방향).

## 구조

- `collect/` — 외부 API 수집 스크립트. `bike_realtime.py`(60s 폴링), `weather_nowcast.py`
  (초단기실황/예보, 10min 폴링), `weather_asos_backfill.py`(과거 백필, 기본 dry-run),
  `common.py`(재시도·시각·parquet 저장 공용). CROWD 원본은 API 폴링이 아니라 수동 다운로드
  파일이라 이 폴더에 수집 스크립트가 없다.
- `eda/` (따릉이·날씨) — `parsers.py`(파일형 원본 → `data/BYC/interim`), `analysis.py`
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

## `data/` 하위 각 디렉터리가 뭔지

`AI/data/`는 이 폴더와 이름이 비슷해 보이지만 별개 위치다(`.gitignore`가 `AI/data/**` 기준으로
걸려 있어 옮기지 않았다). 도메인(JIRA 에픽 prefix) 우선 구조라 따릉이는 `data/BYC/`, 지하철
혼잡도는 `data/CROWD/`, 여러 도메인이 공유하는 날씨는 `data/EXTERNAL/`에 있다. 전부 원본·가공
데이터라 커밋되지 않는다.

| 경로 | 내용 | 출처 | 시간 해상도 | 쓰이는 곳 |
| --- | --- | --- | --- | --- |
| `data/BYC/raw/realtime/` | 대여소별 실시간 재고 스냅샷 | `bike_realtime.py` 폴링 (소급 불가, 지금부터 쌓는 것만 존재) | 60초 | 재고 분포·시간패턴·공간구조 (1·2·4번 섹션) |
| `data/BYC/raw/rental_history/` | 대여소별 이용정보 **월별 집계** (OA-15182) | 수동 다운로드 | 월 단위 | 정류소/자치구 월간 총량 참고용 — **날씨 분석엔 미사용** |
| `data/BYC/raw/station_5min/` | 대여소별 5분단위 이용현황 O-D (OA-21229) | 수동 다운로드 | 5분(집계 시 시간 단위로 묶음) | **날씨-수요 핵심 분석 (3번 섹션)** |
| `data/BYC/raw/station_master/` | 대여소 좌표 (OA-21235) | 수동 다운로드 | - | 공간분석 좌표 조인 (4번 섹션) |
| `data/EXTERNAL/raw/weather/asos/` | 종관기상관측 시간자료 2년 백필 (지점 108) | `weather_asos_backfill.py` | 시간 | 날씨-수요 핵심 분석 (3번 섹션) |
| `data/EXTERNAL/raw/weather/nowcast/` | 초단기실황/예보 스냅샷 | `weather_nowcast.py` 폴링 | 10분 | 재고 쪽 보조 분석(향후, 데이터 쌓이는 대로) |
| `data/BYC/interim/` | `eda/parsers.py` 정규화 결과 (parquet) | 파서 실행 | 원본 그대로 | `report.py`가 직접 읽는 소스 |
| `data/BYC/processed/`, `data/EXTERNAL/processed/` | (아직 미사용) 도메인별 가공·피처 산출물 자리 | - | - | - |
| `data/CROWD/raw/` | 서울시 지하철혼잡도정보 CSV(1~8호선) + 9호선 xlsx 6개년 | 수동 다운로드 | "대표 1주" 스냅샷(날짜 아님) | 정적 프로파일 EDA |
| `data/CROWD/interim/crowd_congestion_long.parquet` | `parsers_crowd.py` tidy long-format 결과 | 파서 실행 | 원본 그대로 | `report_crowd.py`가 직접 읽는 소스 |

## 하드 룰

호출 횟수가 크거나 반복 실행되는 수집 스크립트는 실행 범위를 사용자와 먼저 맞춘다
(`AI/CLAUDE.md` 참고). `weather_asos_backfill.py`는 기본이 dry-run이고 `--yes`를 줘야 실제
호출한다.
