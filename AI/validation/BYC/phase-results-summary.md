# 따릉이 재고 예측 — 완료 실험 결과 요약서

작성: 2026-09-13. `experiment-plan.md`의 로드맵(Phase 0~7) 중 **지금까지 성공적으로
완료된 Phase 0~3**의 결과만 모았다. 상세 실행 로그·디버깅 과정은 각 Phase 산출물
디렉터리 참고(하단 "산출물 위치" 표).

## 한눈에 보기

| Phase | 목적 | 결론 |
|---|---|---|
| 0 | 데이터 검증 | PASS — station 매칭 100%, split 경계·leakage 이상 없음 |
| 1 | 최소 feature baseline | 트리 모델이 MAE는 근소 우위, R²·방향성은 Naive_Profile 우세 → Phase 2 필요 확인 |
| 2 | 과거 프로파일 feature 추가 | MAE/R²는 PASS, **direction_accuracy는 여전히 Naive_Profile이 우위** |
| 2.5 | 학습 기간 스케일 확장(3→12개월) | top300은 09m에서 direction_accuracy 역전 성공. stratified300은 격차 감소하나 역전 못 함(12m 미완료) |
| 3 | station 정적 feature(거리·구·rack) | 소폭 개선되나 direction_accuracy 문제 근본 해결은 못 함 |

**핵심 결론**: MAE/R²(오차 크기)는 Phase 2부터 꾸준히 Naive_Profile을 이기지만, **"오를지 내릴지 방향"을 맞추는 문제는 top300+9개월 이상 스케일에서만 풀렸고, stratified300(station 표본이 더 다양한 경우)은 아직 못 풀었다.** 이건 데이터 양보다 station 표본 구성(활동량 낮은 station 포함 여부)이 더 큰 변수일 수 있음을 시사한다.

---

## Phase 0 — 데이터 검증

**목적**: `target_net_flow` 생성 데이터가 이후 모든 Phase가 신뢰할 수 있는 상태인지 검증.

| 항목 | top300 | stratified300 |
|---|---|---|
| station 매칭(train∩valid∩test) | 300/300 (100%) | 300/300 (100%) |
| target=0 비율 | - | 최대 82.5% |

**판정**: PASS. 다만 stratified300은 target=0 비율이 높아 모델링 난이도가 top300보다 원천적으로 높음 — 이후 Phase들에서 stratified300 성능이 계속 낮게 나오는 배경 중 하나.

## Phase 1 — 최소 feature baseline (B안)

**목적**: recent-OD 없이 서비스 시점에 만들 수 있는 최소 feature(재고 상태 + 시간/요일 주기성)만으로 유의미한 예측이 되는지 확인.

- **top300**: LightGBM이 MAE만 근소 우위, R²/방향성/decrease_recall은 Naive_Profile이 전반적으로 우세
- **stratified300**: 같은 패턴이 더 뚜렷함 — tree 모델 direction_accuracy 급락(0.269→0.155)

**판정**: Phase 2(과거 프로파일 feature) 필요성 확인. stratified300에서 문제가 더 명확히 드러남.

## Phase 2 — 과거 OD 프로파일 feature 추가

**목적**: station×요일×시간대 과거 평균/표준편차를 feature로 직접 제공하면 방향성 예측이 개선되는지 확인.

| | top300 | stratified300 |
|---|---|---|
| best model | LightGBM | LightGBM |
| MAE | 1.0045 < Naive 1.0225 | 0.5616 < Naive 0.5781 |
| R² | 0.2416 > Naive 0.2194 | 0.2752 > Naive 0.2483 |
| direction_accuracy | 0.2903 < **Naive 0.3018** | 0.1665 < **Naive 0.3361** |

**판정**: MAE·R² 기준 PASS. **그러나 historical profile feature를 직접 줘도 direction_accuracy는 여전히 Naive_Profile이 우위** — 특히 stratified300은 격차가 top300의 3배 이상(거의 절반 수준). 데이터 기간만 늘리면 해결되는지 확인 필요 → Phase 2.5로 이어짐.

## Phase 2.5 — 학습 기간 스케일 확장 (3→6→9→12개월)

**목적**: Phase 1~2에서 안 풀린 direction_accuracy 격차가 "학습 데이터 부족" 때문인지 진단.

### direction_accuracy 격차 추이 (트리모델 − Naive_Profile)

| 스케일 | top300 | stratified300 |
|---|---|---|
| 03개월 | -0.0053 | -0.1275 |
| 06개월 | -0.0016 | -0.0941 |
| 09개월 | **+0.0014**(첫 역전) | -0.0862 |
| 12개월 | +0.0004(역전 유지) | 미완료(OOM/hang 8회 반복, 다음 세션 과제) |

**판정**: **top300은 가설 지지** — 09개월부터 트리 모델이 Naive를 direction_accuracy에서도 앞섬. **stratified300은 가설 기각에 가까움** — 격차가 줄어드는 방향은 맞지만(개선 속도는 06→09월 구간에서 4배 이상 둔화) top300만큼 좁혀지지 않고 역전도 못 함.

**핵심 발견**: 같은 03개월 스케일에서도 top300(-0.0053)과 stratified300(-0.1275) 격차가 **24배** 차이 난다. → "스케일이 격차를 줄인다"는 가설만으로는 불충분하고, **station 표본 구성(활동량 낮은/희소한 station 포함 여부)이 스케일보다 direction_accuracy에 더 큰 영향**을 줄 수 있음.

**부수 성과(버그 수정 3건, 이후 모든 실험에 적용됨)**:
1. XGBoost GPU가 VRAM 초과로 대규모 데이터에서 15배까지 느려짐 → CPU로 전환
2. stratified300 station dtype이 train∩valid만으론 부족해 test 매칭 실패 → train∪valid∪test 스캔으로 수정
3. 대규모에서 station id를 문자열로 다루면 메모리 폭발(28배 차이 실측) → category dtype 고정 지정으로 수정

## Phase 3 — station 정적 feature (좌표/구/rack_count/지하철·버스 도보거리)

**목적**: station_id 범주형 인코딩만으로 못 잡는 station별 물리적 특성(대중교통 접근성 등)이 추가 정보를 주는지 확인.

| | top300 | stratified300 |
|---|---|---|
| best model | LightGBM | LightGBM |
| MAE | 1.0045 < Naive 1.0225 | 0.5616 < Naive 0.5781 |
| R² | 0.2416 > Naive 0.2194 | 0.2752 > Naive 0.2483 |
| direction_accuracy | 0.2903 < Naive 0.3018 | 0.1665 < Naive 0.3361 |

**station 거리 feature 자체의 품질 검증**(`station_distance_report.md`): K값 수렴 검증(K=25/20 vs K=50) 차이 0%, OSRM 실패율 0%, 지하철 평균 569m/버스 평균 115m — 데이터 품질은 문제없음.

**판정**: MAE/R²는 Phase 2와 동일 수준으로 PASS 유지되지만, **direction_accuracy 문제는 이 feature로도 해결되지 않음**(Phase 2와 수치가 거의 동일 — station 정적 feature 추가만으로는 방향성 예측력에 유의미한 개선이 없었음을 시사). Phase 2.5의 발견(station 표본 구성 문제)과 연결하면, 문제는 "정적 속성 정보 부족"이 아니라 다른 원인(예: 희소 station의 절대적 샘플 수 부족, 혹은 방향성 자체가 이 feature들로는 설명 안 되는 다른 요인에 좌우됨)일 가능성.

---

## 종합 시사점

1. **회귀 정확도(MAE/R²)는 Phase 2부터 꾸준히 풀렸다** — historical profile feature 하나로 Naive_Profile을 안정적으로 이김.
2. **방향성(direction_accuracy)은 훨씬 어려운 문제였다** — feature를 추가하는 것(Phase 2, 3)만으로는 안 풀리고, **데이터 양을 늘리는 것(Phase 2.5)이 top300에서는 통했지만 stratified300에서는 부분적으로만 통했다.**
3. **다음으로 봐야 할 가설**: station 표본 구성(top300=활동량 상위 300개 vs stratified300=다양한 활동량대 300개)이 방향성 예측력에 미치는 영향 — Phase 3 정적 feature로 이 차이를 설명 못 했다는 게, 순수히 "샘플이 적은 station은 패턴 자체가 불규칙하다"는 통계적 한계일 가능성을 시사한다.

## 산출물 위치

| Phase | 경로 |
|---|---|
| 0~2 | `AI/validation/BYC/q3-seasonal-dataset-check/outputs/` |
| 2.5 | `AI/validation/BYC/q3-seasonal-dataset-check/outputs/phase2.5/`, 상세 로그는 `progress_report.md` |
| 3 | `AI/validation/BYC/phase3-station-static/outputs/`, 데이터 검증은 `AI/data/EXTERNAL/station/processed/station_distance_report.md` |
| 로드맵 전체 현황 | `AI/validation/BYC/experiment-plan.md` §9 |
