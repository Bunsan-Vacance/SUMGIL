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
- 도메인 패키지는 **대문자**로 쓰고 JIRA 에픽 prefix에 맞춘다(`CROWD/`, `BYC/`, `RVSL/`).
  새 도메인을 추가할 때도 이 규칙을 따른다. 내부 파일 규약:
  - `router.py` — `APIRouter`. 요청 검증·응답 변환만 하고 로직은 `service.py`로 위임한다.
  - `service.py` — 도메인 비즈니스 로직.
  - `schemas.py` — 요청/응답 pydantic 모델.
  - `pipeline/` — 오프라인 배치(Spark 집계·피처 생성 등, 선택).
- **서빙 경로(`router.py`/`service.py`)는 가벼운 의존성만 두고**, torch·PySpark 같은 무거운
  의존성은 `pipeline/` 함수 내부에서 지연 import한다 — 모듈 최상단 import로 서빙 계층까지
  로딩 지연이 번지는 것을 막기 위해서다.
- `RVSL`은 `CROWD`·`BYC`의 산출물을 조합하는 결과물이라 그 두 도메인을 import할 수 있다.
  반대 방향(도메인이 `RVSL`을 import)은 만들지 않는다.
- `test/` — `app/<도메인>/` 구조를 그대로 미러한다(`test/CROWD/`, `test/BYC/`, ...).
  **`test/` 아래에 `__init__.py`를 만들지 않는다** — 표준 라이브러리 `test` 패키지와
  충돌해서 pytest가 파일 경로가 아니라 basename으로 모듈을 식별하게 된다. 그래서
  **테스트 파일명은 리포 전체에서 유일해야 한다**(`test_<도메인>_<대상>.py`).
- `validation/` — PoC·스파이크 코드(관례는 `validation/README.md`). 프로덕션(`app/`)에서
  import하지 않는다. 반대 방향(`test/`·`validation/`이 `app/`을 import)은 정상이다.
- `DATA_ENGINE/` — 원천 데이터 수집·EDA 계층. `app/`(서빙)·`validation/`(모델 PoC) 어디에도
  속하지 않는 별도 생애주기라 분리했다 — `collect/`(API 폴링·백필)와 `eda/`(파서·분석·리포트
  생성)로 나뉜다. `app/`은 `DATA_ENGINE/`을 import하지 않는다(단방향). 대문자인 이유는
  `CROWD/`·`BYC/`·`RVSL`과 같은 시각적 구분 규칙을 따른 것 — 최상위 패키지라 ruff N999가
  중첩 도메인 패키지와 달리 이것만 잡아내서 `pyproject.toml`에 예외 처리해뒀다.
  - `conf/`, `reports/`, `scripts/`도 `DATA_ENGINE/` 전용이라 그 안에 같이 둔다
    (`conf/column_map.yaml` 설정, `reports/` 산출물, `scripts/` nohup·systemd 배포 템플릿).
  - `data/`(원본·중간·가공 저장소)는 이름이 비슷해 보이지만 `AI/data/`에 그대로 있다 —
    `.gitignore`가 이 경로를 기준으로 걸려 있어 옮기지 않았다.

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

## 커밋 전 로컬 검증

```bash
cd AI
pip install -r requirements-dev.txt   # ruff/black/pytest/httpx + requirements.txt
ruff check .
black --check .   # 실패하면 black . 로 자동 정렬 후 diff 리뷰
pytest -q
```
