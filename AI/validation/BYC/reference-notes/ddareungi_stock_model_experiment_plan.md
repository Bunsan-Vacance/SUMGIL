# 따릉이 도착 예상 재고 예측 모델 실험 계획서

## 1. 목적

본 실험의 목적은 사용자가 경로 조회를 요청했을 때, 후보 따릉이 대여소에 도착하는 시점의 예상 재고를 제공하기 위한 baseline 모델을 선정하는 것이다.

서비스에서 필요한 최종 값은 현재 재고가 아니라 도착 예상 재고다.

```text
도착 예상 재고 = 현재 재고 API 값 + ETA 동안의 예측 재고 변화량
```

따라서 모델의 학습 target은 절대 재고보다 `target_delta`를 우선 사용한다.

```text
target_delta = horizon 뒤 재고 - 현재 재고
```

예측 horizon은 사용자 도착 시간을 고려해 다음 단위로 시작한다.

```text
5분, 10분, 15분, 30분
```

## 2. 참고 프로젝트 방향

참고 저장소: [SKN29-2nd-5Team](https://github.com/SKNETWORKS-FAMILY-AICAMP/SKN29-2nd-5Team)

해당 프로젝트는 따릉이 대여소별 수요 예측을 위해 baseline, XGBoost, LightGBM, GRU를 비교하고 `MAE`, `RMSE`, `WAPE`, `R2` 기준으로 최종 모델을 선정했다.

우리 프로젝트도 다음 흐름을 차용한다.

```text
Baseline 규칙 모델
→ XGBoost
→ LightGBM
→ GRU
→ 성능 비교
→ 최종 baseline 선정
→ API 서빙
```

다만 target은 다르다.

```text
참고 프로젝트: 대여량 예측
우리 프로젝트: 도착 시점 재고 변화량 예측
```

따라서 평가 지표에도 부족 위험 예측 지표를 추가한다.

## 3. 사용할 데이터셋

### 3.1 현재 생성된 starter 데이터셋

현재 생성된 데이터셋은 2025년 9월, OD 활동량 상위 200개 정류장 기준이다.

```text
기간: 2025-09-01 ~ 2025-09-30
단위: station_id + 5분 timestamp
정류장 수: 200개
master rows: 1,728,000
training rows: 6,909,600
horizon: 5, 10, 15, 30분
```

파일 위치:

```text
C:/Users/SSAFY/Documents/Codex/2026-09-07/https-docviewer-nanet-go-kr-reader/outputs/stock_dataset_202509
```

사용 파일:

```text
train_202509_top200.csv.gz
valid_202509_top200.csv.gz
test_202509_top200.csv.gz
station_stock_5m_master_202509_top200.csv.gz
```

### 3.2 데이터셋 생성 방식

데이터셋은 다음 두 데이터를 결합해 만들었다.

```text
1시간 단위 대여소별 대여가능 수량
+ 5분 단위 OD 대여/반납 데이터
= 5분 단위 복원 재고 데이터셋
```

1시간 재고 데이터는 실제 관측 anchor로 사용한다.

```text
station_id
datetime_hour
stock_observed_hour
```

5분 OD 데이터는 대여/반납 흐름으로 변환한다.

```text
rent_count_5m = 출발시간 기준 시작 대여소별 전체 건수
return_count_5m = 도착시간 기준 종료 대여소별 전체 건수
net_delta_5m = return_count_5m - rent_count_5m
```

5분 재고는 시간별 anchor에서 시작해 OD 순증감을 누적해 복원한다.

```text
stock_reconstructed_5m(t+5)
= stock_reconstructed_5m(t) + return_count_5m - rent_count_5m
```

매 정각에는 실제 시간별 재고 anchor로 보정하고, OD로 설명되지 않는 차이는 별도 컬럼으로 남긴다.

```text
exception_delta_hour
= 실제 시간별 재고(t+1h)
- [실제 시간별 재고(t) + 1시간 OD 순증감]
```

이 값은 재배치, 고장 회수, 수리 복귀, 운영자 개입, 집계 시간 차이 등을 포함할 수 있다.

### 3.3 라벨 신뢰도

5분 단위 재고는 직접 관측값이 아니라 복원값이다.

```text
label_type = hourly_observed
  실제 시간별 재고 anchor

label_type = reconstructed
  1시간 anchor와 5분 OD 흐름으로 복원한 weak label
```

따라서 현재 실험은 “실제 5분 재고” 기준이 아니라 “복원 5분 재고” 기준 baseline 실험이다.

## 4. 학습 데이터 구조

한 row는 다음 의미를 가진다.

```text
특정 정류장의 특정 5분 시점에서
현재 재고와 최근 대여/반납 흐름, 시간 정보를 보고
horizon분 뒤 재고 변화량을 예측한다.
```

기본 feature:

```text
station_id
horizon_min
current_stock
capacity_proxy
stock_ratio_proxy
rent_count_5m
return_count_5m
net_delta_5m
rent_recent_15m
return_recent_15m
net_recent_15m
net_recent_30m
net_recent_60m
stock_delta_prev_5m
stock_delta_prev_15m
stock_delta_prev_60m
hour
minute
day_of_week
is_weekend
```

target:

```text
target_delta = horizon 뒤 재고 - 현재 재고
target_stock = horizon 뒤 재고
```

모델은 `target_delta`를 학습하고, 평가는 `target_delta`와 `target_stock` 모두 수행한다.

## 5. Train / Validation / Test

현재 starter 실험에서는 2025년 9월을 시간 기준으로 나눈다.

```text
Train: 2025-09-01 ~ 2025-09-20
Validation: 2025-09-21 ~ 2025-09-25
Test: 2025-09-26 ~ 2025-09-30
```

랜덤 split은 사용하지 않는다. 시계열 예측 문제이므로 미래 데이터가 과거 학습에 섞이면 안 된다.

## 6. 실험 순서

### 6.1 1단계: 최소 feature baseline

현재 생성된 데이터셋만 사용한다.

사용 feature:

```text
현재 재고
최근 5/15/30/60분 대여/반납 흐름
시간/분/요일/주말
정류장 ID
```

목적:

```text
학습 파이프라인 검증
복원 데이터셋이 예측 문제로 작동하는지 확인
Naive보다 ML 모델이 좋은지 확인
tree 계열 대표 모델 선정
```

비교 모델:

```text
Naive_15m_trend
Naive_60m_trend
RandomForest
XGBoost
LightGBM
```

### 6.2 2단계: 날씨/공휴일 feature 추가

추가 feature:

```text
temperature
rainfall
humidity
wind_speed
snow
pm10
is_holiday
holiday_name
is_before_holiday
is_after_holiday
```

목적:

```text
강수, 기온, 공휴일이 재고 변화량 예측에 주는 영향 확인
외부 환경 feature 추가 효과 측정
```

날씨는 시간 단위로 `datetime_hour` 기준 join한다.  
공휴일은 날짜 기준으로 join한다.

### 6.3 3단계: 정류장 공간 feature 추가

추가 feature:

```text
lat
lon
rack_count
district
near_subway_distance
near_bus_stop_count
is_near_park
is_near_river
is_business_area
is_school_area
```

목적:

```text
station_id encoding만으로 설명되지 않는 정류장 특성 반영
신규 또는 저빈도 정류장 일반화 가능성 확보
```

정류장 정보는 `station_id` 기준으로 join한다.

### 6.4 4단계: 생활인구/행사 feature 추가

추가 feature:

```text
population_flow
resident_population
working_population
event_count_nearby
event_distance_min
event_type
event_expected_people
```

목적:

```text
한강, 공원, 공연, 축제, 출퇴근 유동인구 등 특수 수요 반영
특정 시간대 급격한 재고 변화 설명력 개선
```

행사는 시간 범위와 위치 반경 기준으로 join한다.

```text
event_start <= datetime_5m <= event_end
AND distance(station, event_location) <= N meters
```

## 7. 모델 후보와 역할

### 7.1 Naive

규칙 기반 baseline이다.

```text
Naive_15m_trend:
pred_delta = net_recent_15m / 15 * horizon_min

Naive_60m_trend:
pred_delta = net_recent_60m / 60 * horizon_min
```

역할:

```text
모든 ML 모델이 반드시 이겨야 하는 최소 기준선
```

### 7.2 RandomForest

전통 ML baseline이다. 따릉이 실시간 수요예측 논문에서 RandomForest를 최종 예측 모델로 사용한 흐름을 차용한다.

역할:

```text
구현이 쉽고 안정적인 비교 기준
```

### 7.3 XGBoost

정형 데이터에서 강한 boosting tree 모델이다. 따릉이 수요 예측 GitHub 프로젝트들과 참고 프로젝트에서 핵심 후보로 사용됐다.

역할:

```text
실사용 baseline 1순위 후보
```

장점:

```text
성능이 좋음
추론이 빠름
feature importance/SHAP으로 설명 가능
현재 데이터셋 구조와 잘 맞음
```

### 7.4 LightGBM

XGBoost와 같은 boosting tree 계열이지만 대용량 tabular 데이터에서 빠른 편이다.

역할:

```text
XGBoost와 함께 최종 baseline 후보
```

### 7.5 GRU

sequence deep learning 대표 후보이다. GRU 논문에서는 LSTM보다 약간 좋은 성능과 빠른 실행시간을 보였다.

단, 현재 tabular training 파일을 바로 쓰는 것이 아니라 `station_stock_5m_master`에서 sequence dataset을 별도로 만들어야 한다.

입력 예:

```text
최근 12개 timestep = 최근 60분
X shape = [samples, 12, features]
y = target_delta
```

초기 baseline 선정 후, XGBoost/LightGBM 대비 성능 개선 폭을 확인하는 고도화 실험으로 진행한다.

## 8. 평가 지표

참고 프로젝트와 논문에서 사용한 지표:

```text
MAE
RMSE
WAPE
R2
학습시간
추론시간
```

우리 프로젝트에서 추가해야 할 지표:

```text
Stock MAE
Stock RMSE
Shortage Precision
Shortage Recall
Shortage F1
```

stock 평가는 다음과 같이 계산한다.

```text
pred_stock = current_stock + pred_delta
true_stock = target_stock
```

부족 위험 기준:

```text
shortage = stock <= 2
```

서비스 관점에서는 `MAE`뿐 아니라 `Shortage Recall`이 중요하다. 실제로 부족한 정류장을 놓치면 사용자가 도착했을 때 자전거를 못 탈 수 있기 때문이다.

## 9. 모델 선정 기준

최종 baseline 모델은 다음 기준으로 선정한다.

```text
1. Naive보다 Stock MAE가 명확히 낮다.
2. horizon별 성능이 안정적이다.
3. Shortage Recall이 높다.
4. 추론 속도가 빠르다.
5. 운영이 단순하다.
6. feature importance 등 설명 가능성이 있다.
```

성능 차이가 작다면 딥러닝보다 XGBoost/LightGBM을 우선한다.

예:

```text
GRU Stock MAE = 1.28
LightGBM Stock MAE = 1.32
```

이 정도 차이라면 첫 배포 baseline은 LightGBM이 더 현실적이다. 운영이 단순하고 설명 가능성이 높기 때문이다.

## 10. 최종 실험 로드맵

### Phase 1. Starter Baseline

```text
데이터: 2025년 9월 top200 정류장
Feature: 현재 재고 + 최근 OD 흐름 + 시간/요일
Model: Naive, RandomForest, XGBoost, LightGBM
Output: 첫 모델 비교표
```

### Phase 2. Feature Expansion

```text
데이터: 동일 기간
Feature: Phase 1 + 날씨 + 공휴일 + 정류장 정보
Model: XGBoost, LightGBM 중심
Output: feature 추가 효과 비교표
```

### Phase 3. Sequence Model

```text
데이터: station_stock_5m_master
Feature: 최근 60분 또는 120분 sequence
Model: GRU, LSTM
Output: tree baseline 대비 성능 개선 여부
```

### Phase 4. Wider Period Validation

```text
데이터: 2025년 여러 월 또는 한 분기 전체
Model: Phase 2~3에서 살아남은 후보 1~2개
Output: 계절/기간 확장 검증
```

### Phase 5. Final Baseline Selection

```text
데이터: 2022~2025 확장 데이터
Train: 2022~2024
Validation: 2025 상반기
Test: 2025 하반기
Output: 최종 baseline 모델, 모델 파일, feature schema
```

## 11. 서빙 구조

운영 시에는 상시 모니터링 없이, 사용자 경로 조회 요청 시 현재 재고 API를 호출한다.

```text
사용자 경로 조회
→ 후보 대여소 조회
→ 각 대여소 ETA 계산
→ 현재 재고 API 조회
→ feature 생성
→ model.predict(features)
→ predicted_stock = current_stock + predicted_delta
→ 부족 위험도 계산
→ 앱 응답
```

응답 예:

```json
{
  "stationId": "ST-102",
  "etaMinutes": 10,
  "currentStock": 3,
  "predictedStock": 1.7,
  "displayStock": "1~2",
  "shortageRisk": "HIGH"
}
```

## 12. 결론

현재는 최종 모델을 고르는 단계가 아니라, 최소 feature 기반 baseline 실험을 시작하는 단계다.

가장 현실적인 순서는 다음이다.

```text
1. 2025년 9월 top200 데이터로 Naive/RF/XGBoost/LightGBM 비교
2. XGBoost/LightGBM 중 유력 baseline 후보 선정
3. 날씨/공휴일/정류장 feature 추가 후 재비교
4. GRU/LSTM으로 sequence 고도화 가능성 확인
5. 성능, 추론 속도, 운영 난이도를 함께 보고 최종 baseline 선정
```

초기 baseline은 `XGBoost` 또는 `LightGBM`이 될 가능성이 높다.  
GRU/LSTM은 첫 baseline 선정 이후, 성능 개선 폭이 충분한지 확인하는 고도화 후보로 두는 것이 적절하다.
