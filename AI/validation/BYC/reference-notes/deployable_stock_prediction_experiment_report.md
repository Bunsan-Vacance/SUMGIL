# 따릉이 ETA 기반 도착 예상 재고 예측 실험 계획 보고서

## 1. 결론 요약

우리 서비스는 상시 모니터링을 하지 않는다. 따라서 서비스 시점에 사용할 수 있는 정보는 제한된다.

서비스에서 가능한 입력은 다음이다.

```text
1. 사용자 경로 조회 시점에 호출한 현재 재고 API 값
2. ETA
3. 시간/요일/공휴일
4. 현재 또는 예보 기반 날씨
5. 과거 데이터로 만든 정류장별 시간대 패턴
6. 정류장 위치/거치대/주변 환경
7. 과거 프로파일 기반 생활인구/유동인구
```

반대로 서비스 시점에 사용할 수 없는 정보는 다음이다.

```text
직전 5분 실제 OD 대여량
직전 15분 실제 OD 반납량
직전 60분 실제 순증감량
실시간으로 누적한 정류장별 5분 재고 변화
```

따라서 최종 모델은 **실시간 recent OD를 쓰는 모델이 아니라, 조회 순간 현재 재고와 배포 가능한 feature만 사용하는 모델**이어야 한다.

최종 서비스 식은 다음이다.

```text
demand_based_arrival_stock
= realtime_current_stock + predicted_net_flow
```

모델 target은 다음으로 둔다.

```text
target_net_flow(t, h)
= t 이후 h분 동안의 반납 건수 합계 - 대여 건수 합계
```

## 2. 현재 문제

현재 가장 중요한 문제는 **학습 데이터에서 쓸 수 있는 feature와 실제 서비스에서 쓸 수 있는 feature가 다르다**는 점이다.

과거 OD 데이터로는 다음 값을 만들 수 있다.

```text
최근 5분 대여량
최근 15분 반납량
최근 60분 순증감량
```

하지만 운영 시점에는 상시 모니터링을 하지 않기 때문에, 사용자가 경로 조회를 요청하는 순간 직전 5분/15분/60분의 실제 OD 흐름을 알 수 없다.

즉 다음과 같은 실험은 가능하지만, 그대로 서비스할 수 없다.

```text
X = 현재 재고 + 직전 실제 OD 흐름 + 시간/날씨/정류장 feature
y = 향후 net_flow
```

이 실험은 성능이 좋게 나와도 실제 배포 모델로 쓰기 어렵다.

따라서 최종 baseline 선정은 반드시 다음 조건으로 해야 한다.

```text
서비스 요청 순간 만들 수 있는 feature만 사용한다.
```

## 3. A안과 B안의 의미

## 3.1 A안: 실제 recent OD 포함 실험

A안은 과거 데이터 기준으로 직전 5분/15분/60분 실제 OD 흐름을 feature로 사용하는 실험이다.

예시 feature:

```text
recent_rent_5m
recent_return_5m
recent_net_15m
recent_net_60m
```

장점:

```text
모델이 낼 수 있는 상한 성능을 확인할 수 있다.
최근 흐름 feature가 얼마나 강력한지 알 수 있다.
데이터셋과 target 생성이 맞는지 빠르게 검증할 수 있다.
```

한계:

```text
상시 모니터링이 없으면 서비스 시점에 만들 수 없다.
최종 배포 모델로 사용할 수 없다.
성능이 높아도 실제 서비스 성능을 대표하지 않는다.
```

따라서 A안의 목적은 다음으로 제한한다.

```text
학습 파이프라인 검증
모델 성능 상한선 확인
recent flow feature의 가치 측정
논문/실험 보고서의 보조 비교군
```

## 3.2 B안: 배포 가능 feature만 사용하는 실험

B안은 사용자가 경로 조회를 요청한 순간 실제로 만들 수 있는 feature만 사용한다.

예시 feature:

```text
realtime_current_stock
stock_ratio
ETA
hour
minute
day_of_week
is_weekend
is_holiday
weather
station_id
lat
lon
rack_count
historical_station_time_profile
historical_net_flow_mean
historical_net_flow_std
living_population_profile
event_feature_if_available
```

장점:

```text
실제 서비스 구조와 일치한다.
성능 지표가 배포 가능성을 판단하는 기준이 된다.
API 서빙 구조로 바로 연결할 수 있다.
```

한계:

```text
직전 실제 OD 흐름을 쓰는 A안보다 성능이 낮을 수 있다.
과거 평균 패턴과 외부 feature 품질에 의존한다.
급격한 실시간 수요 변화에는 약할 수 있다.
```

최종 baseline 모델은 B안 기준으로 선정한다.

## 4. 왜 A안도 실험하는가

A안은 서비스에 직접 쓰기 위한 실험이 아니다. 그래도 실험할 이유는 있다.

첫째, **상한 성능**을 확인할 수 있다.

```text
A안 성능이 B안보다 훨씬 좋다
→ recent flow가 매우 중요하다는 의미
→ 향후 상시 모니터링 또는 실시간 OD 대체 feature 도입 가치가 있음
```

둘째, **데이터 생성 로직 검증**에 유용하다.

```text
OD target_net_flow 생성
horizon별 라벨 생성
모델 학습/평가 파이프라인
```

이 단계에서 문제가 있으면 B안 실험도 신뢰하기 어렵다.

셋째, **feature ablation 기준점**으로 쓸 수 있다.

```text
A안: 실제 최근 흐름을 알 때의 성능
B안: 배포 가능한 과거 프로파일만 쓸 때의 성능
```

둘의 차이가 크면 서비스 성능 한계가 어디서 오는지 설명할 수 있다.

하지만 최종 의사결정은 B안으로 한다.

## 5. 최종 문제 정의

최종 모델은 재고 자체를 직접 예측하지 않는다.

모델은 다음 값을 예측한다.

```text
predicted_net_flow
= ETA 동안 예상되는 반납 수 - 대여 수
```

서비스는 경로 조회 시 현재 재고 API를 호출한다.

```text
current_stock = realtime_stock_api(station_id)
```

그 뒤 모델 예측값을 더한다.

```text
predicted_arrival_stock
= current_stock + predicted_net_flow
```

표시 단계에서는 재고 범위를 보정한다.

```text
display_stock = max(0, predicted_arrival_stock)
```

부족 위험은 다음처럼 계산한다.

```text
shortage_risk = predicted_arrival_stock <= 2
```

## 6. 사용할 데이터셋

## 6.1 Label 생성용 데이터

정답 label은 5분 OD 데이터에서 직접 만든다.

```text
target_net_flow(t, h)
= sum(return_count_5m from t+5 to t+h)
- sum(rent_count_5m from t+5 to t+h)
```

horizon:

```text
5분
10분
15분
30분
```

이 target은 실제 관측된 이용자 대여/반납 흐름이다.

## 6.2 Feature용 데이터

1시간 재고 데이터는 label이 아니라 feature로 사용한다.

```text
stock_anchor_hour
stock_ratio_hour
is_empty_anchor
is_full_anchor
```

주의:

```text
예측 시점 이후의 재고 anchor는 feature로 사용하면 안 된다.
```

예를 들어 14:35를 예측할 때 사용할 수 있는 것은 14:00 재고 anchor 또는 서비스 시점 현재 재고 API 값이다. 15:00 재고는 미래 정보이므로 사용할 수 없다.

## 7. Feature Set 실험 순서

## 7.1 Phase 0: 데이터 검증

목적:

```text
OD 기반 target_net_flow가 정상 생성되는지 확인
station_id 매칭률 확인
horizon별 row 수 확인
target=0 비율 확인
```

산출물:

```text
dataset_report.md
target_distribution.csv
station_coverage.csv
```

## 7.2 Phase 1: 배포 가능 최소 feature

서비스에서 반드시 만들 수 있는 feature만 사용한다.

Feature:

```text
station_id
horizon_min
stock_anchor_hour 또는 realtime_current_stock에 해당하는 current_stock
stock_ratio
hour
minute
day_of_week
is_weekend
month
sin_hour
cos_hour
sin_day_of_week
cos_day_of_week
```

모델:

```text
Naive_Profile
RandomForest
XGBoost
LightGBM
```

목적:

```text
배포 가능한 최소 입력만으로 예측이 되는지 확인
```

## 7.3 Phase 2: 과거 OD 프로파일 추가

실시간 recent OD가 아니라, 과거 데이터로 미리 만든 정류장별 시간대 평균 패턴을 사용한다.

Feature:

```text
historical_net_flow_mean_by_station_dow_time
historical_net_flow_std_by_station_dow_time
historical_rent_mean_by_station_dow_time
historical_return_mean_by_station_dow_time
historical_shortage_like_flow_rate
```

예:

```text
ST-102는 월요일 18:30~18:45에 평균 net_flow가 -2.3대
```

목적:

```text
최근 실시간 흐름 없이도 과거 반복 패턴으로 수요 변화를 설명할 수 있는지 확인
```

이 Phase가 실제 서비스 baseline의 핵심이다.

## 7.4 Phase 3: 날씨/공휴일 추가

Feature:

```text
temperature
rainfall
humidity
wind_speed
snow
is_holiday
is_before_holiday
is_after_holiday
```

주의:

```text
서비스에서는 현재 날씨 또는 예보 값을 써야 한다.
과거 학습에서는 관측 날씨를 쓰되, 배포 가능성을 고려해 예보 대체 가능성을 기록한다.
```

목적:

```text
비, 기온, 휴일이 수요 기반 순증감 예측에 주는 효과 측정
```

## 7.5 Phase 4: 정류장 정적 정보 추가

Feature:

```text
lat
lon
district
rack_count
near_subway_distance
bus_stop_count_300m
is_near_park
is_near_river
```

목적:

```text
station_id만으로 부족한 공간 특성을 보완
고수요/저수요 정류장 간 차이 설명
```

## 7.6 Phase 5: 생활인구/유동인구 프로파일 추가

실제 생활인구 데이터는 지연 공개될 수 있으므로, 배포 후보에는 과거 프로파일을 우선 사용한다.

Feature:

```text
living_population_profile_by_grid_dow_hour
living_population_lag_profile
living_population_change_profile
working_population_profile
resident_population_profile
```

목적:

```text
시간대별 활동 규모가 순증감량 예측에 기여하는지 확인
```

실험은 둘로 나눠도 된다.

```text
5-A. 실제 관측 생활인구 사용
  → 성능 상한 확인

5-B. 과거 평균 생활인구 프로파일 사용
  → 배포 가능 모델 평가
```

최종 baseline 선정은 5-B 기준으로 한다.

## 7.7 Phase 6: 행사/POI 추가

Feature:

```text
event_count_nearby
event_type
event_distance_min
poi_count_park
poi_count_school
poi_count_business
```

목적:

```text
특정 시간과 장소에서 발생하는 급격한 수요 변화를 설명할 수 있는지 확인
```

행사 feature는 데이터 품질과 과거 이력 확보가 어려우므로 후순위다.

## 7.8 Phase 7: Sequence 모델 검토

Tree 모델 실험 후 필요할 때만 GRU/LSTM을 테스트한다.

단, 상시 모니터링이 없기 때문에 GRU/LSTM도 실시간 recent OD를 입력으로 쓰면 배포 불가능하다.

GRU/LSTM을 쓰려면 sequence도 배포 가능한 값으로 구성해야 한다.

가능한 sequence:

```text
과거 프로파일 sequence
시간/날씨 예보 sequence
현재 재고 API 값에서 시작하는 ETA 구간 feature sequence
```

배포 불가능한 sequence:

```text
요청 직전 60분 실제 OD sequence
요청 직전 60분 실제 재고 snapshot sequence
```

따라서 GRU/LSTM은 다음 조건일 때만 테스트한다.

```text
XGBoost/LightGBM 성능이 부족하다.
배포 가능한 sequence feature를 만들 수 있다.
성능 개선 폭이 운영 복잡도를 감당할 만큼 크다.
```

## 8. 모델 비교 순서

각 Phase마다 같은 모델을 비교한다.

```text
1. Naive
2. RandomForest
3. XGBoost
4. LightGBM
```

대용량에서는 RandomForest는 샘플로만 돌린다.

```text
RandomForest: train sample 100만~300만 rows
XGBoost/LightGBM: 가능하면 전체 train
```

GRU/LSTM은 Phase 7에서 별도 비교한다.

## 9. 평가 지표

모델 target이 `target_net_flow`이므로 핵심 지표는 net flow 기준이다.

회귀 지표:

```text
Net Flow MAE
Net Flow RMSE
WAPE
R2
```

방향성 지표:

```text
Direction Accuracy
Direction Macro-F1
```

방향 class:

```text
decrease: target_net_flow < 0
stable: target_net_flow = 0
increase: target_net_flow > 0
```

감소 위험 지표:

```text
Decrease Precision
Decrease Recall
Decrease F1
```

서비스 시뮬레이션 지표:

```text
simulated_arrival_stock = current_stock + predicted_net_flow
simulated_shortage = simulated_arrival_stock <= 2
```

단, 실제 5분 재고 snapshot이 없으므로 shortage 지표는 참고 지표로 둔다.

운영 지표:

```text
학습 시간
추론 rows/sec
모델 파일 크기
feature 생성 가능성
```

## 10. Train / Validation / Test

분기 실험 기준 권장 split:

```text
Train: 2024-07-01 ~ 2024-09-15
Validation: 2024-09-16 ~ 2024-09-30
Test: 2025-07-01 ~ 2025-09-30
```

이 split의 장점:

```text
같은 계절의 다음 해 테스트
미래 데이터 일반화 확인
test leakage 방지
```

주의:

```text
Test는 마지막 평가에만 사용한다.
튜닝은 Validation에서만 한다.
스케일러, 인코더, 결측 대체값은 Train에서만 fit한다.
과거 프로파일 feature도 Test 기간 정보를 사용해 만들면 안 된다.
```

## 11. 최종 baseline 선정 기준

최종 모델은 B안 기준으로 선정한다.

선정 기준:

```text
1. 배포 가능한 feature만 사용한다.
2. Naive보다 Net Flow MAE/WAPE가 낮다.
3. horizon별 성능이 안정적이다.
4. decrease recall이 높다.
5. 2025년 Q3 test에서 성능이 유지된다.
6. 추론이 빠르고 운영이 단순하다.
7. feature importance 또는 SHAP으로 설명 가능하다.
```

성능 차이가 작으면 다음 순서로 우선한다.

```text
LightGBM 또는 XGBoost
→ RandomForest
→ GRU/LSTM
```

## 12. 최종 실행 순서

최종 권장 순서는 다음이다.

```text
1. OD 기반 target_net_flow 데이터셋 재정의
2. 배포 가능 feature와 배포 불가능 feature를 분리
3. Phase 1: 최소 배포 가능 feature 실험
4. Phase 2: 과거 OD 프로파일 feature 추가
5. Phase 3: 날씨/공휴일 추가
6. Phase 4: 정류장 정적 정보 추가
7. Phase 5: 생활인구 프로파일 추가
8. Phase 6: 행사/POI는 데이터 품질 확인 후 추가
9. 각 Phase마다 Naive/RF/XGB/LGBM 비교
10. B안 기준 최종 baseline 선정
11. 필요할 때만 GRU/LSTM을 배포 가능한 sequence로 비교
12. 선택 모델을 API 서빙 구조에 연결
```

## 13. 서비스 적용 흐름

운영 시점 흐름:

```text
사용자 경로 조회 요청
→ 후보 대여소 탐색
→ 대여소별 ETA 계산
→ 현재 재고 API 호출
→ 배포 가능 feature 생성
→ predicted_net_flow 예측
→ predicted_arrival_stock = current_stock + predicted_net_flow
→ 부족 위험 계산
→ 사용자에게 후보 대여소별 도착 예상 재고 제공
```

응답 예:

```json
{
  "stationId": "ST-102",
  "etaMinutes": 10,
  "currentStock": 3,
  "predictedNetFlow": -1.4,
  "predictedArrivalStock": 1.6,
  "shortageRisk": "HIGH"
}
```

## 14. 최종 판단

기존의 “5분 복원 재고를 직접 예측”하는 방식보다, 새로 정리한 “OD 기반 순증감량 예측” 방식이 우리 서비스에 더 적합하다.

이유:

```text
1. 서비스 시점 현재 재고는 API로 조회한다.
2. 모델은 ETA 동안의 이용자 대여/반납 흐름만 예측하면 된다.
3. 운영 개입과 고장 회수 같은 비이용 변화는 예측 범위에서 제외할 수 있다.
4. OD 기반 target은 복원 재고보다 라벨 의미가 명확하다.
5. 최종 모델을 배포 가능 feature 기준으로 평가할 수 있다.
```

따라서 앞으로의 실험은 다음 원칙으로 진행한다.

```text
A안은 상한 성능과 진단용으로만 사용한다.
B안만 최종 baseline 선정 기준으로 사용한다.
feature 추가 실험은 배포 가능 여부를 기준으로 단계적으로 수행한다.
```
