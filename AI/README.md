# AI & Data

**스택** Python · PyTorch · PySpark · scikit-learn

분석 파이프라인, 피처 엔지니어링, 모델 학습·평가를 담당한다.

---

## 사전 요구사항

> ⚠️ **현재 개발 환경에 Python이 설치돼 있지 않다.** 아래 설치가 선행돼야 한다.

| 항목 | 버전 | 비고 |
| --- | --- | --- |
| Python | 3.11 권장 | PySpark 3.5 호환 범위 |
| JDK | 17 이상 | PySpark 구동에 필요 (현재 환경 JDK 21 설치됨) |

Windows 기준 [python.org](https://www.python.org/downloads/) 설치 시 **"Add python.exe to PATH"** 를 반드시 체크한다.

## 시작하기

```bash
cd AI

# 가상환경
python -m venv .venv
source .venv/Scripts/activate   # Windows Git Bash
# .venv\Scripts\activate.bat    # cmd
# source .venv/bin/activate     # macOS / Linux

# 의존성
pip install -r requirements.txt

# 설치 후 버전 고정 (최초 1회, 팀 공유)
pip freeze > requirements.lock.txt
```

## 디렉터리 구조

```
AI/
├─ src/           분석·학습 코드 (파이프라인, 피처, 모델)
├─ notebooks/     탐색적 분석(EDA), 실험 기록
├─ data/
│  ├─ raw/        원본 수집 데이터        ← Git 추적 제외
│  └─ processed/  정제·가공 데이터        ← Git 추적 제외
├─ models/        학습된 모델 산출물      ← Git 추적 제외
└─ tests/         테스트 코드
```

**`data/`와 `models/`는 Git에 올리지 않는다.** 용량이 크고 재생성이 가능하기 때문이며, 루트 `.gitignore`에서 제외 처리돼 있다. 팀원 간 공유가 필요하면 별도 스토리지를 쓰고 경로만 문서로 남긴다.

## 작업 규칙

- **노트북은 탐색용, `src/`는 재현용.** 노트북에서 검증된 로직은 `src/`의 순수 함수로 옮긴 뒤 파이프라인에 연결한다.
- 피처 엔지니어링 함수는 **학습 코드와 Spark 양쪽에서 재사용 가능하게** numpy/pandas 기반 순수 함수로 작성한다. Spark에서는 `pandas_udf`로 감싸 쓴다.
- 노트북 커밋 전 출력(output)을 비운다. diff가 읽히지 않는다.
- API 키·인증 정보는 `.env`에 두고 커밋하지 않는다.

## 참고 문서

- [데이터 검증 리포트](../Docs/Service%20Design/데이터-검증-리포트.md) — 데이터·API 47건의 6축 검증과 판정, 접근 제약과 대응 설계
- [데이터 기준 기획](../Docs/Service%20Design/데이터-기준-기획.md) — 후보별 파이프라인 설계
