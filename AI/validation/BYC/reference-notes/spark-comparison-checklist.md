# Spark 도입 후 성능 비교 체크리스트

작성 시점: 2026-09-11, Phase 2.5(학습 기간 스케일 확장 실험) 진행 중 논의된 내용을 기록.
아직 Spark는 도입 전이며, 이 문서는 **도입 후 무엇을 비교할지 미리 정리해둔 계획**이다.

## 전제 — 비교 범위

`AI/README.md`에 이미 명시된 원칙: "집계 데이터는 작아서 그대로 쓰고, 원본 로그·스트림·조합
폭발 계산에만 분산을 썼다." 즉 Spark는 **데이터 준비/전처리 단계** 대체용이지 모델 학습
자체(XGBoost/LightGBM)를 MLlib로 바꾸는 게 아니다. 그래서:

- **비교 대상**: 데이터 로딩, feature 생성(historical profile 등), 집계
- **비교 대상 아님**: 모델 학습시간·정확도 자체 (Spark 도입과 무관, 같은 pandas 최종
  feature 테이블을 그대로 학습에 씀)

## 비교 항목

### 1. 데이터 로딩 + 전처리 시간 (스케일별)

Phase 2.5에서 03m/06m/09m/12m 스케일별로 실측한 pandas 단일머신 처리 시간이 "before"
베이스라인이다. `AI/validation/BYC/q3-seasonal-dataset-check/outputs/phase2.5/progress_report.md`에
스케일별 elapsed·행수 기록돼 있음. Spark로 같은 원본을 읽어 같은 feature를 만들면 스케일별
시간을 나란히 비교해 "데이터가 커질수록 격차가 벌어지는가"를 그래프로 보여줄 수 있다.

### 2. 메모리 사용량(피크 RAM)

Phase 2.5 진행 중 겪은 문제들(OOM kill 2회, 5시간22분 hang)이 단일머신 pandas 한계의
실제 사례. Spark 분산 처리 시 노드당 피크 메모리가 실제로 줄어드는지가 "Spark 도입이 문제를
해결했는가"의 핵심 증거.

### 3. 결과 정확성(수치 동일성) — 속도 비교보다 먼저 검증

Phase 2.5에서 청크 처리로 리팩터링할 때 "기존 방식과 수학적으로 완전히 같은 값을 내는지"
합성 데이터로 먼저 검증한 뒤 실제 job을 돌렸던 것과 같은 원칙. Spark로 만든 집계/피처가
pandas 버전과 값이 동일한지 먼저 확인한 뒤에 속도를 비교해야 한다 — 안 그러면 빨라진 게
로직 차이 때문인지 버그 때문인지 구분이 안 됨.

### 4. 피처 엔지니어링 로직 재사용성

`AI/README.md`: "피처 엔지니어링 함수는 학습 코드·Spark 양쪽에서 재사용 가능하게
pandas/numpy 순수 함수로 작성, Spark에서는 `pandas_udf`로 감싼다." Phase 2.5에서 만든
`downcast_memory()`, `HistoricalProfileBuilder`, station dtype 매핑 로직이 재사용 대상
후보 — 같은 로직을 `pandas_udf`로 감쌌을 때 결과 일치(항목 3) + 속도 개선을 함께 확인.

### 5. I/O 최적화 대조군 (구체적 사례 하나 확보됨)

Phase 2.5의 `03m/stratified300/phase2`에서 station id dtype 구성을 위해 test 파일을
두 번 읽는 구조가 돼버려 처리 시간이 2.2배(39분대→105분)로 늘어난 사례가 있음(원인·조치는
`progress_report.md` 항목 4 참고). Spark의 lazy evaluation/DAG 최적화가 이런 중복 스캔을
자동으로 피하는지, 아니면 pandas처럼 수동 캐싱이 필요한지 비교해볼 만한 구체적 케이스.

## 참고

- 비교용 "before" 원본 실측 데이터: `AI/validation/BYC/q3-seasonal-dataset-check/outputs/phase2.5/progress_report.md`
- 이 프로젝트의 분산처리 적용 범위 설계: `AI/README.md` "발표 방어 논리" 절
