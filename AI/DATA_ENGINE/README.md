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
- `scripts/` — 폴러 백그라운드 실행용 nohup 스크립트·systemd 유닛 템플릿.

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
| `data/BIKE/raw/rental_history/` | 대여소별 이용정보 **월별 집계** (OA-15182) | 수동 다운로드 | 월 단위 | 정류소/자치구 월간 총량 참고용 — **날씨 분석엔 미사용** |
| `data/BIKE/raw/station_5min/` | 대여소별 5분단위 이용현황 O-D (OA-21229) | 수동 다운로드 | 5분(집계 시 시간 단위로 묶음) | **날씨-수요 핵심 분석 (3번 섹션)** |
| `data/BIKE/raw/station_master/` | 대여소 좌표 (OA-21235) | 수동 다운로드 | - | 공간분석 좌표 조인 (4번 섹션) |
| `data/EXTERNAL/weather/raw/asos/` | 종관기상관측 시간자료 2년 백필 (지점 108) | `weather_asos_backfill.py` | 시간 | 날씨-수요 핵심 분석 (3번 섹션) |
| `data/EXTERNAL/weather/raw/nowcast/` | 초단기실황/예보 스냅샷 | `weather_nowcast.py` 폴링 | 10분 | 재고 쪽 보조 분석(향후, 데이터 쌓이는 대로) |
| `data/EXTERNAL/station/raw/` | 서울시 역사마스터(역사_ID·역사명·호선·위경도, 지하철 전 노선) | 수동 다운로드 | - | CROWD 역 군집화·ROUTE 라우팅·BIKE 역-대여소 거리 등 여러 도메인이 참조 |
| `data/EXTERNAL/population/raw/` | 서울 생활인구 250M 격자, 일별 zip(시간대·연령·성별) | 수동 다운로드 | 시간 | 역 반경 집계 후 CROWD/BIKE 수요 보조 피처 (아직 집계 코드 없음) |
| `data/EXTERNAL/holiday/raw/` | 사립학교교직원연금공단 공휴일 관리 정보 | 수동 다운로드 | 일 단위 | 공휴일 파생변수(is_holiday) — CROWD/BIKE 이벤트 피처 |
| `data/BIKE/interim/` | `eda/parsers.py` 정규화 결과 (parquet) | 파서 실행 | 원본 그대로 | `report.py`가 직접 읽는 소스 |
| `data/BIKE/processed/`, `data/EXTERNAL/*/processed/` | (아직 미사용) 도메인·출처별 가공·피처 산출물 자리 | - | - | - |
| `data/CROWD/raw/` | 서울시 지하철혼잡도정보 CSV(1~8호선) + 9호선 xlsx 6개년 | 수동 다운로드 | "대표 1주" 스냅샷(날짜 아님) | 정적 프로파일 EDA |
| `data/CROWD/interim/crowd_congestion_long.parquet` | `parsers_crowd.py` tidy long-format 결과 | 파서 실행 | 원본 그대로 | `report_crowd.py`가 직접 읽는 소스 |
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
python validation/CROWD/baseline-check/compare_models.py <세트 ...> --models=lightgbm,xgboost     --save-results=data/CROWD/interim/validation/compare_results.parquet
python validation/CROWD/baseline-check/grade_sensitivity.py     --save-cells=data/CROWD/interim/validation/grade_cells.parquet
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
