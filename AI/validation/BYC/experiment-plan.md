# 따릉이 ETA 기반 도착 예상 재고 예측 — 실험 실행 계획

앞으로 이 문서를 기준으로 작업한다.

## 1. 서비스 정의

```text
입력:
- 대여소 ID
- 현재 재고 API 값
- ETA
- 시간/요일/공휴일
- 날씨
- 과거 대여/반납 패턴
- 정류장 위치/거치대/생활인구/행사 등

모델 출력:
- ETA 동안 예상 순증감량 (predicted_net_flow)

서비스 출력:
- 도착 예상 재고 = current_stock(API) + predicted_net_flow
- 부족 위험도 (shortage_risk)
```

## 2. Target 정의

```text
target_net_flow(t, h)
= sum(return_count_5m, t+5 ~ t+h) − sum(rent_count_5m, t+5 ~ t+h)
```

target은 OD 이벤트(대여/반납)만으로 정의한다. 재고 관측치의 변화량을 target으로 쓰지 않는다 — 시간별
재고 관측치는 운영 개입·회수 같은 비이용 요인의 영향을 받을 수 있어서, 그대로 target으로 쓰면 모델이
예측해야 할 대상이 불분명해진다. target을 OD 이벤트 기반으로 한정하면 모델이 예측하는 대상이
"이용자 행동(대여/반납)"으로 명확해진다.

재고 수준 지표(MAE/RMSE, shortage 시뮬레이션)는 `target_stock`(= current_stock + target_net_flow 누적)을
참고 지표로 별도 계산한다. 학습 target으로는 쓰지 않는다.

**생성 방법**: `AI/data/processed/BYC/stock_q3_mapped_netflow_v5/`에 좌표 기반 station 매핑과
함께 `target_net_flow`가 이미 계산된 상태로 전달받는다(station별 5분 단위 `rent_count_5m`/
`return_count_5m`를 forward rolling sum한 값). 8절 "작업 현황" 참고.

## 3. Feature 설계

### 3.1 A안 / B안

두 갈래로 나눠서 실험한다.

```text
A안 (배포 불가, 상한 성능·파이프라인 검증 전용):
rent_count_5m, return_count_5m, net_delta_5m,
rent_recent_15m, return_recent_15m, net_recent_15m/30m/60m,
stock_delta_prev_5m/15m/60m

B안 (배포 가능, 최종 baseline 후보):
station_id, horizon_min, known_stock_at_request(3.2절), stock_ratio,
hour, minute, day_of_week, is_weekend, month, sin/cos_hour, sin/cos_dow,
historical_* profile(Phase 2), 정류장 정적 정보(Phase 3), 날씨/공휴일(Phase 4),
생활인구 프로파일(Phase 5), 행사/POI(Phase 6, 후순위)
```

A안은 recent-OD를 포함해 모델이 낼 수 있는 상한 성능과 데이터 파이프라인 정합성을 확인하는 용도로만
쓴다. **최종 baseline 선정은 B안으로만 한다.**

### 3.2 재고 입력 — known_stock_at_request

재고 입력은 다음 3개 feature로 구성한다.

```text
known_stock_at_request     : 요청 시점에 알 수 있는 재고값
known_stock_source         : 값의 출처 (hourly_anchor / realtime_api)
minutes_since_stock_anchor : 그 값이 얼마나 오래된 정보인지(분)
```

| 상황 | known_stock_at_request | known_stock_source | minutes_since_stock_anchor |
|---|---|---|---|
| 학습(과거 데이터) | 요청 시점 이전 가장 최근 시간별 재고 anchor | `hourly_anchor` | 요청 시점 − anchor 시점(분) |
| 서비스(실배포) | 실시간 재고 API 값 | `realtime_api` | 0 |

이렇게 구성하면 모델이 "정보가 신선할 때"와 "오래됐을 때"를 구분해서 학습하고, 재고 입력의
신선도 차이를 명시적인 feature로 다룰 수 있다.

### 3.3 A안 재평가 조건

A안(recent-OD)을 배포 불가로 두는 전제는 "상시 모니터링이 없어 서비스 시점에 recent flow를 알 수
없다"는 것이다. 이 전제는 고정이 아니다 — BE가 Kafka/Redis 기반으로 정류장별 recent flow(최근
5/15/60분 대여·반납)를 안정적으로 서비스에 제공할 수 있게 되면, 이 전제가 무효화된다.

```text
재평가 조건: bike.stock Kafka 토픽이 실제로 운영되고, Redis의 recent flow가
            SLA(신선도) 안에서 안정적으로 유지될 때
재평가 시 조치: recent flow feature를 A안에서 B안(배포 가능)으로 재분류하고,
              배포 후보로 재실험한다
```

지금은 이 조건이 충족되지 않았으므로 A안은 여전히 상한 성능·진단용으로만 쓴다. 조건이 충족되면
이 절을 갱신하고 3.1절의 A안/B안 구분도 다시 정리한다.

## 4. 데이터 범위 원칙

**station 표본 원칙 (신규)**: Phase 1부터는 top300(이용량 상위 300개)과 stratified300(상위
20%/중위60%/하위20% 구간에서 90/120/90개, 이용량 계층별 대표 표본) 두 데이터셋을 각 Phase마다
같이 돌린다. top300만으로는 고이용 정류장 편향이 있어 일반화 여부를 확인할 수 없다는 게
Phase 1에서 확인됐다(direction accuracy가 stratified300에서 tree 모델만 크게 떨어짐). 두
데이터셋 결과가 갈리면 stratified300 결과를 더 신뢰한다(전체 정류장 대표성이 높음).

```text
Phase 0~2, 2.5(3개월 구간) : 2024 Q3 데이터로 진행 (신규 수집 불필요)
Phase 2.5(6/9/12개월 구간)  : 계절을 넘나드는 데이터 필요 (승인 후 개별 요청)
Phase 3(정류장 정적 정보)   : 시간 무관, 정류장당 1회성 조회 (소규모 신규 수집)
Phase 4(날씨/공휴일)        : Phase 2.5 결과로 확정된 범위와 동일 기간
Phase 5(생활인구)           : Phase 2.5 결과로 확정된 범위와 동일 기간
Phase 6(행사/POI)           : 데이터 품질 확인 후 별도 판단

historical profile(Phase 2) 원칙:
"historical profile feature는 평가 대상 기간(valid/test)의 OD를 사용해 만들지 않는다."
→ Train 기간 OD만으로 station × day_of_week × time-bin 프로파일을 생성하고, valid/test에는 조인만 한다.
```

## 5. Phase 로드맵

```text
Phase 0.  데이터 검증 + target 생성          (Q3, 신규 수집 불필요)
Phase 1.  B안 최소 배포 가능 feature baseline (Q3, 신규 수집 불필요)
Phase 2.  과거 OD 프로파일 추가               (Q3, 신규 수집 불필요, leakage 주의)
Phase 2.5 데이터 스케일 / 계절 확장 실험       (3→6→9→12개월, 6개월부터 신규 수집)
Phase 3.  정류장 정적 정보 (lat/lon/district/rack_count/지하철·버스 거리)
Phase 4.  날씨/공휴일 (현재/예보로 대체 가능한 컬럼만)
Phase 5.  생활인구 프로파일 (실측 vs 과거 프로파일 분리, baseline은 프로파일 기준)
Phase 6.  행사/POI (데이터 품질 확인 후 선택적으로)
Phase 7.  Sequence 모델 (Tree 모델이 부족할 때만, 배포 가능한 sequence만)
```

정류장 정적 정보(Phase 3)는 수집 비용이 낮고 leakage 위험이 없어 날씨(Phase 4)보다 앞에 둔다.

## 6. Phase 0 상세

### 목적

master 데이터에서 `target_net_flow`를 생성하고, 이후 모든 Phase가 신뢰하고 쓸 수 있는 상태인지 검증한다.

### 검증 항목

```text
1.  스키마 검증
2.  split 경계 검증 (train/valid/test 날짜 범위, 겹침 없음)
3.  station_id 매칭률 (train ∩ valid ∩ test 교집합 기준)
4.  horizon별 row 수
5.  target_net_flow 분포 (mean/std/percentile)
6.  target_net_flow = 0 비율
7.  감소/유지/증가 class(direction) 비율
8.  feature leakage 점검 (예측 시점 이후 정보가 feature에 섞였는지)
9.  known_stock_at_request 사용 가능 시점 검증 (anchor staleness 분포)
10. 이상치 station/시간대 flag (exception 집중 구간 등)
```

### 산출물

```text
dataset_report.md
target_distribution.csv
station_coverage.csv
split_boundary_check.csv
horizon_distribution.csv
direction_distribution.csv
feature_availability_matrix.csv
leakage_check_report.md
data_quality_flags.csv
```

`feature_availability_matrix`는 이후 모든 Phase에서 "이 feature를 B안에 넣어도 되는가"를 판단하는
기준표 역할을 한다.

| feature | 학습 가능 | 서비스 가능 | 최종 baseline 사용 |
|---|---|---|---|
| recent_net_15m | 가능 | 불가 | 제외 (A안 전용) |
| historical_profile_net | 가능 | 가능 | 포함 |
| known_stock_at_request | 가능(anchor 대체) | 가능(실시간 API) | 포함 |
| weather_current | 가능 | 가능 | 포함 |
| future_weather_observed | 가능 | 불가 | 제외 |

### 완료 판정 기준

```text
station 매칭: train ∩ valid ∩ test 교집합으로 실험 대상 station을 정한다
coverage 95% 이상 → PASS, 미만 정류장은 제외 후보로 flag
horizon 4종 분포 편차 일정 수준 이내 → PASS
target_net_flow=0 비율 과도(예: 90%+) → WARN, 모델링 의미 재검토
특정 정류장/시간대에 exception·이상치 집중 → WARN, Phase 2 프로파일 계산 시 제외 후보
```

## 7. Phase 1 상세

### 목적

recent-OD 없이, 서비스 요청 순간 만들 수 있는 최소한의 feature만으로 모델이 유의미한 예측을
하는지 확인한다. 최종 baseline을 확정하는 단계가 아니라 "이 최소 정보로도 예측이 되는가"를
보는 단계다.

### 확인하려는 것 — 두 축

```text
1. 지금 재고 상태 자체가 미래를 예측하는 신호가 되는가
   → 정류장이 꽉 차있으면(is_full_anchor=1) 대여가 늘어 줄어들 가능성이 높고,
     비어있으면(is_empty_anchor=1) 반납이 늘어 늘어날 가능성이 높은
     평균회귀(mean-reversion) 패턴이 있는지

2. 시간대/요일/계절 패턴이 신호가 되는가
   → 출퇴근 시간대, 주중/주말, 낮/밤 같은 반복 패턴이 있는지
```

이 두 축만으로 "station × 요일 × 시간대 과거 평균"(Naive_Profile)보다 더 잘 맞추는 모델을
만들 수 있는지가 핵심 질문이다. 날씨·정류장 위치·recent OD 흐름은 이 단계에서 다루지 않는다.

### Feature 정의 — 진짜 최소셋만

```text
station_id   : od_station_id (범주형 → station_code로 인코딩)
horizon_min
known_stock  : stock_anchor_hour, stock_ratio_hour, minutes_since_stock_anchor,
               is_empty_anchor, is_full_anchor
시간/주기성   : hour, minute, day_of_week, is_weekend, month,
               sin_hour, cos_hour, sin_slot, cos_slot
```

**의도적으로 제외**: `rack_count`, `lat_stock`, `lon_stock`, `district`(Phase 3) — 데이터에
이미 조인돼 있지만, `od_station_id`가 이미 범주형으로 station별 고유 패턴을 잡아주기 때문에
(train/valid/test에 300개 정류장이 전부 동일하게 존재), 이 4개가 station_id 대비 얼마나
"추가" 정보를 주는지는 Phase 3에서 station_id-only 대비로 격리해서 측정한다. historical
profile(Phase 2)·날씨(Phase 4)는 애초에 데이터에 없어 이 단계에서 만들 수 없다.

**절대 안 씀(A안 전용)**: `rent_count_5m`, `return_count_5m`, `net_flow_5m`

### Target

```text
target_net_flow   (회귀)
```

### 모델 후보 4개

```text
1. Naive_Profile   : station × day_of_week × hour 별 과거 평균 target_net_flow
                     (Train만으로 lookup 테이블 생성 → valid/test엔 조인만, horizon_min별로도 분리)
2. RandomForest    : train 샘플 100만~300만 rows
3. XGBoost         : 가능하면 전체 train
4. LightGBM        : 가능하면 전체 train
```

Naive_Profile은 Phase 2의 historical profile feature와 다른 목적이다 — Phase 1의
Naive_Profile은 그 값 자체를 예측치로 내는 비교 기준선이고, Phase 2의 historical profile은
RF/XGB/LightGBM에 넣는 입력 feature다. 둘 다 train 기간 데이터로만 만든다는 원칙은 같다.

### 평가 지표

```text
회귀        : Net Flow MAE, RMSE, WAPE, R²
방향성      : Direction Accuracy, Direction Macro-F1 (decrease/stable/increase)
감소위험    : Decrease Precision/Recall/F1
서비스 시뮬 : simulated_arrival_stock = stock_anchor_hour + predicted_net_flow
             simulated_shortage = simulated_arrival_stock <= 2   (참고 지표)
운영        : 학습 시간, 추론 rows/sec, 모델 파일 크기
```

horizon(5/10/15/30분)별로도 따로 집계한다.

### 완료 판정 기준

```text
트리 모델(RF/XGB/LGBM) 중 최소 1개가 Naive_Profile보다 Net Flow MAE/WAPE가 낮으면
→ 최소 feature로도 예측이 됨 → Phase 2로 진행

전부 Naive_Profile보다 못하면
→ 실패가 아니라 "historical profile 없이는 부족하다"는 근거로 취급하고 Phase 2로 진행
```

### 구현 위치

```text
AI/validation/BYC/q3-seasonal-dataset-check/
  src/phase1_baseline.py   (신규)
  outputs/phase1/          (신규 산출물 폴더 — model_comparison.csv, model_comparison_by_horizon.csv,
                             feature_importance.csv, metrics.json, best_model.pkl)
```

## 8. Phase 2 상세

### 프로파일 정의

Naive_Profile(Phase 1)과 같은 그룹 기준으로 train 데이터에서 통계를 뽑아 feature로 만든다.

```text
group by: od_station_id × day_of_week × hour × horizon_min

historical_net_flow_mean   : 그룹의 target_net_flow 평균
historical_net_flow_std    : 그룹의 target_net_flow 표준편차
historical_rent_mean       : 그룹의 target_rent_count 평균
historical_return_mean     : 그룹의 target_return_count 평균
historical_profile_fallback_level : 0=정확한 조합, 1=(station,horizon) 대체, 2=전체 평균 대체
```

`fallback_level`은 표본 부족 구간을 모델이 덜 신뢰할 근거로 구분할 수 있게 하는 신규 feature다.

### Feature 구성

```text
Phase 1 최소셋 (그대로 유지) + 위 5개 historical_* feature
```

여전히 제외: `rack_count`/`lat_stock`/`lon_stock`/`district`(Phase 3), 날씨(Phase 4), recent OD(A안)

### Leakage 방지

```text
프로파일은 train 기간 데이터로만 계산(fit)
valid/test에는 station×dow×hour×horizon 키로 조인만(재계산 없음)
fallback 순서: (station,dow,hour,horizon) → (station,horizon) → (horizon 전체)
```

### 모델 후보 — Phase 1과 동일 4개

Naive_Profile, RandomForest, XGBoost, LightGBM. Naive_Profile은 비교 기준선으로 계속 유지해
Phase가 진행될수록 격차가 좁혀지는지 추적한다.

### 평가 지표 — Phase 1과 동일

MAE/RMSE/WAPE/R², Direction Accuracy/Macro-F1, Decrease Precision/Recall/F1, 서비스 시뮬레이션,
운영지표. horizon별 집계.

### 완료 판정 기준 (Phase 1보다 강화)

```text
Phase 1: MAE만 근소 우위 → 애매한 결과였음
Phase 2: 트리 모델이 Naive_Profile 대비 MAE와 R² 둘 다에서 명확히 앞서야 통과
         (historical profile을 직접 줬는데도 못 이기면 원인 재분석 필요)
```

### 구현 위치

```text
AI/validation/BYC/q3-seasonal-dataset-check/
  src/phase2_historical_profile.py   (신규)
  outputs/phase2/                    (top300)
  outputs/stratified/phase2/         (stratified300)
```

## 9. 작업 현황

```text
데이터 위치:
  AI/data/processed/BYC/stock_q3_mapped_netflow_v5/              (top300)
  AI/data/processed/BYC/stock_q3_mapped_netflow_stratified300/   (stratified300)
  → 둘 다 좌표 기반 station 매핑 + target_net_flow가 이미 계산된 상태로 전달받음.

AI/validation/BYC/stock-delta-baseline-check/
  → A안(recent-OD 포함) 실험 결과물. 상한 성능 참고용으로만 사용하고,
    최종 baseline 후보로 사용하지 않는다.

AI/validation/BYC/q3-seasonal-dataset-check/
  → B안 실험 진행 디렉터리.
  src/dataset_report_v5.py, src/phase1_baseline.py는 --file-tag로 top300/stratified300
  둘 다 지원한다 (outputs/ = top300, outputs/stratified/ = stratified300).

진행 상황:
  Phase 0 (top300)         : PASS (station 매칭 300/300, 100%)
  Phase 0 (stratified300)  : PASS (station 매칭 300/300, 100%, target=0 비율 최대 82.5%)
  Phase 1 (top300)         : 완료. LightGBM이 MAE만 근소 우위, R²/방향성/decrease_recall은
                              Naive_Profile이 전반적으로 우세 → Phase 2 필요성 확인
  Phase 1 (stratified300)  : 완료. 같은 패턴이 더 뚜렷함(tree 모델 direction accuracy 급락:
                              0.269→0.155). Phase 2 필요성이 top300보다 더 명확히 드러남
```

## 10. 참고 진단 실험 — Sequence 모델 상한 성능 (Phase 순서 밖, A안)

정식 Phase 0~7 순서와 별개로, 참고용으로 먼저 해볼 수 있는 진단 실험이다. Phase 7(Sequence
모델)의 정식 진입 조건(Phase 1~6 완료 + tree 모델 부족 확인)을 기다리지 않고, "recent OD를
쓸 수 있다면 GRU/LSTM이 상한으로 얼마나 나오는가"만 미리 확인한다.

```text
목적: recent OD 시퀀스 기반 GRU/LSTM의 상한 성능 확인 (tree 모델 A안과 같은 성격)
데이터: rent_count_5m/return_count_5m/net_flow_5m을 station별 시계열로 정렬해
        최근 N개 시점을 이어붙인 시퀀스로 구성
모델: GRU 또는 LSTM (단순 구조로 시작)
target: target_net_flow (동일)
```

**결과 해석 원칙**:

```text
1. 이 실험은 B안 baseline 선정에 어떤 단계에서도 영향을 주지 않는다.
2. 성능이 좋게 나와도 이 모델 자체를 배포하지 않는다 — recent OD를 서비스 시점에
   만들 수 없다는 사실은 변하지 않는다.
3. 성능이 좋게 나오면, "이 모델을 반영"하는 게 아니라:
   a. 카프카/레디스(3.3절 재평가 조건) 투자를 정당화하는 근거자료로 쓴다.
   b. 인프라가 갖춰진 뒤, 실제로 배포 가능해진 recent flow(예: Redis 기반
      recent_stock_net_delta)로 같은 계열의 모델을 처음부터 다시 학습한다.
4. 정식 Phase 7과는 별개 실험이므로 산출물도 outputs/diagnostic_sequence/ 처럼
   분리해서 둔다.
```

## 11. 원칙 요약

```text
A안은 상한 성능과 진단용으로만 사용한다.
B안만 최종 baseline 선정 기준으로 사용한다.
feature 추가 실험은 배포 가능 여부를 기준으로 단계적으로 수행한다.
target은 OD 이벤트 기반 순증감량으로 정의한다.
historical profile은 평가 대상 기간의 OD를 사용해 만들지 않는다.
```
