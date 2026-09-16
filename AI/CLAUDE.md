# AI — 지하철·따릉이 판단 지표 산출

담당 범위·기술 스택·산출물은 `AI/README.md` 참고. 이 문서는 `AI/` 폴더 안에서만 적용되는
실행·CI·코딩 규칙을 다룬다. 루트 `CLAUDE.md`(커밋·브랜치 규칙 포함)가 우선한다.

## 🚫 하드 룰 — 대량·반복 호출성 데이터 수집 스크립트는 실행 전 확인

공공데이터 API는 무료지만 인증키 발급 정책·호출 한도가 있고(`README.md` 4절), `bikeList`처럼
호출당 건수 제한이 있는 API도 있다.

- 대여이력 몇 개월치 다운로드, `bikeList` 반복 폴링처럼 **호출 횟수가 크거나 반복 실행되는
  스크립트는 작성은 하되, 실행 범위(기간·건수)를 사용자와 먼저 맞추고 실행한다.**
- 이유: 인증키 재발급·차단 위험, 그리고 다운로드 결과(용량·건수)가 이후 HDFS 적재 계획에
  그대로 영향을 준다 — 조용히 전체를 받아버리면 계획을 다시 세워야 한다.
- 엔드포인트 응답 스키마 확인 수준의 1회성 호출은 예외.

## 디렉터리·모듈 규약

- `app/` — 프로덕션 서빙 계층(도메인 우선 구조). 진입점은 `app/main.py`
  (`uvicorn app.main:app`), 앱 전역 공통은 `app/core/`, 도메인 공용 유틸은 `app/shared/`.
- 도메인 패키지는 **대문자**로 쓰고 JIRA 에픽 prefix에 맞춘다(`CROWD/`, `BIKE/`, `ROUTE/`).
  새 도메인을 추가할 때도 이 규칙을 따른다. 내부 파일 규약:
  - `router.py` — `APIRouter`. 요청 검증·응답 변환만 하고 로직은 `service.py`로 위임한다.
  - `service.py` — 도메인 비즈니스 로직.
  - `schemas.py` — 요청/응답 pydantic 모델.
  - `pipeline/` — 오프라인 배치(Spark 집계·피처 생성 등, 선택).
- **서빙 경로(`router.py`/`service.py`)는 가벼운 의존성만 두고**, torch·PySpark 같은 무거운
  의존성은 `pipeline/` 함수 내부에서 지연 import한다 — 모듈 최상단 import로 서빙 계층까지
  로딩 지연이 번지는 것을 막기 위해서다.
- `ROUTE`는 `CROWD`·`BIKE`의 산출물을 조합하는 결과물이라 그 두 도메인을 import할 수 있다.
  반대 방향(도메인이 `ROUTE`를 import)은 만들지 않는다.
- `test/` — `app/<도메인>/` 구조를 그대로 미러한다(`test/CROWD/`, `test/BIKE/`, ...).
  **`test/` 아래에 `__init__.py`를 만들지 않는다** — 표준 라이브러리 `test` 패키지와
  충돌해서 pytest가 파일 경로가 아니라 basename으로 모듈을 식별하게 된다. 그래서
  **테스트 파일명은 리포 전체에서 유일해야 한다**(`test_<도메인>_<대상>.py`).
- `validation/` — PoC·스파이크 코드(관례는 `validation/README.md`). 프로덕션(`app/`)에서
  import하지 않는다. 반대 방향(`test/`·`validation/`이 `app/`을 import)은 정상이다.
- `DATA_ENGINE/` — 원천 데이터 수집·EDA 계층. `app/`(서빙)·`validation/`(모델 PoC) 어디에도
  속하지 않는 별도 생애주기라 분리했다 — `collect/`(API 폴링·백필)와 `eda/`(파서·분석·리포트
  생성)로 나뉜다. `app/`은 `DATA_ENGINE/`을 import하지 않는다(단방향). 대문자인 이유는
  `CROWD/`·`BIKE/`·`ROUTE`과 같은 시각적 구분 규칙을 따른 것 — 최상위 패키지라 ruff N999가
  중첩 도메인 패키지와 달리 이것만 잡아내서 `pyproject.toml`에 예외 처리해뒀다.
  - `conf/`, `reports/`, `scripts/`도 `DATA_ENGINE/` 전용이라 그 안에 같이 둔다
    (`conf/column_map.yaml` 설정, `reports/` 산출물, `scripts/` nohup·systemd 배포 템플릿).
  - `data/`(원본·중간·가공 저장소)는 이름이 비슷해 보이지만 `AI/data/`에 그대로 있다 —
    `.gitignore`가 이 경로를 기준으로 걸려 있어 옮기지 않았다.

## 딥러닝 학습 — GPU 우선

torch 학습 코드(`train_dl` 등)는 장치를 `--device auto`(기본)로 받아 `cuda`가 있으면 GPU, 없으면 CPU로
돈다 — 하드코딩하지 않는다. 학습 PC의 SUMGIL 환경은 CUDA 빌드 torch(`+cu130`)를 쓴다(README 6절).
아티팩트 `meta.json`에 `device`·`train_seconds`를 남겨 어느 장치에서 얼마나 걸렸는지 기록한다.
예측기(`predictor.py`)와 배치 추론은 CPU에서도 그대로 동작해야 하고(EC2에 GPU 없음), 테스트는
장치를 `cpu`로 고정한다.

## 테스트 작성 — 무거운 의존성 가드

torch·PySpark처럼 무거운 의존성이 필요한 테스트는 파일 최상단에서
`pytest.importorskip(...)`으로 감싸, CI처럼 그 패키지가 안 깔린 환경에서 에러 없이
스킵되게 한다. 표준 라이브러리·numpy/pandas 순수 로직 테스트는 가드가 필요 없다.

```python
import pytest

torch = pytest.importorskip("torch")

from my_module import Something  # noqa: E402
```

CI(`ai-test`)는 `requirements-dev.txt` 전체(= `requirements.txt`의 torch·PySpark·geopandas
등 프로덕션 의존성 전부, GB 단위)가 아니라 `requirements-ci.txt`(지금 테스트가 실제로
import하는 것만 담은 목록)를 설치한다 — 안 그러면 매 파이프라인마다 수 분씩 걸린다.
**새 테스트가 `requirements-ci.txt`에 없는 패키지를 import하면 CI에서
`ModuleNotFoundError`가 난다** — 그 패키지가 위 가드로 스킵할 무거운 의존성이 아니라면
`requirements-ci.txt`에 추가한다.

## 실험 실행 효율 — 같은 계산을 두 번 하지 않는다

89번(피처 엔지니어링)에서 파생 컬럼(lookup 잔차·시차·인접역 조인)을 피처 세트마다 처음부터
다시 만들어, 세트당 4~5분 중 실제 학습은 1분이고 나머지가 전부 400만 행 조인이었다.
7세트 비교에 35분이 걸렸다. 반복 실험에서는 다음을 지킨다.

- **파생은 한 번, 학습은 여러 번.** 비교 스크립트는 "파생 컬럼 생성"과 "세트별 학습·평가"를
  분리한다. 파생은 전체 패널에 한 번 붙여 `data/CROWD/interim/`(도메인별 interim)에 parquet으로
  저장하고, 세트 비교는 그 파일을 읽어 컬럼만 골라 쓴다. 입력 패널·분할 경계·lookup 정의가
  바뀌면 재생성한다 — 그 조건을 파일명이나 옆 메타 파일에 남겨 stale 캐시를 쓰지 않게 한다.
- **여러 세트를 한 프로세스에서 돌린다.** 스크립트는 세트 목록을 인자로 받아 데이터 로딩·
  파생·lookup fit을 공유한다. 셸 루프로 세트마다 프로세스를 새로 띄우지 않는다.
- **느린 후보는 기본에서 뺀다.** RandomForest는 400만 행에서 fit 160~210초로 LightGBM(8초)의
  20배이고 87·89 비교에서 일관되게 열세였다. 기본 후보는 lightgbm·xgboost로 두고 RF는 명시적
  옵션으로만 켠다. 새 후보를 넣을 때도 먼저 표본으로 시간을 재고 결정한다.
- **실행 전 예상 시간을 계획 파일에 적고, 5분을 넘으면 먼저 줄일 방법을 찾는다.** 표본
  축소(역 일부·기간 일부)로 파이프라인이 끝까지 도는지 확인한 뒤 전체를 돌린다.
- **긴 실행은 백그라운드로 두고 세트가 끝날 때마다 결과를 파일에 append한다.** 중단돼도
  끝난 세트는 다시 돌리지 않는다. 콘솔 출력만 믿지 않는다.
- **조인은 키 조인, 반복은 벡터화.** 400만 행에서 `groupby.apply`·행 단위 루프·
  `DataFrame.apply(axis=1)`은 피한다. 같은 원천에 대한 merge를 side·lag마다 반복하지 않고,
  한 번 merge한 뒤 pivot/rename으로 컬럼을 만든다. 위치 shift 대신 날짜·슬롯 키 조인을 쓴다
  (빠진 날이 있어도 이전 행을 끌어오지 않는다).
- **결과 수치는 텍스트로 남긴다.** 노트북 출력만 믿지 않고, 비교 결과는
  `validation/<도메인>/<기능>-check/RESULTS.md`에 실행 조건(패널 버전·분할·환경)과 함께 기록한다.
  기록이 없으면 다음 작업이 기준값을 다시 만들어야 한다.
- **노트북 출력은 지우지 않는다.** 출력이 들어 있는 ipynb는 리뷰어·팀원이 실행 없이 바로 보라고
  의도적으로 남긴 것이다. 커밋 전에 출력을 비우거나, 출력 유무를 바꾸는 커밋을 만들지 않는다.
  출력을 지우는 것은 작성자가 직접 요청했을 때만 한다. ruff는 ipynb의 코드 셀만 검사하므로 출력이
  있어도 CI에 영향이 없다.

## 검증 결과 기록 — 리포와 Notion 실험실 양쪽에

검증(validation/ PoC, 피처·모델 비교, 데이터 진단)이 한 묶음 끝나면 결과를 두 곳에 남긴다.

1. **리포**: `validation/<도메인>/<기능>-check/RESULTS.md`에 실행 조건(패널 버전·분할·환경·명령)과
   수치 표를 그대로 기록한다. 재현·기준값의 원본은 여기다.
2. **Notion `특화 PJT / 실험실 /` 하위**: 팀이 읽는 요약을 도메인 페이지 아래에 쓴다
   (혼잡도는 `실험실 / [CROWD] 혼잡도` 하위, 따릉이·경로는 각 도메인 페이지 하위). 새 페이지
   하나가 검증 묶음 하나이고, 제목은 `<도메인> <무엇을 검증> — <한 줄 결론>` 형식으로 쓴다.
   본문은 다음 세 절로 고정한다:
   - **어떤 실험을 했나** — 가설, 비교 대상(기준선 vs 후보), 데이터·분할·환경, 실행 명령.
   - **결과** — 핵심 수치 표(기준선 대비 개선율과 절대값 둘 다), 부정적 결과와 제외한 것도 적는다.
   - **핵심 인사이트** — 결과가 뜻하는 것 3~5개, 다음 티켓에 넘기는 권장 사항, 미해결 논의.
   미해결 논의는 `실험실 / [CROWD] 혼잡도 / 혼잡도 — 팀 논의 포인트 (상시 갱신)`에도 항목으로
   추가한다(해결되면 체크 후 지우는 관례).

Notion 페이지에는 수치 표를 복제하되 원본은 리포 `RESULTS.md`라고 링크한다 — 두 곳의 수치가
어긋나면 리포가 맞다. Notion MCP가 연결돼 있으면 세션에서 바로 쓰고, 안 되면 본문을 `.md`로
만들어 사용자에게 넘긴다.

## 커밋 전 로컬 검증

```bash
cd AI
pip install -r requirements-dev.txt   # ruff/black/pytest/httpx + requirements.txt
ruff check .
black --check .   # 실패하면 black . 로 자동 정렬 후 diff 리뷰
pytest -q
```
