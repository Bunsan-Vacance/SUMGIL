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
| **대여소 쌍별 실측 소요시간** | 대여이력 `반납시각 − 대여시각` 분포 | 역전 판정 | `BYC` |
| **따릉이 고갈 예측** | "20분 후 예상 잔여 대수" | 재고 검증 | `BYC` |
| **역전 테이블** | 역 × 목적지 × 시간대 × 요일 사전계산 | BE 조회 API | `RVSL` |

`RVSL`(역전 판정)은 `CROWD`·`BYC`의 산출물을 조합해서 만드는 결과물이라 별도 도메인으로 둔다.
JIRA 에픽이 확정되면 위 도메인명(대문자)을 에픽 키에 맞춰 조정한다.

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

# 설치 후 버전 고정 (최초 1회, 팀 공유)
pip freeze > requirements.lock.txt

# FastAPI 서버 (AI/에서 실행 — .env를 실행 CWD 기준으로 읽는다)
uvicorn app.main:app --reload --port 8000
```

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
│  ├─ BYC/                 #   대여소 쌍별 소요시간 · 따릉이 고갈 예측 (구조는 CROWD와 동일)
│  └─ RVSL/                #   역전 테이블 — CROWD·BYC 산출물을 조합 (구조는 CROWD와 동일)
├─ test/                   # app/<도메인>/ 구조를 그대로 미러 (test/CROWD/, test/BYC/, ...)
├─ validation/             # PoC · 스파이크 코드 — 프로덕션 아님 (관례는 validation/README.md)
├─ data/                   # 도메인(JIRA 에픽 prefix)별로 나눔      ← Git 추적 제외
│  ├─ CROWD/               #   raw/(원본) → interim/(중간 산출물) → processed/(최종 데이터)
│  ├─ BYC/                 #   CROWD와 동일하게 raw/interim/processed
│  └─ EXTERNAL/            #   여러 도메인이 공유하는 외부 요인(날씨 등) — 동일 구조,
│                           #   raw/ 밑에 출처별 서브폴더(raw/weather/asos, .../forecast, .../nowcast)
├─ models/                 # 학습된 모델 산출물      ← Git 추적 제외
├─ requirements.txt        # 프로덕션 런타임 의존성
├─ requirements-dev.txt    # + ruff/black/pytest/httpx
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

## 8. 작업 규칙

- **`validation/`은 탐색용, `app/`은 재현·서빙용.** `validation/`에서 검증된 로직은
  `app/<도메인>/service.py` 또는 `pipeline/`으로 옮긴 뒤 라우터에 연결한다. 반대 방향(`app/`이
  `validation/`을 import)은 하지 않는다.
- 피처 엔지니어링 함수는 **학습 코드와 Spark 양쪽에서 재사용 가능하게** numpy/pandas 기반 순수 함수로 작성한다. Spark에서는 `pandas_udf`로 감싸 쓴다.
- 노트북 커밋 전 출력(output)을 비운다. diff가 읽히지 않는다.
- API 키·인증 정보는 `.env`에 두고 커밋하지 않는다.
- 커밋 전 로컬에서 `ruff check .`, `black --check .`, `pytest -q`를 돌려서 확인한다
  (`requirements-dev.txt` 설치 필요).
- **추정 데이터는 절대값이 아니라 변화율·상대 순위로 쓴다.** 표본이 부족한 구간에는 값을 채우지 않고 "데이터 부족"으로 명시한다. → [데이터 검증 리포트의 원칙 8가지](../Docs/Service%20Design/데이터-검증-리포트.md#5-검증에서-도출된-원칙)

## 9. 다음 할 일

1. **대여이력 몇 개월치 다운로드** → 실제 용량·건수 확인, HDFS 적재 계획 수립
2. **강남권 역전 구간 실존 여부 검증** — 한티→역삼 시나리오부터
3. **하차 데이터 기반 착석 확률 타당성 검증**

> **6주 범위**: 2호선 + 강남·홍대 축 + 수인분당선 강남 구간만 제대로. 확장성은 코드 구조로 증명한다.
