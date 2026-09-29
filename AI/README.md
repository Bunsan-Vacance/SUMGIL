# AI & Data

**스택** Python · PyTorch · PySpark · scikit-learn · LightGBM

> **숨길** — 지하철 탈출 내비게이션.
> "계속 탈까, 내려서 따릉이 탈까"를 감이 아니라 숫자로 판단하게 하는 서비스에서,
> **판단의 근거가 되는 모든 수치를 만드는 파트**다.

---

## 1. 이 파트가 만드는 것

서비스의 두 선택지 비교는 전부 여기서 나온 산출물로 계산된다.

```
A안 (계속 지하철) = 남은 역 이동 + 환승 도보 + 환승 대기 + 출구 도보
B안 (내려서 따릉이) = 출구→대여소 도보 + 대여 1분 + 주행 + 반납 + 목적지 도보
                                              ↑ 실측 이력에서 뽑은 값
```

| 산출물 | 설명 | 소비처 | `app/` 도메인 |
| --- | --- | --- | --- |
| **착석 기회 지수** | 혼잡도 → 앉을 확률 변환. 역·시간대·요일별 | BE 조회 API | `CROWD` |
| **자리 회전 예측** | "몇 정거장 뒤에 자리가 나는가" — 하차 피크 기반 | BE 조회 API | `CROWD` |
| **대여소 쌍별 실측 소요시간** | 대여이력 `반납시각 − 대여시각` 분포 | 역전 판정 | `BIKE` |
| **따릉이 고갈 예측** | "20분 후 예상 잔여 대수" | 재고 검증 | `BIKE` |
| **역전 테이블** | 역 × 목적지 × 시간대 × 요일 사전계산 | BE 조회 API | `ROUTE` |

`ROUTE`(역전 판정)은 `CROWD`·`BIKE`의 산출물을 조합해서 만드는 결과물이라 별도 도메인으로 둔다.
위 도메인명(대문자)은 확정된 JIRA 에픽 prefix와 일치한다(`CROWD`=[CROWD] 혼잡도,
`BIKE`=[BIKE] 따릉이, `ROUTE`=[ROUTE] 경로 추천).

## 2. 모델 계획

### 2.1 착석 기회 지수

혼잡도 34%가 "좌석이 딱 찬 상태"라는 기준점을 잡고 혼잡도(%) → 착석 확률(%) 변환을 만든다.

고정 곡선 하나로 끝내지 않고 **분위수 회귀(Quantile Regression)** 로 확장해 역·시간대·요일별 편차를 반영한 **구간**(예: 60~75%)을 낸다. 데이터가 적은 노선에서 불확실성을 함께 보여줄 수 있다.

> ⚠️ 혼잡도 원천이 평균 기반이라 실시간·특이 이벤트를 반영하지 못한다. **앱 표기는 "착석 확률"이 아니라 "착석 기회 지수"** 로 통일한다. 확신 없는 수치라는 것을 모델과 표기가 함께 드러내야 한다.

### 2.2 따릉이 고갈 예측

입력은 시간대·요일·날씨·인근 역 하차량. LightGBM으로 시작한다.

지하철 하차량과 따릉이 수요는 원인-결과 관계이므로(사람이 내리면 근처 대여소가 빈다), **착석 지수 모델과 피처 파이프라인을 공유**하거나 멀티태스크로 묶는다. 학습 데이터가 적은 구간에서 서로 보완된다.

### 2.3 대여소 쌍별 소요시간

대여이력에서 대여소 쌍마다 실측 분포를 만든다. **평균이 아니라 중앙값 / 하위 25% 값**을 쓴다 — 관광·산책처럼 놀면서 탄 기록이 섞여 평균이 위로 끌려간다.

이력이 부족한 구간은 OSRM(OpenStreetMap 자전거 모드)을 직접 구축해 보완한다. 도보는 표준 보행속도 분당 67m로 계산한다.

### 2.4 역전 구간 후보 스크리닝 *(선택)*

역-대여소-정류소 그래프에 Node2Vec류 임베딩을 적용해 "환승이 많고 대여소가 가까운" 패턴을 벡터 유사도로 잡는다. 전수 조사 없이 후보를 순위화할 수 있어, 6주 안에 검증할 구간을 **감이 아니라 모델이 고른 후보**로 제시할 수 있다.

### 2.5 스트리밍 이상 탐지 *(선택)*

대여소 재고 급감, 열차 도착 간격 이상을 감지해 사고·행사 상황에서 추천을 보수적으로 전환한다. 별도 모델 없이 **통계적 관리도(control chart)** 수준으로 시작 가능하다.

## 3. 분산 처리를 쓰는 지점

집계 데이터(혼잡도·승하차·역간시간)는 작다. 분산은 세 곳에서만 정당화된다.

| 지점 | 규모 | 도구 |
| --- | --- | --- |
| **볼륨** — 따릉이 대여이력 원천 로그 | 연간 수천만 건, 수년치 수억 건·수십 GB. 대여소 약 2,700개 → 쌍 약 700만 개 × 시간대 × 요일 집계 | HDFS + Spark 배치 |
| **스트림** — 실시간 수집 | bikeList 2,700개 + 도착정보를 1~2분 주기 → 하루 수백만 레코드 | Kafka → Spark Streaming → Redis |
| **계산량** — 역전 테이블 | 역 300개 × 인근 대여소 × 목적지 후보 × 시간대 48 × 요일 = 수천만~수억 조합 | 야간 Spark 배치 |

> **발표 방어 논리**: "집계 데이터는 작아서 그대로 쓰고, 원본 로그·스트림·조합 폭발 계산에만 분산을 썼다 — 데이터 크기에 맞는 도구 선택."

## 4. 사용 데이터

전부 무료 공공데이터. ★는 URL 미확인으로 포털에서 데이터셋명 검색 필요.

### 지하철 — 시간 계산

| # | 데이터 | 쓰임새 |
| --- | --- | --- |
| ① | [서울교통공사 역간거리 및 소요시간](https://data.seoul.go.kr/dataList/OA-12034/F/1/datasetView.do) | A안 기본 블록. 남은 역 수만큼 합산 |
| ② | [서울시 도시철도 구간정보](https://www.data.go.kr/data/15134768/fileData.do) | ①이 1~8호선 한정 → **수인분당선 등 커버** |
| ③ | 서울 도시철도 환승정보 ★ | 숨은 비용인 **환승 도보 시간**. 자전거가 이기는 이유 대부분이 여기 |
| ④ | 지하철 실시간 도착정보 ★ (`realtimeStationArrival`) | 환승 **대기** 시간 |

### 지하철 — 혼잡도 · 착석

| # | 데이터 | 쓰임새 |
| --- | --- | --- |
| ⑤ | [지하철혼잡도정보](https://data.seoul.go.kr/dataList/OA-12928/F/1/datasetView.do) · [포털판](https://www.data.go.kr/data/15071311/fileData.do) | 30분 단위 요일별·역별 혼잡도(%). **1~8호선만** 제공, 분기 갱신 |
| ⑥ | [호선별 역별 시간대별 승하차](https://data.seoul.go.kr/dataList/OA-12252/S/1/datasetView.do) (`CardSubwayTime`) | 자리 회전 예측 · 1~8호선 외 혼잡도 추정 · 따릉이 수요 입력 |
| ⑥′ | [서울교통공사 역별 시간대별 승하차인원(일별)](https://data.seoul.go.kr/dataList/OA-22723/A/1/datasetView.do) (`getStnPsgr`) | **D−1 갱신·최근 7일만 제공.** 배치 예측의 시차 피처 이력 창을 채우는 일 배치 원천(`DATA_ENGINE/collect/subway_ridership_daily.py`, 143). 1~8호선 273역 = 패널과 동일 |

### 따릉이

| # | 데이터 | 쓰임새 |
| --- | --- | --- |
| ⑦ | [공공자전거 대여이력](https://data.seoul.go.kr/dataList/OA-15182/F/1/datasetView.do) | **가장 중요.** 실측 소요시간 + 고갈 예측 학습. [이동경로판](https://data.seoul.go.kr/dataList/OA-22244/F/1/datasetView.do)도 존재 |
| ⑧ | [실시간 대여정보](https://data.seoul.go.kr/dataList/OA-15493/A/1/datasetView.do) (`bikeList`) | 재고 확인. 호출당 1,000건 제한 → **3회 분할 호출** |
| ⑨ | [대여소 정보](https://data.seoul.go.kr/dataList/OA-13252/F/1/datasetView.do) | 그래프 노드, 역↔대여소 도보거리 |
| ⑩ | OSRM + OpenStreetMap | 이력 부족 구간 보완 |
| ⑪ | 기상청 단기예보 ★ | 비 = 수요 급감. 예측 입력 + 우천 시 추천 차단 |

### 보조 후보

[실시간 열차 위치정보](https://data.seoul.go.kr/dataList/OA-12601/A/1/datasetView.do) · [지하철 실시간 도착정보](https://data.seoul.go.kr/dataList/OA-12764/F/1/datasetView.do) · SK open API 칸별 혼잡도 · ODsay 노선 경로 API

> 💡 **API 인증키** — 열린데이터광장·공공데이터포털 각각 회원가입 후 발급(즉시~1일). 열린데이터광장 호출 형식은 `openapi.seoul.go.kr:8088/{인증키}/json/{서비스명}/...`
>
> ⚠️ **약관 준수** — 외부 API·데이터를 다수 사용한다. 각 제공처 이용약관(재배포·상업적 이용·호출 한도)을 확인하고 위반하지 않는다.

## 5. 사전 요구사항

> ⚠️ **현재 개발 환경에 Python이 설치돼 있지 않다.** 아래 설치가 선행돼야 한다.

| 항목 | 버전 | 비고 |
| --- | --- | --- |
| Python | 3.11 권장 | PySpark 3.5 호환 범위 |
| JDK | 17 이상 | PySpark 구동에 필요 (현재 환경 JDK 21 설치됨) |

Windows 기준 [python.org](https://www.python.org/downloads/) 설치 시 **"Add python.exe to PATH"** 를 반드시 체크한다.

macOS에서 `lightgbm`은 OpenMP 런타임(`libomp`)이 없으면 import 시점에
`Library not loaded: @rpath/libomp.dylib`로 실패한다 — `brew install libomp`로 먼저 설치한다
(Linux·Windows는 해당 없음).

## 6. 시작하기

```bash
cd AI

# 가상환경
python -m venv .venv
source .venv/Scripts/activate   # Windows Git Bash
# .venv\Scripts\activate.bat    # cmd
# source .venv/bin/activate     # macOS / Linux

# 의존성 (개발 도구 포함)
pip install -r requirements-dev.txt

# NVIDIA GPU가 있는 학습 PC — PyPI 기본 torch는 CPU 빌드라 CUDA 빌드로 덮어쓴다(드라이버 CUDA 13.x 기준)
pip install --upgrade torch --index-url https://download.pytorch.org/whl/cu130
python -c "import torch; print(torch.__version__, torch.cuda.is_available())"   # '...+cu130 True'

# 설치 후 버전 고정 (최초 1회, 팀 공유)
pip freeze > requirements.lock.txt

# FastAPI 서버 (AI/에서 실행 — .env를 실행 CWD 기준으로 읽는다)
uvicorn app.main:app --reload --port 8000
```

### CROWD 혼잡도 — 배치 추론과 조회 API

모델은 요청 시점에 돌리지 않는다. 배치가 하루치 예측 표를 만들어 두고 API는 그 표만 읽는다.

```bash
cd AI
# (최초 1회) 잔차 모델 아티팩트 — models/CROWD/<세트>_<시각>/ (약 25초)
python -m app.CROWD.pipeline.train

# 배치 추론 — data/CROWD/serving/predictions_YYYY-MM-DD.parquet + .meta.json
python -m app.CROWD.pipeline.batch_predict --today --tomorrow --link-table  # 운영(BE 적재용 링크 CSV까지 산출)
python -m app.CROWD.pipeline.batch_predict --date 2025-06-02           # 패널 안 날짜(재현·검증)
python -m app.CROWD.pipeline.batch_predict --date 2026-01-05 --predictor lookup   # 기준선만

# 조회
uvicorn app.main:app --port 8000
# GET /crowd/meta
# GET /crowd/stations/222/congestion?date=2026-01-05&direction=내선
# GET /crowd/lines/2호선/congestion?date=2026-01-05&time=08:30
```

- 예측기는 `app/CROWD/pipeline/predictor.py`의 `Predictor` 인터페이스로 갈아 끼운다. `CROWD_PREDICTOR`
  설정값 `auto`(기본)는 아티팩트가 있으면 `lightgbm`, 없으면 `lookup`(요일유형×역×시간대 평균)이다.
  `llm`은 자리만 있고 `CROWD_LLM_API_KEY`가 설정되면 구현한다.
- **변환 층(승하차 → 혼잡도)에도 버전이 있다.** 예측 승하차를 화면 값으로 바꾸는 것은 재귀식과
  **배율표**(`data/CROWD/processed/crowd_congestion_calibration.parquet`)인데, 배율표는 모든 셀의
  승수라 갈아 끼우면 같은 모델·같은 승하차에서도 값이 통째로 바뀐다. 그래서 모델 아티팩트와 같은
  수준으로 추적한다 — 옆에 `crowd_congestion_calibration.meta.json`(적합 스냅샷판·승하차 창·방향 대응
  규칙·경계 처리 안·이전 파일 sha256)을 두고 이전 파일은 `processed/_archive/`로 옮긴다. 재생성은
  `python -m DATA_ENGINE.eda.build_congestion_calibration`(88 현행 재현은 `--variant current`)이고,
  하류 `crowd_congestion_label_calibrated_2024_2026.parquet`도 같이 다시 만든다. 현재 버전과 갱신
  기준은 [`app/CROWD/pipeline/MODEL_REGISTRY.md`](app/CROWD/pipeline/MODEL_REGISTRY.md) 5절
  "변환 층 산출물", 재적합 판정 근거는
  [`validation/CROWD/calibration-refit/RESULTS.md`](validation/CROWD/calibration-refit/RESULTS.md)(199).
- **피처 세트·아티팩트·예측기 코드가 각각 무엇인지**(어느 티켓, 수치, 현재 배포 세트 `festival_selflag_d1sd_d7_resid`)는
  [`app/CROWD/pipeline/MODEL_REGISTRY.md`](app/CROWD/pipeline/MODEL_REGISTRY.md)에 있다.
- 등급 임계치는 `CROWD_GRADE_THRESHOLDS`(기본 `50,100`, %). 값을 낼 수 없는 셀은 0으로 채우지 않고
  `data_status`로 응답한다 — 우선순위 순으로 `no_lookup`(기준선 없음) / `ok` / `calibration_fallback`
  (1~8호선 공휴일이라 일요일 배율을 빌려 쓴 셀, 값은 있다) / `segment_truncated`(절단 구간의 종점 링크 —
  1·3·4·7호선 본선과 2호선 신정지선 중 경계 유입 상수를 못 구한 셀) / `no_calibration`(결번 역 등 그 밖의
  배율 결측). 그 날짜 표가 없으면 404(배치 미실행). 근거는
  [`validation/CROWD/congestion-criteria-check/RESULTS.md`](validation/CROWD/congestion-criteria-check/RESULTS.md)(146)와
  [`validation/CROWD/calibration-refit/RESULTS.md`](validation/CROWD/calibration-refit/RESULTS.md)(199).
- 미래 날짜는 달력(요일유형)·이벤트 골격 위에 최근 7일 시차로 예측한다. 최근 7일 실측은 패널(2025-12까지) 뒤에
  D−1 수집기(`DATA_ENGINE/collect/subway_ridership_daily.py`, 매일 09:00·13:00)가 쌓은 파일을 이어붙여 채운다(143).
  전날 실측이 없으면 `lag1d_available=false`로 표시되고, 어떤 예측기를 쓸지는 가용성 4단
  (`full`/`d1_only`/`d7_only`/`no_lag`)에 따라 `pipeline/routing.py`의 `POLICY`가 정한다 — `d1_only`만 GRU고
  나머지 셋은 결측 시나리오를 학습 때부터 본 마스킹 LightGBM이다(145 후속 `masking-check/RESULTS.md` 14절).
  **이력이 전무할 때 lookup으로 강제 대체하던 옛 동작은 197에서 없어졌다** — `predictor_fallback`은 BE 계약
  유지를 위해 키만 남고 값은 항상 `null`이다(`SERVING_CONTRACT.md` 3절).
- 서버에서는 이 명령을 `crowd-batch-predict.timer`(매일 09:30 KST)가 돌리며, 설정·확인 절차는
  [`DATA_ENGINE/README.md`](DATA_ENGINE/README.md)의 "CROWD 혼잡도 예측 배치" 절에 있다.

### BIKE avg 배치 표의 시간 구간

`data/BIKE/serving/bike_stock_pred_*.parquet`과 같은 이름의 CSV에서 `time_slot`은
하루를 30분씩 나눈 구간 번호(`0`~`47`)다. `시 = time_slot // 2`,
`분 = (time_slot % 2) * 30`으로 구간 시작 시각을 구한다. 예를 들어 `0`은
`00:00~00:29`, `1`은 `00:30~00:59`, `9`는 `04:30~04:59`, `33`은
`16:30~16:59`, `47`은 `23:30~23:59`를 뜻한다. 표와 AI API에는 조회 키인
`time_slot` 숫자를 그대로 저장한다.

`dow_type`은 `0` 평일, `1` 토요일, `2` 일요일·공휴일이다. 따라서
`rental_id=ST-10, dow_type=0, time_slot=9`는 ST-10 대여소의 평일
04:30~04:59에 해당하는 과거 평균·빈도를 나타낸다.

### 운영 반영 (J15A104A)

운영 AI API는 k3s 파드가 아니라 **J15A104A 호스트의 systemd 유닛**이다(AI 이미지 S15P21A104-211 전까지).
클러스터 연결·외부 노출은 [`k8s/README.md`](k8s/README.md)를 본다.

- 서버 사본: `~/Soomgil-INFRA-ai-data-monitoring/AI` — **git 저장소가 아니다.** scp로 파일 단위 반영한다.
- 유닛: `ai-api.service` (`EnvironmentFile`=`.env`, `--host 100.64.193.109 --port 8000`). 로그는 `logs/ai-api.log`.
- 반영 단위(TIME 배포): `app/TIME/` 전체, `app/main.py`, `app/core/config.py`, `app/BIKE/router.py`·`service.py`
  (TIME이 쓰는 파일). 그 외 BIKE 파이프라인 파일은 DATA_ENGINE/BIKE 담당 범위라 TIME 배포에서 건드리지 않는다.

절차:

```bash
# ① 서버에서 교체 대상 백업 (<sha> = 배포하는 커밋)
mkdir -p .deploy-backups/<sha> && tar czf .deploy-backups/<sha>/before.tgz app/TIME app/main.py app/core/config.py app/BIKE/router.py app/BIKE/service.py
# ② 로컬에서 scp → 서버에서 풀기 (파일 단위)
# ③ 재시작 전 사전 import (깨진 코드를 올리지 않는다)
set -a; . ./.env; set +a; .venv/bin/python -c "import app.main"
# ④ 재시작 — 순단 약 2초. BE가 /bike/.../eta-stock을 실시간 호출하므로 피크 시간을 피한다
sudo systemctl restart ai-api
# ⑤ 확인
curl 100.64.193.109:8000/health
curl 100.64.193.109:8000/time/meta   # stationIndexSize ≈ 2,741, snapshotAgeSec < 300
```

`.env` 키 (서버 `AI/.env`):

| 키 | 값·용도 |
|---|---|
| `TIME_BE_BASE_URL` | BE 공개 주소 `https://j15a104.p.ssafy.io` |
| `TIME_LLM_BASE_URL` / `TIME_LLM_MODEL` / `GMS_API_KEY` | LLM 재안내 사유 생성. 비우면 규칙 전략으로 동작 |
| `TIME_DEBUG_FORCE_TRIGGER_ENABLED` / `TIME_DEBUG_EMPTY_RENTAL_IDS` | 시연용 강제 트리거. **운영은 비운다** — 시연 후 삭제하고 재시작 |
| `TIME_TRIGGER_P_EMPTY` 등 트리거 임계값 | 기본값은 `app/core/config.py` 참조 |

롤백: 서버 `.deploy-backups/<sha>/`의 tar를 풀어 복원한 뒤 `sudo systemctl restart ai-api`.

## 7. 디렉터리 구조

FastAPI 기준 **도메인 우선(domain-first)** 구조를 쓴다. 기능(산출물)마다 `app/<도메인>/`
자체완결 패키지를 만들고, 도메인 내부는 파일로 레이어를 나눈다.

```
AI/
├─ app/                    # 프로덕션 코드
│  ├─ main.py              #   FastAPI 앱 생성 + 도메인 router 등록 + /health
│  ├─ core/                #   앱 전역 공통 — config.py 등
│  ├─ shared/              #   여러 도메인이 공유하는 유틸(공공데이터 API 클라이언트 등)
│  ├─ CROWD/               #   착석 기회 지수 · 자리 회전 예측
│  │  ├─ router.py         #     APIRouter — 요청 검증·응답 변환만, 로직은 service로 위임
│  │  ├─ service.py        #     비즈니스 로직
│  │  ├─ schemas.py        #     요청/응답 pydantic 모델
│  │  └─ pipeline/         #     오프라인 배치(피처 집계 등)
│  ├─ BIKE/                #   대여소 쌍별 소요시간 · 따릉이 고갈 예측 (구조는 CROWD와 동일)
│  └─ ROUTE/               #   역전 테이블 — CROWD·BIKE 산출물을 조합 (구조는 CROWD와 동일)
├─ test/                   # app/<도메인>/ 구조를 그대로 미러 (test/CROWD/, test/BIKE/, ...)
├─ validation/             # PoC · 스파이크 코드 — 프로덕션 아님 (관례는 validation/README.md)
├─ data/                   # 도메인(JIRA 에픽 prefix)별로 나눔      ← Git 추적 제외
│  ├─ CROWD/               #   raw/(원본) → interim/(중간 산출물) → processed/(최종 데이터)
│  ├─ BIKE/                #   CROWD와 동일하게 raw/interim/processed
│  ├─ ROUTE/               #   CROWD·BIKE와 동일 구조. raw/transfer_info/ — 환승역 간 도보
│  │                        #   소요시간(A안 경로 시간 계산 전용, 혼잡도 예측용 아님)
│  └─ EXTERNAL/            #   여러 도메인이 공유하는 외부 요인 — 다른 도메인과 달리
│                           #   출처(weather/, station/, population/, holiday/)가 최상위이고
│                           #   그 밑에 각각 raw/interim/processed를 둔다(예: weather/raw/
│                           #   {asos,forecast,nowcast}, station/raw/ — 역사 위경도, 여러
│                           #   도메인이 참조, population/raw/ — 서울 생활인구 250m 격자,
│                           #   holiday/raw/ — 공휴일 관리 정보)
├─ models/                 # 학습된 모델 산출물      ← Git 추적 제외
├─ requirements.txt        # 프로덕션 런타임 의존성
├─ requirements-dev.txt    # + ruff/black/pytest/httpx (로컬 개발용, requirements.txt 전체 포함)
├─ requirements-ci.txt     # CI 전용 — 테스트가 실제 쓰는 것만 (AI/CLAUDE.md 참고)
└─ pyproject.toml          # ruff/black/pytest 설정
```

- **`app/`은 게이트웨이·서빙 계층.** 무거운 학습·배치 코드는 각 도메인의 `pipeline/`에 두되,
  torch 등 무거운 의존성이 서빙 경로(`router.py`/`service.py`)까지 끌려오지 않게 한다.
- 도메인 테스트는 `test/<도메인>/`에 둔다(`app/` 아래에 `tests/`를 따로 만들지 않는다).
  **`test/` 아래에는 `__init__.py`를 만들지 않는다** — 표준 라이브러리 `test` 패키지와 충돌한다.
  대신 테스트 파일명이 리포 전체에서 유일해야 한다(`test_<도메인>_<대상>.py`).
- **`data/`와 `models/`는 Git에 올리지 않는다.** 용량이 크고 재생성이 가능하기 때문이며 루트
  `.gitignore`에서 제외 처리돼 있다. 실제 데이터 파일은 팀 공유 Google
  Drive([SUMGIL](https://drive.google.com/drive/folders/1C_x37kCT3wfeLqqw1aApt_ODWNks8THw))의 `data/`에
  같은 도메인·경로 구조로 올린다.

### 선택: 로컬 Drive 자동 동기화 (AI 팀 전용)

Google Drive for Desktop으로 SUMGIL 폴더를 로컬에 마운트해뒀다면, `develop-AI`에 새 MR이
merge된 뒤 `git pull`을 받을 때마다 로컬 `AI/data/`가 Drive의 최신 데이터로 자동 갱신되게
할 수 있다. 완전히 opt-in이라 설치하지 않으면 아무 영향이 없다.

```bash
# 최초 1회 (AI 팀원 각자)
cd AI
powershell -File scripts/install_drive_sync_hook.ps1
```

- 설치 스크립트가 물어보는 경로는 Google Drive for Desktop이 마운트한 SUMGIL 폴더(예:
  `G:\내 드라이브\SUMGIL`)다.
- 이후 `develop-AI`에서 `git pull`로 새 MR을 받을 때마다 Drive → 로컬 `AI/data/` 방향으로만
  자동 복사된다(로컬 파일이 더 최신이면 덮어쓰지 않고, 삭제도 하지 않는다).
- 새로 만든 데이터를 Drive에 올리는 건 자동화하지 않는다 — 검증 후 직접
  `powershell AI/scripts/sync_drive_data.ps1 -Direction Push` 로 실행한다.

## 8. 작업 규칙

- **`validation/`은 탐색용, `app/`은 재현·서빙용.** `validation/`에서 검증된 로직은
  `app/<도메인>/service.py` 또는 `pipeline/`으로 옮긴 뒤 라우터에 연결한다. 반대 방향(`app/`이
  `validation/`을 import)은 하지 않는다.
- 피처 엔지니어링 함수는 **학습 코드와 Spark 양쪽에서 재사용 가능하게** numpy/pandas 기반 순수 함수로 작성한다. Spark에서는 `pandas_udf`로 감싸 쓴다.
- **노트북 출력(output)은 지우지 않는다.** 출력이 들어 있는 ipynb는 리뷰어·팀원이 실행 없이 바로
  보라고 의도적으로 남긴 산출물이다(`AI/CLAUDE.md` "실험 실행 효율"). 노트북은 `_build_notebook.py`
  같은 생성 스크립트로 만들고 실행까지 해서 커밋한다.
- API 키·인증 정보는 `.env`에 두고 커밋하지 않는다.
- 커밋 전 로컬에서 `ruff check .`, `black --check .`, `pytest -q`를 돌려서 확인한다
  (`requirements-dev.txt` 설치 필요).
- **추정 데이터는 절대값이 아니라 변화율·상대 순위로 쓴다.** 표본이 부족한 구간에는 값을 채우지 않고 "데이터 부족"으로 명시한다. → [데이터 검증 리포트의 원칙 8가지](../Docs/Service%20Design/데이터-검증-리포트.md#5-검증에서-도출된-원칙)

## 9. 다음 할 일

1. **대여이력 몇 개월치 다운로드** → 실제 용량·건수 확인, HDFS 적재 계획 수립
2. **강남권 역전 구간 실존 여부 검증** — 한티→역삼 시나리오부터
3. **하차 데이터 기반 착석 확률 타당성 검증**

> **6주 범위**: 2호선 + 강남·홍대 축 + 수인분당선 강남 구간만 제대로. 확장성은 코드 구조로 증명한다.
